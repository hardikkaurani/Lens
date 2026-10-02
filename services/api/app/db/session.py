import logging
from collections.abc import AsyncGenerator
from typing import Optional

from redis.asyncio import Redis, from_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Asynchronous SQLAlchemy Engine with connection pooling
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Shared async Redis client instance
_redis_client: Optional[Redis] = None


def get_redis_client() -> Redis:
    """Return an async Redis client instance using the configured URL."""
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _redis_client


async def close_connections() -> None:
    """Gracefully close database engine and Redis connection pool."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception as e:
            logger.warning("Error closing Redis client: %s", e)
        finally:
            _redis_client = None

    try:
        await engine.dispose()
    except Exception as e:
        logger.warning("Error disposing database engine: %s", e)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding an isolated async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_database_health() -> bool:
    """Verify PostgreSQL connectivity by executing a lightweight SELECT 1 query."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        return False


async def check_redis_health() -> bool:
    """Verify Redis connectivity by sending a PING command."""
    try:
        client = get_redis_client()
        return await client.ping() is True
    except Exception as e:
        logger.warning("Redis health check failed: %s", e)
        return False
