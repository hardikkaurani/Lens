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

# Redis key prefix for OAuth states
OAUTH_STATE_KEY_PREFIX = "lens:oauth:github:state:"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes

# In-memory fallback cache for OAuth states when Redis is unavailable (e.g., isolated test environments)
_memory_state_cache: dict[str, tuple[str, float]] = {}


def generate_oauth_state() -> str:
    """Generate a high-entropy, cryptographically secure OAuth state string."""
    return secrets.token_urlsafe(32)


async def store_oauth_state(state: str, metadata: Optional[dict[str, Any]] = None) -> None:
    """Store OAuth state with a 10-minute expiration to prevent CSRF and replay attacks."""
    payload_str = json.dumps(metadata or {"created_at": time.time()})
    key = f"{OAUTH_STATE_KEY_PREFIX}{state}"

    # Try storing in Redis
    try:
        redis = get_redis_client()
        await redis.set(key, payload_str, ex=OAUTH_STATE_TTL_SECONDS)
        return
    except Exception as exc:
        logger.warning("Redis unavailable for OAuth state storage; falling back to memory store: %s", exc)

    # Fallback to local memory store
    expires_at = time.time() + OAUTH_STATE_TTL_SECONDS
    _memory_state_cache[state] = (payload_str, expires_at)


async def validate_and_consume_oauth_state(state: str) -> Optional[dict[str, Any]]:
    """Validate and atomically consume (delete) an OAuth state.

    Returns the stored metadata if valid, or None if expired, missing, or already consumed.
    """
    if not state or not state.strip():
        return None

    key = f"{OAUTH_STATE_KEY_PREFIX}{state}"

    # 1. Try Redis first with atomic delete
    try:
        redis = get_redis_client()
        # getdel returns value and deletes in one atomic step (supported in Redis >= 6.2)
        val = await redis.getdel(key)
        if val:
            try:
                data = json.loads(val)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    except Exception as exc:
        logger.warning("Redis getdel failed for OAuth state; checking memory fallback: %s", exc)

    # 2. Check in-memory fallback
    now = time.time()
    # Clean up expired items
    expired_keys = [k for k, (_, exp) in _memory_state_cache.items() if exp < now]
    for k in expired_keys:
        _memory_state_cache.pop(k, None)

    if state in _memory_state_cache:
        payload_str, expires_at = _memory_state_cache.pop(state)
        if expires_at >= now:
            try:
                data = json.loads(payload_str)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    return None


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

