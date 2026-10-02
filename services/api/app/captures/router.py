import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.captures.schemas import (
    CaptureCreate,
    CaptureDetailResponse,
    CaptureListResponse,
    CaptureResponse,
)
from app.db.models import Capture, SourceMetadata, SourceType
from app.db.session import get_db

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
        async with db.begin():
            capture = Capture(
                source_type=SourceType(payload.source_type),
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

        # Re-query with eager-loaded source_metadata for response
        query = (
            select(Capture)
            .options(selectinload(Capture.source_metadata))
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
            .options(selectinload(Capture.source_metadata))
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
