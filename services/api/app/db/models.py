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

    # One-to-many relationship with GitHubRepository (cascade deletion)
    repositories: Mapped[list["GitHubRepository"]] = relationship(
        "GitHubRepository",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
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


class RepositorySyncStatus(str, enum.Enum):
    """Synchronization status of a discovered GitHub repository."""

    DISCOVERED = "discovered"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"


class GitHubRepository(Base):
    """Stores normalized metadata for GitHub repositories discovered for a connection."""

    __tablename__ = "github_repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("github_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    github_repository_id: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        index=True,
    )
    owner_login: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    owner_id: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    is_private: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        nullable=False,
    )
    is_fork: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        nullable=False,
    )
    is_archived: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        nullable=False,
    )
    is_disabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        nullable=False,
    )
    is_selected: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    html_url: Mapped[str] = mapped_column(
        sa.String(512),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    default_branch: Mapped[Optional[str]] = mapped_column(
        sa.String(128),
        nullable=True,
    )
    language: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    visibility: Mapped[Optional[str]] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    license_name: Mapped[Optional[str]] = mapped_column(
        sa.String(128),
        nullable=True,
    )
    sync_status: Mapped[RepositorySyncStatus] = mapped_column(
        sa.Enum(
            RepositorySyncStatus,
            name="repository_sync_status",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=True,
        ),
        default=RepositorySyncStatus.DISCOVERED,
        server_default="discovered",
        nullable=False,
        index=True,
    )
    sync_error: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    github_created_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    github_updated_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    github_pushed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
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


    connection: Mapped["GitHubConnection"] = relationship(
        "GitHubConnection",
        back_populates="repositories",
    )

    # One-to-many relationship with GitHubActivity (cascade deletion)
    activities: Mapped[list["GitHubActivity"]] = relationship(
        "GitHubActivity",
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Activity sync status tracking
    activity_sync_status: Mapped[str] = mapped_column(
        sa.String(32),
        default="idle",
        server_default="idle",
        nullable=False,
        index=True,
    )
    activity_sync_error: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    activity_sync_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    activity_last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "connection_id",
            "github_repository_id",
            name="uq_github_repositories_conn_repo",
        ),
        sa.Index(
            "ix_github_repositories_conn_sync",
            "connection_id",
            "sync_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<GitHubRepository id={self.id} full_name={self.full_name!r} status={self.sync_status.value}>"


class GitHubActivityType(str, enum.Enum):
    """Supported GitHub activity entity types for ingestion and search indexing."""

    PULL_REQUEST = "pull_request"
    ISSUE = "issue"
    COMMIT = "commit"
    REVIEW = "review"


class GitHubActivity(Base):
    """Stores normalized GitHub activity records (PRs, issues, commits, reviews)."""

    __tablename__ = "github_activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("github_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_type: Mapped[GitHubActivityType] = mapped_column(
        sa.Enum(
            GitHubActivityType,
            name="github_activity_type",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=True,
        ),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        index=True,
    )
    title: Mapped[Optional[str]] = mapped_column(
        sa.String(512),
        nullable=True,
    )
    body: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    html_url: Mapped[Optional[str]] = mapped_column(
        sa.String(1024),
        nullable=True,
    )
    author_login: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    state: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    source_created_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    ingested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )

    repository: Mapped["GitHubRepository"] = relationship(
        "GitHubRepository",
        back_populates="activities",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "repository_id",
            "activity_type",
            "external_id",
            name="uq_github_activities_repo_type_ext",
        ),
        sa.Index(
            "ix_github_activities_repo_type",
            "repository_id",
            "activity_type",
        ),
        sa.Index(
            "ix_github_activities_repo_created",
            "repository_id",
            "source_created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<GitHubActivity id={self.id} type={self.activity_type.value} ext_id={self.external_id!r}>"


