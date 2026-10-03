from datetime import datetime, timezone
import json
import logging
import secrets
import time
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_secret
from app.db.models import GitHubConnection
from app.db.session import get_redis_client

logger = logging.getLogger(__name__)

# Cookie name for browser session binding
OAUTH_COOKIE_NAME = "lens_oauth_session"

# Redis key prefix for OAuth states
OAUTH_STATE_KEY_PREFIX = "lens:oauth:github:state:"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes

# In-memory fallback cache for OAuth states when Redis is unavailable (strictly for dev/test environments)
_memory_state_cache: dict[str, tuple[str, float]] = {}


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

