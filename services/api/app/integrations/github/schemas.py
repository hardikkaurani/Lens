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
    sync_status: Optional[str] = Field(default="idle", description="Connection sync status: idle, syncing, synced, or failed.")
    last_synced_at: Optional[datetime] = Field(default=None, description="Timestamp when repositories were last synced.")
    sync_error: Optional[str] = Field(default=None, description="Error message from last failed sync attempt.")
    has_required_scope: bool = Field(default=True, description="Whether the connection has required repository scopes.")
    missing_scope_reason: Optional[str] = Field(default=None, description="Explanation and reconnect guidance if required scope is missing.")


def check_sufficient_repo_scope(scope: Optional[str]) -> bool:
    """Check if the granted OAuth scopes include repository discovery access.

    Matches 'repo' (full access to private/public repositories) or
    'public_repo' (access to public repositories).
    """
    if not scope:
        return False
    scopes = set(s.strip() for s in scope.replace(",", " ").split())
    return bool({"repo", "public_repo"} & scopes)


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
    activity_sync_status: str = "idle"
    activity_sync_error: Optional[str] = None
    activity_sync_metadata: Optional[dict[str, Any]] = None
    activity_last_synced_at: Optional[datetime] = None
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


class NormalizedGitHubActivity(BaseModel):
    """Defensively typed and sanitized representation of a GitHub activity entity."""

    activity_type: str
    external_id: str
    title: Optional[str] = None
    body: Optional[str] = None
    html_url: Optional[str] = None
    author_login: Optional[str] = None
    state: Optional[str] = None
    source_created_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    payload: dict[str, Any] = Field(default_factory=dict)


def normalize_github_pull_request(data: dict[str, Any]) -> Optional[NormalizedGitHubActivity]:
    """Normalize raw GitHub PR payload into NormalizedGitHubActivity."""
    raw_id = data.get("id")
    if raw_id is None:
        return None
    external_id = str(raw_id).strip()
    if not external_id:
        return None

    raw_user = data.get("user") or {}
    author_login = sanitize_string(raw_user.get("login"), 255) if isinstance(raw_user, dict) else None

    # State: differentiate merged from closed
    state = "merged" if data.get("merged_at") else sanitize_string(data.get("state"), 64)

    # Bounded payload with useful non-secret metadata
    head = data.get("head") or {}
    base = data.get("base") or {}
    payload = {
        "number": data.get("number"),
        "draft": bool(data.get("draft", False)),
        "merged": bool(data.get("merged_at") is not None),
        "merged_at": data.get("merged_at"),
        "head_ref": sanitize_string(head.get("ref"), 128) if isinstance(head, dict) else None,
        "base_ref": sanitize_string(base.get("ref"), 128) if isinstance(base, dict) else None,
    }

    return NormalizedGitHubActivity(
        activity_type="pull_request",
        external_id=external_id,
        title=sanitize_string(data.get("title"), 512),
        body=sanitize_string(data.get("body"), 32768),
        html_url=sanitize_string(data.get("html_url"), 1024),
        author_login=author_login,
        state=state,
        source_created_at=parse_iso_datetime(data.get("created_at")),
        source_updated_at=parse_iso_datetime(data.get("updated_at")),
        payload=payload,
    )


def normalize_github_issue(data: dict[str, Any]) -> Optional[NormalizedGitHubActivity]:
    """Normalize raw GitHub issue payload into NormalizedGitHubActivity.

    IMPORTANT: Detects and excludes pull-request objects returned by GitHub's Issues endpoint.
    """
    if "pull_request" in data:
        # Exclude PRs returned by the issues endpoint to avoid duplication/misclassification
        return None

    raw_id = data.get("id")
    if raw_id is None:
        return None
    external_id = str(raw_id).strip()
    if not external_id:
        return None

    raw_user = data.get("user") or {}
    author_login = sanitize_string(raw_user.get("login"), 255) if isinstance(raw_user, dict) else None

    payload = {
        "number": data.get("number"),
        "comments_count": data.get("comments", 0),
        "labels": [
            sanitize_string(lbl.get("name"), 64)
            for lbl in data.get("labels", [])
            if isinstance(lbl, dict) and lbl.get("name")
        ][:10],
    }

    return NormalizedGitHubActivity(
        activity_type="issue",
        external_id=external_id,
        title=sanitize_string(data.get("title"), 512),
        body=sanitize_string(data.get("body"), 32768),
        html_url=sanitize_string(data.get("html_url"), 1024),
        author_login=author_login,
        state=sanitize_string(data.get("state"), 64),
        source_created_at=parse_iso_datetime(data.get("created_at")),
        source_updated_at=parse_iso_datetime(data.get("updated_at")),
        payload=payload,
    )


def normalize_github_commit(data: dict[str, Any]) -> Optional[NormalizedGitHubActivity]:
    """Normalize raw GitHub commit payload into NormalizedGitHubActivity.

    Commits MUST use the full commit SHA as their stable external identity.
    """
    sha = data.get("sha")
    if not sha or not isinstance(sha, str) or len(sha.strip()) < 7:
        return None
    external_id = sha.strip()

    commit_data = data.get("commit") or {}
    author_data = data.get("author") or {}
    commit_author = commit_data.get("author") or {}

    author_login = None
    if isinstance(author_data, dict) and author_data.get("login"):
        author_login = sanitize_string(author_data.get("login"), 255)
    elif isinstance(commit_author, dict) and commit_author.get("name"):
        author_login = sanitize_string(commit_author.get("name"), 255)

    raw_msg = commit_data.get("message") if isinstance(commit_data, dict) else ""
    if raw_msg:
        parts = str(raw_msg).split("\n", 1)
        title = sanitize_string(parts[0], 512)
        body = sanitize_string(parts[1] if len(parts) > 1 else parts[0], 32768)
    else:
        title = f"Commit {external_id[:7]}"
        body = None

    date_str = None
    if isinstance(commit_author, dict):
        date_str = commit_author.get("date")

    source_dt = parse_iso_datetime(date_str)

    payload = {
        "sha": external_id,
        "author_name": sanitize_string(commit_author.get("name"), 128) if isinstance(commit_author, dict) else None,
    }

    return NormalizedGitHubActivity(
        activity_type="commit",
        external_id=external_id,
        title=title,
        body=body,
        html_url=sanitize_string(data.get("html_url"), 1024),
        author_login=author_login,
        state=None,
        source_created_at=source_dt,
        source_updated_at=source_dt,
        payload=payload,
    )


def normalize_github_review(
    data: dict[str, Any],
    pull_number: int,
) -> Optional[NormalizedGitHubActivity]:
    """Normalize raw GitHub PR review payload into NormalizedGitHubActivity."""
    raw_id = data.get("id")
    if raw_id is None:
        return None
    external_id = str(raw_id).strip()
    if not external_id:
        return None

    raw_user = data.get("user") or {}
    author_login = sanitize_string(raw_user.get("login"), 255) if isinstance(raw_user, dict) else None
    state = sanitize_string(data.get("state"), 64)

    title = f"Review on PR #{pull_number}: {state or 'SUBMITTED'}"
    source_dt = parse_iso_datetime(data.get("submitted_at"))

    payload = {
        "pull_number": pull_number,
        "commit_id": sanitize_string(data.get("commit_id"), 64),
    }

    return NormalizedGitHubActivity(
        activity_type="review",
        external_id=external_id,
        title=title,
        body=sanitize_string(data.get("body"), 32768),
        html_url=sanitize_string(data.get("html_url"), 1024),
        author_login=author_login,
        state=state,
        source_created_at=source_dt,
        source_updated_at=source_dt,
        payload=payload,
    )


class GitHubActivityResponse(BaseModel):
    """Public representation of an ingested GitHub activity."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    activity_type: str
    external_id: str
    title: Optional[str] = None
    body: Optional[str] = None
    html_url: Optional[str] = None
    author_login: Optional[str] = None
    state: Optional[str] = None
    source_created_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    ingested_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class GitHubActivityListResponse(BaseModel):
    """Paginated list response of ingested GitHub activities."""

    items: list[GitHubActivityResponse]
    total: int
    limit: int
    offset: int


class GitHubActivitySyncRequest(BaseModel):
    """Request payload to trigger GitHub activity synchronization."""

    repository_ids: Optional[list[uuid.UUID]] = Field(
        default=None,
        description="Optional list of selected repository IDs to synchronize. Defaults to all selected repositories.",
    )


class GitHubActivitySyncResponse(BaseModel):
    """Response returned when GitHub activity synchronization is initiated or completed."""

    status: str = Field(..., description="Sync status: 'enqueued', 'completed', 'partial', 'already_syncing', or 'failed'.")
    synced_repositories: int = Field(default=0, description="Number of repositories synced.")
    synced_activities: int = Field(default=0, description="Total activity records persisted.")
    message: str = Field(default="GitHub activity synchronization completed.")
    details: Optional[dict[str, Any]] = Field(default=None, description="Per-repository sync breakdown.")

