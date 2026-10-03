"""URL capture ingestion processor coordinating fetch, extraction, chunking, and persistence."""

from datetime import datetime, timezone
import hashlib
import logging
from typing import Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Import domain models and session from api package
from app.db.models import Capture, ContentChunk, ProcessingStatus, SourceType
from app.db.session import AsyncSessionLocal
from app.embeddings import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingTimeoutError,
    get_embedding_provider,
)
from app.storage import (
    ObjectNotFoundError,
    StorageClient,
    StorageConnectionError,
    StorageError,
    get_storage_client,
)
from worker.chunker import chunk_text
from worker.extractor import (
    ExtractionError,
    InsufficientContentError,
    extract_and_normalize_html,
)
from worker.fetcher import (
    FetchError,
    FetchTimeoutError,
    InvalidContentTypeError,
    ResponseSizeLimitExceededError,
    SSRFBlockedError,
    safe_fetch_url,
)
from worker.pdf_extractor import (
    CorruptObjectError,
    EncryptedPDFError,
    MalformedPDFError,
    PDFExtractionError,
    PDFPageLimitExceededError,
    extract_text_from_pdf,
)

logger = logging.getLogger(__name__)


def sanitize_error_message(exc: Exception) -> str:
    """Produce a safe, client-facing error description without stack traces or sensitive details."""
    if isinstance(exc, SSRFBlockedError):
        return f"SSRF security policy blocked destination: {str(exc).split(':')[-1].strip()}"
    if isinstance(exc, InvalidContentTypeError):
        return f"Unsupported content type: {exc}"
    if isinstance(exc, ResponseSizeLimitExceededError):
        return "Remote webpage exceeded the maximum permitted size limit of 2MB."
    if isinstance(exc, FetchTimeoutError):
        return "Connection or read timeout while attempting to fetch remote URL."
    if isinstance(exc, InsufficientContentError):
        return f"Extraction failed: {exc}"
    if isinstance(exc, EncryptedPDFError):
        return "Encrypted or password-protected PDF files are not supported."
    if isinstance(exc, MalformedPDFError):
        return "Corrupted or unreadable PDF document format."
    if isinstance(exc, PDFPageLimitExceededError):
        return "PDF document exceeds maximum permitted page limit."
    if isinstance(exc, ObjectNotFoundError):
        return "Target document could not be located in object storage."
    if isinstance(exc, CorruptObjectError):
        return "Stored document integrity check failed (hash or size mismatch)."
    if isinstance(exc, (StorageError, StorageConnectionError)):
        return "Object storage service unavailable or connection failed."
    if isinstance(exc, EmbeddingTimeoutError):
        return "Embedding generation timed out."
    if isinstance(exc, EmbeddingDimensionError):
        return "Embedding generation failed due to invalid vector dimension."
    if isinstance(exc, EmbeddingError):
        return f"Embedding generation failed: {exc}"
    if isinstance(exc, (FetchError, ExtractionError, PDFExtractionError)):
        return f"Ingestion failed: {exc}"

    return "An unexpected error occurred during capture processing."



async def process_url_capture(
    capture_id: uuid.UUID,
    session_factory=AsyncSessionLocal,
    allow_localhost: bool = False,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> bool:
    """Fetch, extract, chunk, generate embeddings, and persist an ingested URL capture.

    Idempotent: Generates embeddings for all non-empty chunks and replaces any
    existing chunks for this capture atomically in a single database transaction.
    """
    logger.info("Beginning processing for capture %s", capture_id)

    target_url: Optional[str] = None

    # Step 1: Mark capture as PROCESSING and retrieve original URL
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Capture).where(Capture.id == capture_id))
            capture = result.scalar_one_or_none()

            if not capture:
                logger.warning("Capture %s not found in database; abandoning job", capture_id)
                return False

            if capture.source_type != SourceType.URL:
                logger.info(
                    "Capture %s has source_type '%s', skipping URL ingestion",
                    capture_id,
                    capture.source_type.value,
                )
                return True

            target_url = capture.original_url
            capture.processing_status = ProcessingStatus.PROCESSING
            capture.processing_error = None

    # Step 2: Fetch, extract, chunk, and embed outside the database transaction
    try:
        if not target_url:
            raise FetchError("Capture record does not contain an original_url.")

        # 2a. Fetch HTML safely with SSRF protections
        fetched = await safe_fetch_url(target_url, allow_localhost=allow_localhost)

        # 2b. Extract readable body text and page title
        extracted_title, normalized_text = extract_and_normalize_html(fetched.html)

        # 2c. Partition into deterministic chunks
        chunks = chunk_text(normalized_text)

        # 2d. Generate 1536-dimensional embeddings for each chunk
        embeddings: list[list[float]] = []
        if chunks:
            provider = embedding_provider or get_embedding_provider()
            logger.info(
                "Generating embeddings for capture %s (%d chunks) using model %s",
                capture_id,
                len(chunks),
                provider.model_name,
            )
            embeddings = await provider.embed_texts(chunks)
            if len(embeddings) != len(chunks):
                raise EmbeddingProviderError(
                    f"Mismatched embedding count: got {len(embeddings)} vectors for {len(chunks)} chunks."
                )

        # Step 3: Atomic database persistence of chunks, embeddings, and completed state
        async with session_factory() as session:
            async with session.begin():
                # Idempotency: Clean up any existing chunks from previous attempts
                await session.execute(
                    delete(ContentChunk).where(ContentChunk.capture_id == capture_id)
                )

                # Persist new deterministic chunks with 1536-dimensional embeddings
                for index, (chunk_content, chunk_vec) in enumerate(zip(chunks, embeddings)):
                    chunk = ContentChunk(
                        capture_id=capture_id,
                        chunk_index=index,
                        content=chunk_content,
                        embedding=chunk_vec,
                    )
                    session.add(chunk)

                # Update Capture status to COMPLETED
                result = await session.execute(select(Capture).where(Capture.id == capture_id))
                persisted_capture = result.scalar_one()

                persisted_capture.processing_status = ProcessingStatus.COMPLETED
                persisted_capture.processed_at = datetime.now(timezone.utc)
                persisted_capture.processing_error = None

                # Backfill title if not supplied by client
                if not persisted_capture.title and extracted_title:
                    persisted_capture.title = extracted_title

                # Populate content field with normalized extracted text
                if not persisted_capture.content:
                    persisted_capture.content = normalized_text

        logger.info(
            "Successfully processed URL capture %s: generated %d chunks with embeddings",
            capture_id,
            len(chunks),
        )
        return True

    except Exception as exc:
        safe_error = sanitize_error_message(exc)
        logger.warning("URL ingestion failed for capture %s: %s", capture_id, safe_error)

        # Record failure state on Capture record
        try:
            async with session_factory() as session:
                async with session.begin():
                    result = await session.execute(select(Capture).where(Capture.id == capture_id))
                    persisted_capture = result.scalar_one_or_none()
                    if persisted_capture:
                        persisted_capture.processing_status = ProcessingStatus.FAILED
                        persisted_capture.processed_at = datetime.now(timezone.utc)
                        persisted_capture.processing_error = safe_error
        except Exception as record_err:
            logger.error(
                "Failed to persist failure status for capture %s: %s",
                capture_id,
                record_err,
            )

        return False


async def process_file_capture(
    capture_id: uuid.UUID,
    session_factory=AsyncSessionLocal,
    storage_client: Optional[StorageClient] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> bool:
    """Fetch stored binary document from S3/MinIO, extract text, chunk, embed, and persist.

    Idempotent: Generates embeddings for all chunks and replaces any existing chunks
    for this capture atomically in a single database transaction.
    """
    logger.info("Beginning file processing for capture %s", capture_id)

    bucket: Optional[str] = None
    object_key: Optional[str] = None
    expected_sha256: Optional[str] = None
    expected_size: Optional[int] = None

    # Step 1: Mark capture as PROCESSING and retrieve storage coordinates
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Capture)
                .options(selectinload(Capture.source_metadata))
                .where(Capture.id == capture_id)
            )
            capture = result.scalar_one_or_none()

            if not capture:
                logger.warning("Capture %s not found in database; abandoning job", capture_id)
                return False

            if capture.source_type != SourceType.PDF:
                logger.info(
                    "Capture %s has source_type '%s', skipping file ingestion",
                    capture_id,
                    capture.source_type.value,
                )
                return True

            capture.processing_status = ProcessingStatus.PROCESSING
            capture.processing_error = None

            if capture.source_metadata and capture.source_metadata.payload:
                meta = capture.source_metadata.payload
                bucket = meta.get("bucket")
                object_key = meta.get("object_key")
                expected_sha256 = meta.get("sha256")
                expected_size = meta.get("byte_size")

            if not object_key and capture.source_id:
                object_key = capture.source_id

    # Step 2: Retrieve object, verify integrity, extract, chunk, and embed
    try:
        if not object_key:
            raise CorruptObjectError("Capture record does not contain an object_key reference.")

        storage = storage_client or get_storage_client()
        data = storage.get_object(object_key, bucket=bucket)

        if expected_size is not None and len(data) != expected_size:
            raise CorruptObjectError(
                f"Stored object size mismatch: expected {expected_size} bytes, got {len(data)}"
            )

        if expected_sha256:
            actual_sha256 = hashlib.sha256(data).hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                raise CorruptObjectError("Stored object SHA-256 integrity verification failed.")

        # Extract text and optional title from PDF
        extracted_title, normalized_text = extract_text_from_pdf(data)

        # Deterministic chunking
        chunks = chunk_text(normalized_text)

        # Embedding generation
        embeddings: list[list[float]] = []
        if chunks:
            provider = embedding_provider or get_embedding_provider()
            logger.info(
                "Generating embeddings for file capture %s (%d chunks) using model %s",
                capture_id,
                len(chunks),
                provider.model_name,
            )
            embeddings = await provider.embed_texts(chunks)
            if len(embeddings) != len(chunks):
                raise EmbeddingProviderError(
                    f"Mismatched embedding count: got {len(embeddings)} vectors for {len(chunks)} chunks."
                )

        # Step 3: Atomic database persistence of chunks, embeddings, and completed state
        async with session_factory() as session:
            async with session.begin():
                # Idempotency: clean up any existing chunks from prior attempts
                await session.execute(
                    delete(ContentChunk).where(ContentChunk.capture_id == capture_id)
                )

                for index, (chunk_content, chunk_vec) in enumerate(zip(chunks, embeddings)):
                    chunk = ContentChunk(
                        capture_id=capture_id,
                        chunk_index=index,
                        content=chunk_content,
                        embedding=chunk_vec,
                    )
                    session.add(chunk)

                result = await session.execute(select(Capture).where(Capture.id == capture_id))
                persisted_capture = result.scalar_one()

                persisted_capture.processing_status = ProcessingStatus.COMPLETED
                persisted_capture.processed_at = datetime.now(timezone.utc)
                persisted_capture.processing_error = None

                if not persisted_capture.title and extracted_title:
                    persisted_capture.title = extracted_title

                if not persisted_capture.content:
                    persisted_capture.content = normalized_text

        logger.info(
            "Successfully processed file capture %s: generated %d chunks with embeddings",
            capture_id,
            len(chunks),
        )
        return True

    except Exception as exc:
        safe_error = sanitize_error_message(exc)
        logger.warning("File ingestion failed for capture %s: %s", capture_id, safe_error)

        try:
            async with session_factory() as session:
                async with session.begin():
                    result = await session.execute(select(Capture).where(Capture.id == capture_id))
                    persisted_capture = result.scalar_one_or_none()
                    if persisted_capture:
                        persisted_capture.processing_status = ProcessingStatus.FAILED
                        persisted_capture.processed_at = datetime.now(timezone.utc)
                        persisted_capture.processing_error = safe_error
        except Exception as record_err:
            logger.error(
                "Failed to persist failure status for file capture %s: %s",
                capture_id,
                record_err,
            )

        return False

