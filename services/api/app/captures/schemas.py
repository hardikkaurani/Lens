import uuid
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import Capture, ProcessingStatus, SourceType

# Restricted source types permitted through the capture ingestion endpoint
IngestionSourceType = Literal["url", "text"]


class CaptureCreate(BaseModel):
    """Request schema for ingesting a new capture."""

    source_type: IngestionSourceType = Field(
        ...,
        description="Type of capture being ingested. Must be 'url' or 'text'.",
    )
    original_url: Optional[str] = Field(
        None,
        description="Original absolute URL for URL captures (HTTP or HTTPS only).",
    )
    title: Optional[str] = Field(
        None,
        max_length=512,
        description="Optional human-readable title for the capture.",
    )
    content: Optional[str] = Field(
        None,
        max_length=1_000_000,
        description="Textual content for text captures, or optional pre-extracted body for URL captures.",
    )
    mime_type: Optional[str] = Field(
        None,
        max_length=128,
        description="Optional MIME type identifier (e.g., 'text/plain', 'text/html').",
    )
    source_id: Optional[str] = Field(
        None,
        max_length=256,
        description="Optional external identifier from the origin platform.",
    )
    metadata: Optional[dict[str, Any]] = Field(
        None,
        description="Optional structured JSON object containing source-specific metadata.",
    )

    @model_validator(mode="after")
    def validate_capture_payload(self) -> "CaptureCreate":
        """Enforce domain validation rules depending on source_type."""
        if self.source_type == "url":
            if not self.original_url or not self.original_url.strip():
                raise ValueError("original_url is required for URL captures.")

            url = self.original_url.strip()
            try:
                parsed = urlparse(url)
            except Exception as e:
                raise ValueError(f"Invalid URL format: {e}") from e

            if not parsed.scheme or not parsed.netloc:
                raise ValueError(
                    "original_url must be an absolute URL with scheme and host (e.g., https://example.com)."
                )

            if parsed.scheme.lower() not in ("http", "https"):
                raise ValueError(
                    f"Unsupported URL scheme '{parsed.scheme}'. Only HTTP and HTTPS protocols are accepted."
                )

        elif self.source_type == "text":
            if self.content is None or not self.content.strip():
                raise ValueError(
                    "content is required and must not be empty or whitespace-only for text captures."
                )

        return self


class CaptureResponse(BaseModel):
    """Response schema exposing persisted Capture fields."""

    id: uuid.UUID
    source_type: SourceType
    processing_status: ProcessingStatus
    processing_error: Optional[str] = None
    processed_at: Optional[datetime] = None
    title: Optional[str] = None
    original_url: Optional[str] = None
    content: Optional[str] = None
    mime_type: Optional[str] = None
    source_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContentChunkResponse(BaseModel):
    """Public representation of an extracted content chunk without vector embeddings."""

    id: uuid.UUID
    chunk_index: int
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaptureDetailResponse(CaptureResponse):
    """Detailed response schema including associated source metadata and content chunks."""

    metadata: Optional[dict[str, Any]] = None
    chunks: list[ContentChunkResponse] = Field(default_factory=list)

    @classmethod
    def from_capture(cls, capture: Capture) -> "CaptureDetailResponse":
        """Convert a Capture model instance and its optional SourceMetadata and chunks to a response."""
        metadata_dict = (
            capture.source_metadata.payload
            if capture.source_metadata is not None
            else None
        )
        chunks_list = [
            ContentChunkResponse(
                id=ch.id,
                chunk_index=ch.chunk_index,
                content=ch.content,
                created_at=ch.created_at,
            )
            for ch in sorted(capture.chunks or [], key=lambda c: c.chunk_index)
        ]
        return cls(
            id=capture.id,
            source_type=capture.source_type,
            processing_status=capture.processing_status,
            processing_error=capture.processing_error,
            processed_at=capture.processed_at,
            title=capture.title,
            original_url=capture.original_url,
            content=capture.content,
            mime_type=capture.mime_type,
            source_id=capture.source_id,
            created_at=capture.created_at,
            updated_at=capture.updated_at,
            metadata=metadata_dict,
            chunks=chunks_list,
        )


class CaptureListResponse(BaseModel):
    """Paginated list of captures."""

    items: list[CaptureResponse]
    limit: int
    offset: int
    total: int
