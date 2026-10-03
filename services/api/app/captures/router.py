from datetime import datetime, timezone
import hashlib
import io
import logging
from typing import Optional
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.captures.schemas import (
    CaptureCreate,
    CaptureDetailResponse,
    CaptureListResponse,
    CaptureResponse,
)
from app.captures.validation import (
    FileTooLargeError,
    InvalidSignatureError,
    UnsupportedMediaTypeError,
    sanitize_filename,
    validate_pdf_content_type,
    validate_pdf_magic_bytes,
)
from app.core.config import Settings, get_settings
from app.db.models import Capture, ProcessingStatus, SourceMetadata, SourceType
from app.db.session import get_db
from app.queue.job import enqueue_file_ingest_job, enqueue_url_ingest_job
from app.storage import StorageClient, get_storage_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/captures", tags=["captures"])



@router.post(
    "",
    response_model=CaptureDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a new capture",
    description="Persists a new capture from URL or raw text, along with optional source metadata.",
)
async def create_capture(
    payload: CaptureCreate,
    db: AsyncSession = Depends(get_db),
) -> CaptureDetailResponse:
    """Create a new Capture record and optional SourceMetadata atomically."""
    try:
        is_url = payload.source_type == "url"
        initial_status = ProcessingStatus.PENDING if is_url else ProcessingStatus.COMPLETED
        processed_at = None if is_url else datetime.now(timezone.utc)

        async with db.begin():
            capture = Capture(
                source_type=SourceType(payload.source_type),
                processing_status=initial_status,
                processed_at=processed_at,
                title=payload.title,
                original_url=payload.original_url,
                content=payload.content,
                mime_type=payload.mime_type,
                source_id=payload.source_id,
            )
            db.add(capture)
            await db.flush()  # Populate capture.id for child relationship

            if payload.metadata is not None:
                source_meta = SourceMetadata(
                    capture_id=capture.id,
                    payload=payload.metadata,
                )
                db.add(source_meta)

        # For URL captures: enqueue asynchronous ingestion job to Redis
        if is_url:
            try:
                await enqueue_url_ingest_job(capture.id)
            except Exception as e:
                logger.exception("Failed to enqueue URL ingestion job for capture %s: %s", capture.id, e)
                # Preserve the capture in the database; record safe status without exposing Redis internals
                try:
                    async with db.begin():
                        capture.processing_status = ProcessingStatus.FAILED
                        capture.processing_error = (
                            "Background ingestion queue unavailable. Ingestion could not be scheduled."
                        )
                        capture.processed_at = datetime.now(timezone.utc)
                        db.add(capture)
                except Exception as update_err:
                    logger.warning("Failed to record queue failure on capture %s: %s", capture.id, update_err)

        # Re-query with eager-loaded source_metadata and chunks for response
        query = (
            select(Capture)
            .options(
                selectinload(Capture.source_metadata),
                selectinload(Capture.chunks),
            )
            .where(Capture.id == capture.id)
        )
        result = await db.execute(query)
        persisted = result.scalar_one()
        return CaptureDetailResponse.from_capture(persisted)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to create capture: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist capture. Transaction was safely rolled back.",
        ) from None


@router.post(
    "/upload",
    response_model=CaptureDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a binary file/PDF capture",
    description="Uploads and stores a binary document (PDF), persists capture metadata, and enqueues worker processing.",
)
async def upload_capture(
    file: UploadFile = File(..., description="Binary document to upload (PDF format)."),
    title: Optional[str] = Form(None, description="Optional human-readable title for the capture."),
    db: AsyncSession = Depends(get_db),
    storage: StorageClient = Depends(get_storage_client),
    settings: Settings = Depends(get_settings),
) -> CaptureDetailResponse:
    """Handle multipart file upload, validate binary document, persist metadata, and enqueue processing."""
    # 1. Validate MIME type
    try:
        validate_pdf_content_type(file.content_type)
    except UnsupportedMediaTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(e),
        )

    # 2. Sanitize client-provided filename
    safe_filename = sanitize_filename(file.filename)

    # 3. Bounded streaming read & SHA-256 calculation
    max_bytes = settings.MAX_UPLOAD_SIZE_BYTES
    hasher = hashlib.sha256()
    buffer = io.BytesIO()
    total_bytes = 0
    first_chunk = True

    try:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break

            if first_chunk:
                first_chunk = False
                try:
                    validate_pdf_magic_bytes(chunk)
                except InvalidSignatureError as sig_err:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail=str(sig_err),
                    )

            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"File size exceeds maximum permitted limit of {max_bytes / (1024 * 1024):.1f} MB.",
                )


            hasher.update(chunk)
            buffer.write(chunk)
    finally:
        await file.close()

    if total_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    buffer.seek(0)
    file_sha256 = hasher.hexdigest()

    # 4. Generate secure internal object key
    capture_id = uuid.uuid4()
    object_key = storage.generate_secure_object_key(capture_id, extension=".pdf")

    # 5. Put object into storage
    try:
        storage.ensure_bucket_exists()
        storage.put_object(
            key=object_key,
            data=buffer,
            length=total_bytes,
            content_type="application/pdf",
        )
    except Exception as storage_err:
        logger.exception("Failed to store object '%s' in object storage: %s", object_key, storage_err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file in object storage.",
        )

    # 6. Persist Capture & SourceMetadata in DB
    effective_title = (title or "").strip() or safe_filename
    try:
        async with db.begin():
            capture = Capture(
                id=capture_id,
                source_type=SourceType.PDF,
                processing_status=ProcessingStatus.PENDING,
                processed_at=None,
                title=effective_title,
                original_url=None,
                content=None,
                mime_type="application/pdf",
                source_id=object_key,
            )
            db.add(capture)
            await db.flush()

            metadata_payload = {
                "bucket": storage.default_bucket,
                "object_key": object_key,
                "original_filename": safe_filename,
                "byte_size": total_bytes,
                "sha256": file_sha256,
                "mime_type": "application/pdf",
            }
            source_meta = SourceMetadata(
                capture_id=capture.id,
                payload=metadata_payload,
            )
            db.add(source_meta)
    except Exception as db_err:
        logger.exception(
            "Database persistence failed for capture %s; cleaning up storage object %s: %s",
            capture_id,
            object_key,
            db_err,
        )
        storage.delete_object(object_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist capture. Uploaded object was cleaned up safely.",
        ) from None

    # 7. Enqueue background processing job
    try:
        await enqueue_file_ingest_job(capture.id)
    except Exception as queue_err:
        logger.exception("Failed to enqueue file ingestion job for capture %s: %s", capture.id, queue_err)
        try:
            async with db.begin():
                capture.processing_status = ProcessingStatus.FAILED
                capture.processing_error = (
                    "Background ingestion queue unavailable. Ingestion could not be scheduled."
                )
                capture.processed_at = datetime.now(timezone.utc)
                db.add(capture)
        except Exception as update_err:
            logger.warning("Failed to record queue failure on capture %s: %s", capture.id, update_err)

    # 8. Re-query with eager-loaded relationships
    query = (
        select(Capture)
        .options(
            selectinload(Capture.source_metadata),
            selectinload(Capture.chunks),
        )
        .where(Capture.id == capture.id)
    )
    result = await db.execute(query)
    persisted = result.scalar_one()
    return CaptureDetailResponse.from_capture(persisted)



@router.get(
    "",
    response_model=CaptureListResponse,
    summary="List captures",
    description="Retrieve a paginated list of captures ordered deterministically by newest first.",
)
async def list_captures(
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of items to return.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of items to skip.",
    ),
    db: AsyncSession = Depends(get_db),
) -> CaptureListResponse:
    """Return paginated captures ordered by created_at descending."""
    try:
        # Total count query
        count_stmt = select(func.count()).select_from(Capture)
        total = (await db.execute(count_stmt)).scalar() or 0

        # Items query (do not eagerly load child relationships for listing)
        items_stmt = (
            select(Capture)
            .order_by(Capture.created_at.desc(), Capture.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(items_stmt)
        captures = result.scalars().all()

        return CaptureListResponse(
            items=[CaptureResponse.model_validate(c) for c in captures],
            limit=limit,
            offset=offset,
            total=total,
        )
    except Exception as e:
        logger.exception("Failed to list captures: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve captures.",
        ) from None


@router.get(
    "/{capture_id}",
    response_model=CaptureDetailResponse,
    summary="Get capture by ID",
    description="Retrieve a single capture by its UUID, including any attached source metadata.",
)
async def get_capture(
    capture_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CaptureDetailResponse:
    """Retrieve a single capture by ID."""
    try:
        query = (
            select(Capture)
            .options(
                selectinload(Capture.source_metadata),
                selectinload(Capture.chunks),
            )
            .where(Capture.id == capture_id)
        )
        result = await db.execute(query)
        capture = result.scalar_one_or_none()

        if capture is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Capture '{capture_id}' not found.",
            )

        return CaptureDetailResponse.from_capture(capture)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to retrieve capture %s: %s", capture_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve capture.",
        ) from None
