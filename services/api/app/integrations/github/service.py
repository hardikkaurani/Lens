from datetime import datetime, timezone
import json
import logging
import secrets
import time
from typing import Any, Optional
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptionError, decrypt_secret, encrypt_secret
from app.db.models import GitHubConnection, GitHubRepository, RepositorySyncStatus
from app.db.session import get_redis_client
from app.integrations.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubClientError,
    GitHubRateLimitError,
    GitHubTimeoutError,
    get_github_client,
)
from app.integrations.github.schemas import (
    NormalizedGitHubRepository,
    normalize_github_repository,
)

logger = logging.getLogger(__name__)

# Cookie name for browser session binding
OAUTH_COOKIE_NAME = "lens_oauth_session"

# Redis key prefix for OAuth states
OAUTH_STATE_KEY_PREFIX = "lens:oauth:github:state:"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes

# Repository discovery & sync constants
DEFAULT_REPO_PAGE_SIZE = 100
MAX_REPOSITORIES_PER_SYNC = 500
MAX_PAGES_PER_SYNC = 10
SYNC_LOCK_TTL_SECONDS = 60
SYNC_LOCK_KEY_PREFIX = "lens:lock:github_sync:"

# In-memory fallback caches when Redis is unavailable (strictly for dev/test environments)
_memory_state_cache: dict[str, tuple[str, float]] = {}
_memory_lock_cache: dict[str, float] = {}


class OAuthStorageError(Exception):
    """Raised when OAuth state storage is unavailable or fails."""
    pass


def generate_oauth_state() -> str:
    """Generate a high-entropy, cryptographically secure OAuth state string."""
    return secrets.token_urlsafe(32)


def generate_session_binding() -> str:
    """Generate a high-entropy, cryptographically secure browser session identifier."""
    return secrets.token_urlsafe(32)


async def store_oauth_state(
    state: str,
    session_binding: str,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Store OAuth state bound to a browser session with a 10-minute expiration.

    In production (APP_ENV == 'production'), Redis is mandatory. If Redis fails,
    an OAuthStorageError is raised rather than falling back to process-local memory.
    """
    if not state or not state.strip():
        raise ValueError("OAuth state cannot be empty.")
    if not session_binding or not session_binding.strip():
        raise ValueError("Session binding cannot be empty.")

    from app.core.config import get_settings

    settings = get_settings()
    is_production = settings.APP_ENV == "production"

    payload: dict[str, Any] = dict(metadata) if metadata else {}
    payload["session_binding"] = session_binding
    payload["created_at"] = time.time()
    payload_str = json.dumps(payload)
    key = f"{OAUTH_STATE_KEY_PREFIX}{state}"

    # Try storing in Redis
    try:
        redis = get_redis_client()
        await redis.set(key, payload_str, ex=OAUTH_STATE_TTL_SECONDS)
        return
    except Exception as exc:
        if is_production:
            logger.error("Redis unavailable for OAuth state in production: %s", exc)
            raise OAuthStorageError("OAuth storage is unavailable.") from exc
        logger.warning("Redis unavailable for OAuth state storage; falling back to memory store: %s", exc)

    # Fallback to local memory store (strictly allowed in dev/test only)
    expires_at = time.time() + OAUTH_STATE_TTL_SECONDS
    _memory_state_cache[state] = (payload_str, expires_at)


async def validate_and_consume_oauth_state(
    state: str,
    expected_session_binding: Optional[str],
) -> Optional[dict[str, Any]]:
    """Validate and atomically consume (delete) an OAuth state.

    Verifies:
    1. State exists and is unexpired.
    2. Expected browser session binding is present and matches the stored binding.
    3. State is atomically consumed (single-use).

    Returns stored metadata if all validations pass; returns None otherwise.
    """
    if not state or not state.strip():
        return None
    if not expected_session_binding or not expected_session_binding.strip():
        return None

    from app.core.config import get_settings

    settings = get_settings()
    is_production = settings.APP_ENV == "production"
    key = f"{OAUTH_STATE_KEY_PREFIX}{state}"
    payload_str: Optional[str] = None

    # 1. Try Redis with atomic getdel
    try:
        redis = get_redis_client()
        val = await redis.getdel(key)
        if val is not None:
            payload_str = val if isinstance(val, str) else val.decode("utf-8")
    except Exception as exc:
        if is_production:
            logger.error("Redis getdel failed for OAuth state in production: %s", exc)
            raise OAuthStorageError("OAuth storage is unavailable.") from exc
        logger.warning("Redis getdel failed for OAuth state; checking memory fallback: %s", exc)

    # 2. Check in-memory fallback if not in production and not found in Redis
    if payload_str is None and not is_production:
        now = time.time()
        # Clean up expired items
        expired_keys = [k for k, (_, exp) in _memory_state_cache.items() if exp < now]
        for k in expired_keys:
            _memory_state_cache.pop(k, None)

        if state in _memory_state_cache:
            raw_payload, expires_at = _memory_state_cache.pop(state)
            if expires_at >= now:
                payload_str = raw_payload

    if payload_str is None:
        return None

    # Parse payload
    try:
        data = json.loads(payload_str)
        if not isinstance(data, dict):
            return None
    except Exception:
        return None

    # Verify session binding using constant-time comparison
    stored_binding = data.get("session_binding")
    if not stored_binding or not secrets.compare_digest(stored_binding, expected_session_binding):
        logger.warning("OAuth session binding mismatch for state: %s...", state[:8])
        return None

    return data


async def get_github_connection(db: AsyncSession) -> Optional[GitHubConnection]:
    """Retrieve the active GitHub connection record, if one exists."""
    stmt = select(GitHubConnection).where(GitHubConnection.provider == "github").limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_github_connection(
    db: AsyncSession,
    github_user_id: str,
    github_username: str,
    access_token: str,
    scope: Optional[str] = None,
    token_type: Optional[str] = "bearer",
    token_metadata: Optional[dict[str, Any]] = None,
) -> GitHubConnection:
    """Encrypt access token and persist or update the GitHub connection record."""
    encrypted_token = encrypt_secret(access_token)
    now = datetime.now(timezone.utc)

    existing = await get_github_connection(db)
    if existing:
        existing.github_user_id = github_user_id
        existing.github_username = github_username
        existing.encrypted_access_token = encrypted_token
        existing.scope = scope
        existing.token_type = token_type or "bearer"
        existing.token_metadata = token_metadata or {}
        existing.last_verified_at = now
        existing.updated_at = now
        await db.commit()
        await db.refresh(existing)
        return existing

    connection = GitHubConnection(
        provider="github",
        github_user_id=github_user_id,
        github_username=github_username,
        encrypted_access_token=encrypted_token,
        token_type=token_type or "bearer",
        scope=scope,
        token_metadata=token_metadata or {},
        created_at=now,
        updated_at=now,
        last_verified_at=now,
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


async def delete_github_connection(db: AsyncSession) -> bool:
    """Delete all stored GitHub connection records idempotently."""
    stmt = delete(GitHubConnection).where(GitHubConnection.provider == "github")
    result = await db.execute(stmt)
    rowcount = getattr(result, "rowcount", 0)
    await db.commit()
    return isinstance(rowcount, int) and rowcount > 0


async def acquire_sync_lock(connection_id: uuid.UUID) -> bool:
    """Acquire a temporary distributed lock for repository sync to prevent concurrent runs."""
    key = f"{SYNC_LOCK_KEY_PREFIX}{connection_id}"
    now = time.time()
    try:
        redis = get_redis_client()
        res = await redis.set(key, "1", ex=SYNC_LOCK_TTL_SECONDS, nx=True)
        return bool(res)
    except Exception as exc:
        logger.warning("Redis unavailable for sync lock; checking local memory cache: %s", exc)

    # In-memory fallback
    if key in _memory_lock_cache:
        if _memory_lock_cache[key] > now:
            return False
    _memory_lock_cache[key] = now + SYNC_LOCK_TTL_SECONDS
    return True


async def release_sync_lock(connection_id: uuid.UUID) -> None:
    """Release distributed lock for repository sync."""
    key = f"{SYNC_LOCK_KEY_PREFIX}{connection_id}"
    try:
        redis = get_redis_client()
        await redis.delete(key)
    except Exception:
        pass
    _memory_lock_cache.pop(key, None)


async def upsert_repositories(
    db: AsyncSession,
    connection_id: uuid.UUID,
    normalized_repos: list[NormalizedGitHubRepository],
) -> int:
    """Idempotently persist or update GitHub repositories for a connection.

    Protects against duplicates using external github_repository_id + connection_id.
    Preserves internal UUID PK and is_selected preference on rename or update.
    """
    if not normalized_repos:
        return 0

    now = datetime.now(timezone.utc)
    stmt = select(GitHubRepository).where(GitHubRepository.connection_id == connection_id)
    res = await db.execute(stmt)
    existing_repos = res.scalars().all()
    by_github_id: dict[str, GitHubRepository] = {
        r.github_repository_id: r for r in existing_repos
    }

    count = 0
    for repo_data in normalized_repos:
        existing = by_github_id.get(repo_data.github_repository_id)
        if existing:
            # Update mutable fields, preserving internal PK and is_selected state
            existing.name = repo_data.name
            existing.full_name = repo_data.full_name
            existing.owner_login = repo_data.owner_login
            existing.owner_id = repo_data.owner_id
            existing.is_private = repo_data.is_private
            existing.is_fork = repo_data.is_fork
            existing.is_archived = repo_data.is_archived
            existing.is_disabled = repo_data.is_disabled
            existing.html_url = repo_data.html_url
            existing.description = repo_data.description
            existing.default_branch = repo_data.default_branch
            existing.language = repo_data.language
            existing.visibility = repo_data.visibility
            existing.license_name = repo_data.license_name
            existing.github_created_at = repo_data.github_created_at
            existing.github_updated_at = repo_data.github_updated_at
            existing.github_pushed_at = repo_data.github_pushed_at
            existing.sync_status = RepositorySyncStatus.SYNCED
            existing.sync_error = None
            existing.last_synced_at = now
            existing.updated_at = now
        else:
            new_repo = GitHubRepository(
                connection_id=connection_id,
                github_repository_id=repo_data.github_repository_id,
                name=repo_data.name,
                full_name=repo_data.full_name,
                owner_login=repo_data.owner_login,
                owner_id=repo_data.owner_id,
                is_private=repo_data.is_private,
                is_fork=repo_data.is_fork,
                is_archived=repo_data.is_archived,
                is_disabled=repo_data.is_disabled,
                is_selected=False,
                html_url=repo_data.html_url,
                description=repo_data.description,
                default_branch=repo_data.default_branch,
                language=repo_data.language,
                visibility=repo_data.visibility,
                license_name=repo_data.license_name,
                sync_status=RepositorySyncStatus.SYNCED,
                sync_error=None,
                github_created_at=repo_data.github_created_at,
                github_updated_at=repo_data.github_updated_at,
                github_pushed_at=repo_data.github_pushed_at,
                last_synced_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(new_repo)
            by_github_id[repo_data.github_repository_id] = new_repo
        count += 1

    await db.commit()
    return count


async def discover_and_sync_repositories(
    db: AsyncSession,
    connection: GitHubConnection,
    github_client: Optional[GitHubClient] = None,
    max_repos: int = MAX_REPOSITORIES_PER_SYNC,
    page_size: int = DEFAULT_REPO_PAGE_SIZE,
) -> dict[str, Any]:
    """Discover and synchronize repositories from GitHub API for an active connection.

    Decrypts the access token server-side.
    Performs bounded pagination and rate-limit aware fetching.
    Upserts repositories idempotently.
    """
    client = github_client or get_github_client()

    # 1. Decrypt token securely server-side
    try:
        access_token = decrypt_secret(connection.encrypted_access_token)
    except EncryptionError as err:
        logger.error("Failed to decrypt access token for connection %s: %s", connection.id, err)
        raise

    all_normalized: list[NormalizedGitHubRepository] = []
    seen_ids: set[str] = set()

    # 2. Bounded pagination loop
    for page in range(1, MAX_PAGES_PER_SYNC + 1):
        if len(all_normalized) >= max_repos:
            break

        # Fetch page of repositories
        raw_items = await client.list_user_repositories(
            access_token=access_token,
            page=page,
            per_page=min(page_size, max_repos - len(all_normalized)),
        )

        if not raw_items:
            break

        for item in raw_items:
            normalized = normalize_github_repository(item)
            if normalized and normalized.github_repository_id not in seen_ids:
                seen_ids.add(normalized.github_repository_id)
                all_normalized.append(normalized)
                if len(all_normalized) >= max_repos:
                    break

        # Stop when returned items are fewer than requested page size
        if len(raw_items) < page_size:
            break

    # 3. Upsert normalized records idempotently
    synced_count = await upsert_repositories(db, connection.id, all_normalized)

    # 4. Count total repositories in DB for this connection
    count_stmt = select(func.count(GitHubRepository.id)).where(
        GitHubRepository.connection_id == connection.id
    )
    total_in_db = (await db.execute(count_stmt)).scalar() or 0

    return {
        "status": "completed",
        "synced_count": synced_count,
        "total": total_in_db,
    }


async def list_connection_repositories(
    db: AsyncSession,
    connection_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
) -> tuple[list[GitHubRepository], int]:
    """Retrieve paginated repository records belonging to a GitHub connection."""
    safe_limit = min(max(1, limit), 100)
    safe_offset = max(0, offset)

    base_query = select(GitHubRepository).where(
        GitHubRepository.connection_id == connection_id
    )

    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        base_query = base_query.where(
            GitHubRepository.full_name.ilike(search_pattern)
            | GitHubRepository.name.ilike(search_pattern)
        )

    # Total count matching filters
    count_query = select(func.count(GitHubRepository.id)).where(
        GitHubRepository.connection_id == connection_id
    )
    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        count_query = count_query.where(
            GitHubRepository.full_name.ilike(search_pattern)
            | GitHubRepository.name.ilike(search_pattern)
        )

    total = (await db.execute(count_query)).scalar() or 0

    # Ordered deterministically: selected first, then recent push, then name
    ordered_query = (
        base_query.order_by(
            GitHubRepository.is_selected.desc(),
            GitHubRepository.github_pushed_at.desc().nullslast(),
            GitHubRepository.name.asc(),
        )
        .limit(safe_limit)
        .offset(safe_offset)
    )

    result = await db.execute(ordered_query)
    items = list(result.scalars().all())
    return items, total


async def update_repository_selection(
    db: AsyncSession,
    connection_id: uuid.UUID,
    repository_id: uuid.UUID,
    is_selected: bool,
) -> Optional[GitHubRepository]:
    """Update UI repository selection preference for future stage synchronization.

    Verifies connection ownership.
    """
    stmt = select(GitHubRepository).where(
        GitHubRepository.id == repository_id,
        GitHubRepository.connection_id == connection_id,
    )
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        return None

    repo.is_selected = is_selected
    repo.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(repo)
    return repo


