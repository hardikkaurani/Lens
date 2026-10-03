import enum
import uuid
from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Schema placeholder dimension for future embeddings (e.g. OpenAI text-embedding-3-small)
# Storage-only placeholder; actual embedding generation is implemented in subsequent stages.
DEFAULT_EMBEDDING_DIMENSION = 1536


class SourceType(str, enum.Enum):
    """Supported V1 ingestion source types for captured items."""

    URL = "url"
    TEXT = "text"
    IMAGE = "image"
    PDF = "pdf"
    FILE = "file"
    GITHUB = "github"


class ProcessingStatus(str, enum.Enum):
    """Lifecycle processing status for captured items."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Capture(Base):
    """Core domain model representing a captured item saved into LENS."""

    __tablename__ = "captures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_type: Mapped[SourceType] = mapped_column(
        sa.Enum(
            SourceType,
            name="source_type",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=True,
        ),
        nullable=False,
        index=True,
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        sa.Enum(
            ProcessingStatus,
            name="processing_status",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=True,
        ),
        default=ProcessingStatus.PENDING,
        server_default="pending",
        nullable=False,
        index=True,
    )
    processing_error: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    title: Mapped[Optional[str]] = mapped_column(
        sa.String(512),
        nullable=True,
    )
    original_url: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    content: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        sa.String(128),
        nullable=True,
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        sa.String(256),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # One-to-many relationship with ContentChunk (cascade deletion)
    chunks: Mapped[list["ContentChunk"]] = relationship(
        "ContentChunk",
        back_populates="capture",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ContentChunk.chunk_index",
    )

    # One-to-one relationship with SourceMetadata (cascade deletion)
    source_metadata: Mapped[Optional["SourceMetadata"]] = relationship(
        "SourceMetadata",
        back_populates="capture",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    # Full-text search tsvector computed column (title search)
    tsv: Mapped[Optional[Any]] = mapped_column(
        TSVECTOR,
        sa.Computed("to_tsvector('english', coalesce(title, ''))", persisted=True),
        nullable=True,
    )

    __table_args__ = (
        sa.Index(
            "ix_captures_tsv",
            "tsv",
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return f"<Capture id={self.id} type={self.source_type.value} title={self.title!r}>"


class ContentChunk(Base):
    """Searchable chunk of content derived from a parent Capture."""

    __tablename__ = "content_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("captures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    # Nullable vector column reserving embedding storage capacity in pgvector
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(DEFAULT_EMBEDDING_DIMENSION),
        nullable=True,
    )
    # Full-text search tsvector computed column (chunk content search)
    tsv: Mapped[Optional[Any]] = mapped_column(
        TSVECTOR,
        sa.Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    # Relationship back to parent Capture
    capture: Mapped["Capture"] = relationship(
        "Capture",
        back_populates="chunks",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "capture_id",
            "chunk_index",
            name="uq_content_chunks_capture_chunk",
        ),
        sa.Index(
            "ix_content_chunks_tsv",
            "tsv",
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return f"<ContentChunk id={self.id} capture_id={self.capture_id} index={self.chunk_index}>"


class SourceMetadata(Base):
    """Source-specific structured metadata stored as JSONB for a parent Capture."""

    __tablename__ = "source_metadata"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("captures.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # Stored as column 'metadata' in PostgreSQL; named 'payload' in Python to avoid Base.metadata conflict
    payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # Relationship back to parent Capture
    capture: Mapped["Capture"] = relationship(
        "Capture",
        back_populates="source_metadata",
    )

    def __repr__(self) -> str:
        return f"<SourceMetadata id={self.id} capture_id={self.capture_id}>"


class GitHubConnection(Base):
    """Stores verified GitHub OAuth connection metadata and encrypted access tokens."""

    __tablename__ = "github_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider: Mapped[str] = mapped_column(
        sa.String(32),
        default="github",
        nullable=False,
        index=True,
    )
    github_user_id: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    github_username: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    encrypted_access_token: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    token_type: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
        default="bearer",
    )
    scope: Mapped[Optional[str]] = mapped_column(
        sa.String(512),
        nullable=True,
    )
    token_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "provider",
            "github_user_id",
            name="uq_github_connections_provider_user",
        ),
    )

    def __repr__(self) -> str:
        return f"<GitHubConnection id={self.id} user={self.github_username!r} provider={self.provider!r}>"

