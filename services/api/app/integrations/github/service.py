from datetime import datetime, timedelta, timezone
import json
import logging
import secrets
import time
from typing import Any, Awaitable, Optional, cast
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.encryption import EncryptionError, decrypt_secret, encrypt_secret
from app.db.models import (
    GitHubActivity,
    GitHubActivityType,
    GitHubConnection,
    GitHubRepository,
    RepositorySyncStatus,
)
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
    NormalizedGitHubActivity,
    NormalizedGitHubRepository,
    check_sufficient_repo_scope,
    normalize_github_commit,
    normalize_github_issue,
    normalize_github_pull_request,
    normalize_github_repository,
    normalize_github_review,
    parse_iso_datetime,
)

logger = logging.getLogger(__name__)

# Cookie name for browser session binding
OAUTH_COOKIE_NAME = "lens_oauth_session"

# Redis key prefix for OAuth states
OAUTH_STATE_KEY_PREFIX = "lens:oauth:github:state:"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes

# Repository discovery & sync constants
DEFAULT_REPO_PAGE_SIZE = 100
MAX_REPOSITORIES_PER_SYNC = 1000
MAX_PAGES_PER_SYNC = 10
SYNC_LOCK_TTL_SECONDS = 300  # 5 minutes bounded operation deadline
SYNC_LOCK_KEY_PREFIX = "lens:lock:github_sync:"
ENQUEUE_LOCK_TTL_SECONDS = 10  # Brief lock to guard async sync enqueue
ENQUEUE_LOCK_KEY_PREFIX = "lens:lock:github_enqueue:"
GENERIC_SYNC_ERROR_MESSAGE = "An unexpected error occurred during repository synchronization."

# Activity ingestion constants
ACTIVITY_SYNC_LOCK_TTL_SECONDS = 600  # 10 minutes bounded operation deadline
ACTIVITY_SYNC_LOCK_KEY_PREFIX = "lens:lock:github_activity_sync:"
ACTIVITY_ENQUEUE_LOCK_TTL_SECONDS = 10
ACTIVITY_ENQUEUE_LOCK_KEY_PREFIX = "lens:lock:github_activity_enqueue:"
ACTIVITY_OVERLAP_WINDOW_MINUTES = 5
GENERIC_ACTIVITY_SYNC_ERROR_MESSAGE = "An unexpected error occurred during activity synchronization."


# In-memory fallback caches when Redis is unavailable (strictly for dev/test environments)
_memory_state_cache: dict[str, tuple[str, float]] = {}
_memory_lock_cache: dict[str, tuple[str, float]] = {}

# Atomic lock release via Lua script (ensures lock is only deleted if token matches ownership)
RELEASE_LOCK_LUA_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class OAuthStorageError(Exception):
    """Raised when OAuth state storage is unavailable or fails."""
    pass


class LockStorageError(Exception):
    """Raised when distributed lock storage is unavailable in production."""
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


async def acquire_sync_lock(connection_id: uuid.UUID) -> Optional[str]:
    """Acquire a temporary distributed lock for repository sync to prevent concurrent runs.

    Returns a unique lock ownership token (str) if successfully acquired,
    or None if the lock is already held.
    In production mode (APP_ENV == 'production'), Redis is mandatory; if Redis fails,
    raises LockStorageError to fail closed and prevent split-brain race conditions.
    """
    from app.core.config import get_settings

    settings = get_settings()
    is_production = settings.APP_ENV == "production"

    token = secrets.token_hex(16)
    key = f"{SYNC_LOCK_KEY_PREFIX}{connection_id}"
    now = time.time()
    try:
        redis = get_redis_client()
        res = await redis.set(key, token, ex=SYNC_LOCK_TTL_SECONDS, nx=True)
        return token if res else None
    except Exception as exc:
        if is_production:
            logger.error("Redis unavailable for sync lock in production: %s", exc)
            raise LockStorageError("Distributed sync lock service unavailable.") from exc
        logger.warning("Redis unavailable for sync lock; checking local memory cache: %s", exc)

    # In-memory fallback (strictly for development/testing)
    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        expires_at = val[1] if isinstance(val, tuple) else float(val)
        if expires_at > now:
            return None
    _memory_lock_cache[key] = (token, now + SYNC_LOCK_TTL_SECONDS)
    return token


async def release_sync_lock(connection_id: uuid.UUID, token: Optional[str] = None) -> bool:
    """Release distributed lock for repository sync using ownership-checked atomic release.

    Verifies that the lock still belongs to the calling process via `token`.
    Returns True if successfully deleted, False if lock was missing or owned by another process.
    """
    key = f"{SYNC_LOCK_KEY_PREFIX}{connection_id}"
    released = False

    try:
        redis = get_redis_client()
        if token:
            res = await cast(Awaitable[Any], redis.eval(RELEASE_LOCK_LUA_SCRIPT, 1, key, token))
            released = bool(res)
        else:
            # Fallback unconditional delete only if no token provided (legacy compat)
            await redis.delete(key)
            released = True
    except Exception as exc:
        logger.warning("Redis lock release failed: %s", exc)

    # Clean up memory fallback
    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        stored_token = val[0] if isinstance(val, tuple) else None
        if token is None or stored_token == token:
            _memory_lock_cache.pop(key, None)
            released = True

    return released


async def is_sync_locked(connection_id: uuid.UUID) -> bool:
    """Check if repository sync distributed lock is currently held."""
    key = f"{SYNC_LOCK_KEY_PREFIX}{connection_id}"
    try:
        redis = get_redis_client()
        val = await redis.get(key)
        if val is not None:
            return True
    except Exception as exc:
        logger.warning("Redis unavailable for is_sync_locked check: %s", exc)

    # Check memory fallback
    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        expires_at = val[1] if isinstance(val, tuple) else float(val)
        if expires_at > time.time():
            return True
        else:
            _memory_lock_cache.pop(key, None)
    return False


def is_sync_metadata_active(
    sync_info: Optional[dict[str, Any]],
    max_age_seconds: int = SYNC_LOCK_TTL_SECONDS,
) -> bool:
    """Check if the persisted sync metadata indicates an active in-progress sync.

    Treats 'syncing' status as active only while its timestamp is valid and fresh
    within max_age_seconds. Permits recovery from stale or invalid timestamps.
    """
    if not sync_info or not isinstance(sync_info, dict):
        return False
    if sync_info.get("status") != "syncing":
        return False
    started_at_str = sync_info.get("started_at")
    if not started_at_str or not isinstance(started_at_str, str):
        # Missing or non-string timestamp -> stale/invalid, allow recovery
        return False
    try:
        clean = started_at_str.strip().replace("Z", "+00:00")
        started_dt = datetime.fromisoformat(clean)
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - started_dt).total_seconds()
        # Fresh within max_age_seconds (and tolerate clock skew up to max_age_seconds)
        return 0 <= age <= max_age_seconds
    except Exception:
        # Malformed timestamp -> allow recovery
        return False


async def acquire_enqueue_lock(connection_id: uuid.UUID) -> Optional[str]:
    """Acquire a brief distributed lock to serialize async enqueue requests."""
    from app.core.config import get_settings

    settings = get_settings()
    is_production = settings.APP_ENV == "production"

    token = secrets.token_hex(16)
    key = f"{ENQUEUE_LOCK_KEY_PREFIX}{connection_id}"
    now = time.time()
    try:
        redis = get_redis_client()
        res = await redis.set(key, token, ex=ENQUEUE_LOCK_TTL_SECONDS, nx=True)
        return token if res else None
    except Exception as exc:
        if is_production:
            logger.error("Redis unavailable for enqueue lock in production: %s", exc)
            raise LockStorageError("Distributed enqueue lock service unavailable.") from exc
        logger.warning("Redis unavailable for enqueue lock; falling back to memory: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        expires_at = val[1] if isinstance(val, tuple) else float(val)
        if expires_at > now:
            return None
    _memory_lock_cache[key] = (token, now + ENQUEUE_LOCK_TTL_SECONDS)
    return token


async def release_enqueue_lock(connection_id: uuid.UUID, token: Optional[str] = None) -> bool:
    """Release distributed lock for async enqueue."""
    key = f"{ENQUEUE_LOCK_KEY_PREFIX}{connection_id}"
    released = False

    try:
        redis = get_redis_client()
        if token:
            res = await cast(Awaitable[Any], redis.eval(RELEASE_LOCK_LUA_SCRIPT, 1, key, token))
            released = bool(res)
        else:
            await redis.delete(key)
            released = True
    except Exception as exc:
        logger.warning("Redis enqueue lock release failed: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        stored_token = val[0] if isinstance(val, tuple) else None
        if token is None or stored_token == token:
            _memory_lock_cache.pop(key, None)
            released = True

    return released


async def acquire_activity_sync_lock(connection_id: uuid.UUID) -> Optional[str]:
    """Acquire a temporary distributed lock for GitHub activity sync.

    Returns a unique lock ownership token (str) if successfully acquired,
    or None if the lock is already held.
    Fails closed in production if Redis is unavailable.
    """
    from app.core.config import get_settings

    settings = get_settings()
    is_production = settings.APP_ENV == "production"

    token = secrets.token_hex(16)
    key = f"{ACTIVITY_SYNC_LOCK_KEY_PREFIX}{connection_id}"
    now = time.time()
    try:
        redis = get_redis_client()
        res = await redis.set(key, token, ex=ACTIVITY_SYNC_LOCK_TTL_SECONDS, nx=True)
        return token if res else None
    except Exception as exc:
        if is_production:
            logger.error("Redis unavailable for activity sync lock in production: %s", exc)
            raise LockStorageError("Distributed activity sync lock service unavailable.") from exc
        logger.warning("Redis unavailable for activity sync lock; checking local memory cache: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        expires_at = val[1] if isinstance(val, tuple) else float(val)
        if expires_at > now:
            return None
    _memory_lock_cache[key] = (token, now + ACTIVITY_SYNC_LOCK_TTL_SECONDS)
    return token


async def release_activity_sync_lock(connection_id: uuid.UUID, token: Optional[str] = None) -> bool:
    """Release distributed lock for activity sync using atomic ownership check."""
    key = f"{ACTIVITY_SYNC_LOCK_KEY_PREFIX}{connection_id}"
    released = False

    try:
        redis = get_redis_client()
        if token:
            res = await cast(Awaitable[Any], redis.eval(RELEASE_LOCK_LUA_SCRIPT, 1, key, token))
            released = bool(res)
        else:
            await redis.delete(key)
            released = True
    except Exception as exc:
        logger.warning("Redis activity sync lock release failed: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        stored_token = val[0] if isinstance(val, tuple) else None
        if token is None or stored_token == token:
            _memory_lock_cache.pop(key, None)
            released = True

    return released


async def is_activity_sync_locked(connection_id: uuid.UUID) -> bool:
    """Check if activity sync distributed lock is currently held."""
    key = f"{ACTIVITY_SYNC_LOCK_KEY_PREFIX}{connection_id}"
    try:
        redis = get_redis_client()
        val = await redis.get(key)
        if val is not None:
            return True
    except Exception as exc:
        logger.warning("Redis unavailable for is_activity_sync_locked check: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        expires_at = val[1] if isinstance(val, tuple) else float(val)
        if expires_at > time.time():
            return True
        else:
            _memory_lock_cache.pop(key, None)
    return False


async def acquire_activity_enqueue_lock(connection_id: uuid.UUID) -> Optional[str]:
    """Acquire a brief distributed lock to serialize async activity enqueue requests."""
    from app.core.config import get_settings

    settings = get_settings()
    is_production = settings.APP_ENV == "production"

    token = secrets.token_hex(16)
    key = f"{ACTIVITY_ENQUEUE_LOCK_KEY_PREFIX}{connection_id}"
    now = time.time()
    try:
        redis = get_redis_client()
        res = await redis.set(key, token, ex=ACTIVITY_ENQUEUE_LOCK_TTL_SECONDS, nx=True)
        return token if res else None
    except Exception as exc:
        if is_production:
            logger.error("Redis unavailable for activity enqueue lock in production: %s", exc)
            raise LockStorageError("Distributed activity enqueue lock service unavailable.") from exc
        logger.warning("Redis unavailable for activity enqueue lock; falling back to memory: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        expires_at = val[1] if isinstance(val, tuple) else float(val)
        if expires_at > now:
            return None
    _memory_lock_cache[key] = (token, now + ACTIVITY_ENQUEUE_LOCK_TTL_SECONDS)
    return token


async def release_activity_enqueue_lock(connection_id: uuid.UUID, token: Optional[str] = None) -> bool:
    """Release distributed lock for async activity enqueue."""
    key = f"{ACTIVITY_ENQUEUE_LOCK_KEY_PREFIX}{connection_id}"
    released = False

    try:
        redis = get_redis_client()
        if token:
            res = await cast(Awaitable[Any], redis.eval(RELEASE_LOCK_LUA_SCRIPT, 1, key, token))
            released = bool(res)
        else:
            await redis.delete(key)
            released = True
    except Exception as exc:
        logger.warning("Redis activity enqueue lock release failed: %s", exc)

    if key in _memory_lock_cache:
        val = _memory_lock_cache[key]
        stored_token = val[0] if isinstance(val, tuple) else None
        if token is None or stored_token == token:
            _memory_lock_cache.pop(key, None)
            released = True

    return released


def is_activity_sync_metadata_active(
    sync_info: Optional[dict[str, Any]],
    max_age_seconds: int = ACTIVITY_SYNC_LOCK_TTL_SECONDS,
) -> bool:
    """Check if the persisted activity sync metadata indicates an active in-progress sync."""
    if not sync_info or not isinstance(sync_info, dict):
        return False
    if sync_info.get("status") != "syncing":
        return False
    started_at_str = sync_info.get("started_at")
    if not started_at_str or not isinstance(started_at_str, str):
        return False
    try:
        clean = started_at_str.strip().replace("Z", "+00:00")
        started_dt = datetime.fromisoformat(clean)
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - started_dt).total_seconds()
        return 0 <= age <= max_age_seconds
    except Exception:
        return False


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

    # Record sync starting state on connection
    now = datetime.now(timezone.utc)
    token_meta = dict(connection.token_metadata or {})
    token_meta["sync"] = {
        "status": "syncing",
        "started_at": now.isoformat(),
        "error": None,
    }
    connection.token_metadata = token_meta
    flag_modified(connection, "token_metadata")
    await db.commit()

    all_normalized: list[NormalizedGitHubRepository] = []
    seen_ids: set[str] = set()

    try:
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

        # Record successful completion state on connection
        finish_time = datetime.now(timezone.utc)
        token_meta = dict(connection.token_metadata or {})
        token_meta["sync"] = {
            "status": "synced",
            "last_synced_at": finish_time.isoformat(),
            "synced_count": synced_count,
            "total": total_in_db,
            "error": None,
        }
        connection.token_metadata = token_meta
        flag_modified(connection, "token_metadata")
        await db.commit()

        return {
            "status": "completed",
            "synced_count": synced_count,
            "total": total_in_db,
        }
    except Exception as exc:
        err_time = datetime.now(timezone.utc)
        if isinstance(exc, (GitHubClientError, EncryptionError)):
            safe_msg = str(exc)
        else:
            logger.exception(
                "Unexpected failure during repository sync for connection %s: %s",
                connection.id,
                type(exc).__name__,
            )
            safe_msg = GENERIC_SYNC_ERROR_MESSAGE

        token_meta = dict(connection.token_metadata or {})
        token_meta["sync"] = {
            "status": "failed",
            "failed_at": err_time.isoformat(),
            "error": safe_msg,
        }
        connection.token_metadata = token_meta
        flag_modified(connection, "token_metadata")
        try:
            await db.commit()
        except Exception as db_exc:
            logger.error("Failed to persist sync error state to database: %s", db_exc)
            await db.rollback()
        raise


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


async def upsert_activities(
    db: AsyncSession,
    repository_id: uuid.UUID,
    activities: list[NormalizedGitHubActivity],
) -> int:
    """Idempotently persist or update GitHub activities for a repository.

    Prevents duplicates using (repository_id, activity_type, external_id).
    Updates mutable fields while preserving internal UUID PK.
    """
    if not activities:
        return 0

    stmt = select(GitHubActivity).where(GitHubActivity.repository_id == repository_id)
    res = await db.execute(stmt)
    existing_all = res.scalars().all()
    existing_map: dict[tuple[str, str], GitHubActivity] = {
        (act.activity_type.value, act.external_id): act for act in existing_all
    }

    now = datetime.now(timezone.utc)
    count = 0
    seen_in_batch: set[tuple[str, str]] = set()

    for item in activities:
        key = (item.activity_type, item.external_id)
        if key in seen_in_batch:
            continue
        seen_in_batch.add(key)

        existing = existing_map.get(key)
        if existing:
            existing.title = item.title
            existing.body = item.body
            existing.html_url = item.html_url
            existing.author_login = item.author_login
            existing.state = item.state
            existing.source_updated_at = item.source_updated_at
            existing.payload = item.payload
            existing.ingested_at = now
        else:
            new_act = GitHubActivity(
                repository_id=repository_id,
                activity_type=GitHubActivityType(item.activity_type),
                external_id=item.external_id,
                title=item.title,
                body=item.body,
                html_url=item.html_url,
                author_login=item.author_login,
                state=item.state,
                source_created_at=item.source_created_at,
                source_updated_at=item.source_updated_at,
                ingested_at=now,
                payload=item.payload,
            )
            db.add(new_act)
            existing_map[key] = new_act
        count += 1

    await db.commit()
    return count


async def sync_repository_activities(
    db: AsyncSession,
    connection: GitHubConnection,
    repository: GitHubRepository,
    access_token: str,
    github_client: Optional[GitHubClient] = None,
) -> dict[str, Any]:
    """Synchronize pull requests, issues, commits, and reviews for a selected repository."""
    from app.core.config import get_settings

    settings = get_settings()
    client = github_client or get_github_client()

    owner = repository.owner_login
    repo_name = repository.name
    now = datetime.now(timezone.utc)

    # Initialize sync metadata
    meta = dict(repository.activity_sync_metadata or {})
    checkpoints = dict(meta.get("checkpoints", {}))
    categories_status: dict[str, Any] = dict(meta.get("categories", {}))

    max_pages = settings.GITHUB_ACTIVITY_MAX_PAGES_PER_RUN
    page_size = settings.GITHUB_ACTIVITY_PAGE_SIZE
    budget = settings.GITHUB_ACTIVITY_REQUEST_BUDGET
    overlap_delta = timedelta(minutes=ACTIVITY_OVERLAP_WINDOW_MINUTES)

    processed_pr_numbers: list[int] = []
    total_persisted_for_repo = 0
    category_failures: dict[str, str] = {}

    # Helper to format ISO datetime for GitHub API since parameter
    def _format_since(cp_val: Optional[str]) -> Optional[str]:
        if not cp_val:
            return None
        dt = parse_iso_datetime(cp_val)
        if not dt:
            return None
        since_dt = dt - overlap_delta
        return since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. PULL REQUESTS
    if budget > 0:
        pr_checkpoint_str = checkpoints.get("pull_requests")
        pr_cutoff = (parse_iso_datetime(pr_checkpoint_str) - overlap_delta) if pr_checkpoint_str else None
        pr_activities: list[NormalizedGitHubActivity] = []
        max_pr_updated: Optional[datetime] = None

        try:
            for page in range(1, max_pages + 1):
                if budget <= 0:
                    break
                budget -= 1

                raw_prs = await client.list_repository_pull_requests(
                    access_token=access_token,
                    owner=owner,
                    repo=repo_name,
                    page=page,
                    per_page=page_size,
                )
                if not raw_prs:
                    break

                stop_pr_pagination = False
                for item in raw_prs:
                    norm = normalize_github_pull_request(item)
                    if not norm:
                        continue
                    if norm.payload and norm.payload.get("number"):
                        processed_pr_numbers.append(int(norm.payload["number"]))

                    if norm.source_updated_at:
                        if max_pr_updated is None or norm.source_updated_at > max_pr_updated:
                            max_pr_updated = norm.source_updated_at
                        if pr_cutoff and norm.source_updated_at < pr_cutoff:
                            stop_pr_pagination = True

                    pr_activities.append(norm)

                if stop_pr_pagination or len(raw_prs) < page_size:
                    break

            # Persist and advance checkpoint only upon success
            synced_prs = await upsert_activities(db, repository.id, pr_activities)
            total_persisted_for_repo += synced_prs

            if max_pr_updated:
                checkpoints["pull_requests"] = max_pr_updated.isoformat()
            elif not pr_checkpoint_str:
                checkpoints["pull_requests"] = now.isoformat()

            categories_status["pull_requests"] = {
                "status": "synced",
                "count": synced_prs,
                "last_synced_at": now.isoformat(),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Failed to sync pull requests for repo %s: %s", repository.full_name, exc)
            category_failures["pull_requests"] = str(exc)
            categories_status["pull_requests"] = {
                "status": "failed",
                "error": str(exc),
                "failed_at": now.isoformat(),
            }

    # 2. ISSUES (Excludes PRs)
    if budget > 0:
        issue_since = _format_since(checkpoints.get("issues"))
        issue_activities: list[NormalizedGitHubActivity] = []
        max_issue_updated: Optional[datetime] = None

        try:
            for page in range(1, max_pages + 1):
                if budget <= 0:
                    break
                budget -= 1

                raw_issues = await client.list_repository_issues(
                    access_token=access_token,
                    owner=owner,
                    repo=repo_name,
                    since=issue_since,
                    page=page,
                    per_page=page_size,
                )
                if not raw_issues:
                    break

                for item in raw_issues:
                    norm = normalize_github_issue(item)
                    if not norm:
                        continue
                    if norm.source_updated_at:
                        if max_issue_updated is None or norm.source_updated_at > max_issue_updated:
                            max_issue_updated = norm.source_updated_at
                    issue_activities.append(norm)

                if len(raw_issues) < page_size:
                    break

            synced_issues = await upsert_activities(db, repository.id, issue_activities)
            total_persisted_for_repo += synced_issues

            if max_issue_updated:
                checkpoints["issues"] = max_issue_updated.isoformat()
            elif not checkpoints.get("issues"):
                checkpoints["issues"] = now.isoformat()

            categories_status["issues"] = {
                "status": "synced",
                "count": synced_issues,
                "last_synced_at": now.isoformat(),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Failed to sync issues for repo %s: %s", repository.full_name, exc)
            category_failures["issues"] = str(exc)
            categories_status["issues"] = {
                "status": "failed",
                "error": str(exc),
                "failed_at": now.isoformat(),
            }

    # 3. COMMITS
    if budget > 0:
        commit_since = _format_since(checkpoints.get("commits"))
        commit_activities: list[NormalizedGitHubActivity] = []
        max_commit_date: Optional[datetime] = None

        try:
            for page in range(1, max_pages + 1):
                if budget <= 0:
                    break
                budget -= 1

                raw_commits = await client.list_repository_commits(
                    access_token=access_token,
                    owner=owner,
                    repo=repo_name,
                    since=commit_since,
                    page=page,
                    per_page=page_size,
                )
                if not raw_commits:
                    break

                for item in raw_commits:
                    norm = normalize_github_commit(item)
                    if not norm:
                        continue
                    if norm.source_created_at:
                        if max_commit_date is None or norm.source_created_at > max_commit_date:
                            max_commit_date = norm.source_created_at
                    commit_activities.append(norm)

                if len(raw_commits) < page_size:
                    break

            synced_commits = await upsert_activities(db, repository.id, commit_activities)
            total_persisted_for_repo += synced_commits

            if max_commit_date:
                checkpoints["commits"] = max_commit_date.isoformat()
            elif not checkpoints.get("commits"):
                checkpoints["commits"] = now.isoformat()

            categories_status["commits"] = {
                "status": "synced",
                "count": synced_commits,
                "last_synced_at": now.isoformat(),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Failed to sync commits for repo %s: %s", repository.full_name, exc)
            category_failures["commits"] = str(exc)
            categories_status["commits"] = {
                "status": "failed",
                "error": str(exc),
                "failed_at": now.isoformat(),
            }

    # 4. REVIEWS (for PRs fetched in this batch)
    if budget > 0 and processed_pr_numbers:
        review_activities: list[NormalizedGitHubActivity] = []
        max_prs_to_review = settings.GITHUB_ACTIVITY_MAX_PRS_FOR_REVIEWS
        prs_to_inspect = processed_pr_numbers[:max_prs_to_review]

        try:
            for pr_num in prs_to_inspect:
                if budget <= 0:
                    break
                budget -= 1

                raw_reviews = await client.list_pull_request_reviews(
                    access_token=access_token,
                    owner=owner,
                    repo=repo_name,
                    pull_number=pr_num,
                    page=1,
                    per_page=settings.GITHUB_ACTIVITY_REVIEWS_PER_PR,
                )
                if not raw_reviews:
                    continue

                for item in raw_reviews:
                    norm = normalize_github_review(item, pull_number=pr_num)
                    if norm:
                        review_activities.append(norm)

            synced_reviews = await upsert_activities(db, repository.id, review_activities)
            total_persisted_for_repo += synced_reviews

            categories_status["reviews"] = {
                "status": "synced",
                "count": synced_reviews,
                "last_synced_at": now.isoformat(),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Failed to sync reviews for repo %s: %s", repository.full_name, exc)
            category_failures["reviews"] = str(exc)
            categories_status["reviews"] = {
                "status": "failed",
                "error": str(exc),
                "failed_at": now.isoformat(),
            }

    # Compute repository sync status
    total_cats = len(categories_status)
    failed_cats = len(category_failures)
    if failed_cats == 0:
        repo_status = "synced"
        err_msg = None
    elif failed_cats < total_cats:
        repo_status = "partial"
        err_msg = f"Partial failure in categories: {', '.join(category_failures.keys())}"
    else:
        repo_status = "failed"
        err_msg = f"Failed categories: {', '.join(category_failures.keys())}"

    # Update repository record
    repository.activity_sync_status = repo_status
    repository.activity_sync_error = err_msg
    repository.activity_last_synced_at = now
    meta["checkpoints"] = checkpoints
    meta["categories"] = categories_status
    repository.activity_sync_metadata = meta
    flag_modified(repository, "activity_sync_metadata")
    await db.commit()

    return {
        "repository_id": str(repository.id),
        "full_name": repository.full_name,
        "status": repo_status,
        "synced_activities": total_persisted_for_repo,
        "error": err_msg,
        "categories": categories_status,
    }


async def sync_selected_repositories_activities(
    db: AsyncSession,
    connection_id: uuid.UUID,
    repository_ids: Optional[list[uuid.UUID]] = None,
    github_client: Optional[GitHubClient] = None,
) -> dict[str, Any]:
    """Execute activity ingestion across selected repositories belonging to a connection."""
    # 1. Fetch and verify connection
    conn_stmt = select(GitHubConnection).where(GitHubConnection.id == connection_id)
    conn_res = await db.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if not connection:
        raise ValueError("GitHub connection not found.")

    if not check_sufficient_repo_scope(connection.scope):
        raise GitHubAuthError("Connection lacks sufficient repository OAuth scopes.")

    # 2. Fetch eligible selected repositories
    repo_stmt = select(GitHubRepository).where(
        GitHubRepository.connection_id == connection_id,
        GitHubRepository.is_selected.is_(True),
    )
    if repository_ids:
        repo_stmt = repo_stmt.where(GitHubRepository.id.in_(repository_ids))

    repo_res = await db.execute(repo_stmt)
    repositories = list(repo_res.scalars().all())

    if not repositories:
        return {
            "status": "completed",
            "synced_repositories": 0,
            "synced_activities": 0,
            "message": "No selected repositories found to synchronize.",
            "details": {},
        }

    # Decrypt token once for the connection run
    access_token = decrypt_secret(connection.encrypted_access_token)

    now = datetime.now(timezone.utc)
    token_meta = dict(connection.token_metadata or {})
    token_meta["activity_sync"] = {
        "status": "syncing",
        "started_at": now.isoformat(),
        "error": None,
    }
    connection.token_metadata = token_meta
    flag_modified(connection, "token_metadata")
    await db.commit()

    total_activities = 0
    synced_repos_count = 0
    results_breakdown: dict[str, Any] = {}
    has_failures = False
    has_successes = False

    for repo in repositories:
        try:
            repo.activity_sync_status = "syncing"
            await db.commit()

            repo_res = await sync_repository_activities(
                db=db,
                connection=connection,
                repository=repo,
                access_token=access_token,
                github_client=github_client,
            )
            results_breakdown[repo.full_name] = repo_res
            total_activities += repo_res.get("synced_activities", 0)

            if repo_res.get("status") in ("synced", "partial"):
                has_successes = True
                synced_repos_count += 1
            if repo_res.get("status") in ("failed", "partial"):
                has_failures = True
        except Exception as repo_exc:
            logger.exception("Unexpected error syncing activities for repo %s: %s", repo.full_name, repo_exc)
            has_failures = True
            repo.activity_sync_status = "failed"
            repo.activity_sync_error = str(repo_exc)
            await db.commit()
            results_breakdown[repo.full_name] = {
                "repository_id": str(repo.id),
                "full_name": repo.full_name,
                "status": "failed",
                "error": str(repo_exc),
            }

    finish_time = datetime.now(timezone.utc)
    if not has_failures:
        overall_status = "completed"
        overall_msg = f"Successfully synchronized activities for {synced_repos_count} repositories ({total_activities} activities)."
    elif has_successes:
        overall_status = "partial"
        overall_msg = f"Partially synchronized activities for {synced_repos_count}/{len(repositories)} repositories."
    else:
        overall_status = "failed"
        overall_msg = "Failed to synchronize activities for selected repositories."

    token_meta = dict(connection.token_metadata or {})
    token_meta["activity_sync"] = {
        "status": overall_status,
        "last_synced_at": finish_time.isoformat(),
        "synced_repositories": synced_repos_count,
        "synced_activities": total_activities,
        "error": None if overall_status == "completed" else overall_msg,
    }
    connection.token_metadata = token_meta
    flag_modified(connection, "token_metadata")
    await db.commit()

    return {
        "status": overall_status,
        "synced_repositories": synced_repos_count,
        "synced_activities": total_activities,
        "message": overall_msg,
        "details": results_breakdown,
    }


async def list_connection_activities(
    db: AsyncSession,
    connection_id: uuid.UUID,
    repository_id: Optional[uuid.UUID] = None,
    activity_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GitHubActivity], int]:
    """Retrieve paginated activity records belonging to selected repositories of a connection."""
    safe_limit = min(max(1, limit), 100)
    safe_offset = max(0, offset)

    base_query = (
        select(GitHubActivity)
        .join(GitHubRepository, GitHubActivity.repository_id == GitHubRepository.id)
        .where(GitHubRepository.connection_id == connection_id)
    )

    if repository_id is not None:
        base_query = base_query.where(GitHubActivity.repository_id == repository_id)

    if activity_type is not None:
        try:
            type_enum = GitHubActivityType(activity_type)
            base_query = base_query.where(GitHubActivity.activity_type == type_enum)
        except ValueError:
            return [], 0

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    ordered_query = (
        base_query
        .order_by(
            GitHubActivity.source_created_at.desc().nullslast(),
            GitHubActivity.ingested_at.desc(),
            GitHubActivity.id.desc(),
        )
        .limit(safe_limit)
        .offset(safe_offset)
    )

    result = await db.execute(ordered_query)
    items = list(result.scalars().all())
    return items, total



