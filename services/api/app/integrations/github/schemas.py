import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class GitHubConnectionStatus(BaseModel):
    """Safe public representation of a GitHub OAuth integration status."""

    connected: bool = Field(..., description="Whether a valid GitHub account connection exists.")
    github_username: Optional[str] = Field(default=None, description="Connected GitHub login/username.")
    github_user_id: Optional[str] = Field(default=None, description="Connected GitHub account identifier.")
    scope: Optional[str] = Field(default=None, description="Authorized OAuth scopes.")
    connected_at: Optional[datetime] = Field(default=None, description="Timestamp when connection was established.")
    last_verified_at: Optional[datetime] = Field(default=None, description="Timestamp when connection was last verified.")


class GitHubDisconnectResponse(BaseModel):
    """Response returned upon disconnecting GitHub."""

    status: str = Field(default="disconnected", description="Result status.")
    message: str = Field(default="GitHub connection disconnected successfully.")


class NormalizedGitHubRepository(BaseModel):
    """Defensively typed and sanitized representation of a GitHub repository from API."""

    github_repository_id: str
    name: str
    full_name: str
    owner_login: str
    owner_id: Optional[str] = None
    is_private: bool = False
    is_fork: bool = False
    is_archived: bool = False
    is_disabled: bool = False
    html_url: str
    description: Optional[str] = None
    default_branch: Optional[str] = None
    language: Optional[str] = None
    visibility: Optional[str] = None
    license_name: Optional[str] = None
    github_created_at: Optional[datetime] = None
    github_updated_at: Optional[datetime] = None
    github_pushed_at: Optional[datetime] = None


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    """Parse ISO 8601 datetime strings safely."""
    if not value or not isinstance(value, str):
        return None
    try:
        clean = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def sanitize_string(value: Any, max_length: int) -> Optional[str]:
    """Sanitize and bound untrusted strings, stripping null bytes and dangerous control chars."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    # Strip null bytes
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def normalize_github_repository(data: dict[str, Any]) -> Optional[NormalizedGitHubRepository]:
    """Normalize a raw GitHub API repository payload into a validated NormalizedGitHubRepository.

    Returns None if required identity fields (id, name, full_name, html_url) are missing or invalid.
    """
    raw_id = data.get("id")
    if raw_id is None:
        return None
    repo_id_str = str(raw_id).strip()
    if not repo_id_str:
        return None

    raw_name = data.get("name")
    raw_full_name = data.get("full_name")
    raw_html_url = data.get("html_url")

    name = sanitize_string(raw_name, 255)
    full_name = sanitize_string(raw_full_name, 255)
    html_url = sanitize_string(raw_html_url, 512)

    if not name or not full_name or not html_url:
        return None

    # Enforce safe URL schemes
    if not (html_url.startswith("https://") or html_url.startswith("http://")):
        return None

    raw_owner = data.get("owner")
    owner_data: dict[str, Any] = raw_owner if isinstance(raw_owner, dict) else {}
    owner_login = sanitize_string(owner_data.get("login"), 255) or "unknown"
    owner_id_raw = owner_data.get("id")
    owner_id = str(owner_id_raw).strip() if owner_id_raw is not None else None

    # License
    raw_license = data.get("license")
    license_data: dict[str, Any] = raw_license if isinstance(raw_license, dict) else {}
    license_name = sanitize_string(license_data.get("spdx_id") or license_data.get("name"), 128)

    return NormalizedGitHubRepository(
        github_repository_id=repo_id_str,
        name=name,
        full_name=full_name,
        owner_login=owner_login,
        owner_id=owner_id,
        is_private=bool(data.get("private", False)),
        is_fork=bool(data.get("fork", False)),
        is_archived=bool(data.get("archived", False)),
        is_disabled=bool(data.get("disabled", False)),
        html_url=html_url,
        description=sanitize_string(data.get("description"), 1000),
        default_branch=sanitize_string(data.get("default_branch"), 128),
        language=sanitize_string(data.get("language"), 64),
        visibility=sanitize_string(data.get("visibility"), 32),
        license_name=license_name,
        github_created_at=parse_iso_datetime(data.get("created_at")),
        github_updated_at=parse_iso_datetime(data.get("updated_at")),
        github_pushed_at=parse_iso_datetime(data.get("pushed_at")),
    )


class GitHubRepositoryResponse(BaseModel):
    """Public representation of a discovered GitHub repository."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    github_repository_id: str
    name: str
    full_name: str
    owner_login: str
    owner_id: Optional[str] = None
    is_private: bool
    is_fork: bool
    is_archived: bool
    is_disabled: bool
    is_selected: bool
    html_url: str
    description: Optional[str] = None
    default_branch: Optional[str] = None
    language: Optional[str] = None
    visibility: Optional[str] = None
    license_name: Optional[str] = None
    sync_status: str
    sync_error: Optional[str] = None
    github_created_at: Optional[datetime] = None
    github_updated_at: Optional[datetime] = None
    github_pushed_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class GitHubRepoListResponse(BaseModel):
    """Paginated list response of GitHub repositories."""

    items: list[GitHubRepositoryResponse]
    total: int
    limit: int
    offset: int


class GitHubRepoSyncResponse(BaseModel):
    """Response returned upon initiating or completing repository synchronization."""

    status: str = Field(..., description="Sync status: 'completed', 'enqueued', or 'already_syncing'.")
    synced_count: int = Field(default=0, description="Number of repositories processed.")
    total: int = Field(default=0, description="Total repositories currently discovered for connection.")
    message: str = Field(default="Repository synchronization completed successfully.")


class GitHubRepositorySelectRequest(BaseModel):
    """Payload to update repository selection UI state."""

    is_selected: bool = Field(..., description="Whether repository is selected for future sync/ingestion.")
