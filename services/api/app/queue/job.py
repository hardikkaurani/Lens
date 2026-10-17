import json
import logging
import uuid
from typing import Any, Awaitable, Optional, cast

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.db.session import get_redis_client

logger = logging.getLogger(__name__)

# Queue naming constants
URL_INGEST_QUEUE = "lens:jobs:url_ingest"
URL_INGEST_PROCESSING_QUEUE = "lens:jobs:url_ingest:processing"
FILE_INGEST_QUEUE = "lens:jobs:file_ingest"
FILE_INGEST_PROCESSING_QUEUE = "lens:jobs:file_ingest:processing"
GITHUB_REPO_SYNC_QUEUE = "lens:jobs:github_repo_sync"
GITHUB_REPO_SYNC_PROCESSING_QUEUE = "lens:jobs:github_repo_sync:processing"


class URLIngestJob(BaseModel):
    """Explicit job contract for URL capture ingestion."""

    type: str = Field(default="capture.url_ingest", description="Job type identifier.")
    version: int = Field(default=1, description="Schema contract version.")
    capture_id: uuid.UUID = Field(..., description="Target Capture UUID to ingest.")


class FileIngestJob(BaseModel):
    """Explicit job contract for binary file / PDF capture ingestion."""

    type: str = Field(default="capture.file_ingest", description="Job type identifier.")
    version: int = Field(default=1, description="Schema contract version.")
    capture_id: uuid.UUID = Field(..., description="Target Capture UUID to process.")


class GitHubRepoSyncJob(BaseModel):
    """Explicit job contract for GitHub repository discovery and synchronization."""

    type: str = Field(default="github.repositories_sync", description="Job type identifier.")
    version: int = Field(default=1, description="Schema contract version.")
    connection_id: uuid.UUID = Field(..., description="Target GitHubConnection UUID.")
    retry_count: int = Field(default=0, description="Current retry attempt.")
    max_retries: int = Field(default=3, description="Maximum allowed retry attempts.")



async def enqueue_url_ingest_job(
    capture_id: uuid.UUID,
    client: Optional[Redis] = None,
) -> bool:
    """Enqueue a new URL ingestion job into Redis.

    Returns True if successfully pushed to the Redis list.
    Raises Exception if Redis communication fails.
    """
    if client is None:
        client = get_redis_client()

    job = URLIngestJob(capture_id=capture_id)
    payload = job.model_dump_json()

    # Push to head of Redis list
    await cast(Awaitable[int], client.lpush(URL_INGEST_QUEUE, payload))
    logger.info("Enqueued URL ingest job for capture %s", capture_id)
    return True


async def dequeue_url_ingest_job(
    timeout: int = 2,
    client: Optional[Redis] = None,
) -> tuple[Optional[URLIngestJob], Optional[str]]:
    """Reliably dequeue a URL ingest job from Redis using BLMOVE.

    Atomically moves the oldest job from URL_INGEST_QUEUE (RIGHT)
    into URL_INGEST_PROCESSING_QUEUE (LEFT).

    Returns a tuple of (URLIngestJob, raw_payload), or (None, None) if timed out.
    """
    if client is None:
        client = get_redis_client()

    if timeout <= 0:
        raw = await client.lmove(
            URL_INGEST_QUEUE,
            URL_INGEST_PROCESSING_QUEUE,
            src="RIGHT",
            dest="LEFT",
        )
    else:
        raw = await client.blmove(
            URL_INGEST_QUEUE,
            URL_INGEST_PROCESSING_QUEUE,
            timeout,
            src="RIGHT",
            dest="LEFT",
        )
    if raw is None:
        return None, None

    try:
        job = URLIngestJob.model_validate_json(raw)
        return job, raw
    except Exception as e:
        logger.error("Failed to parse job payload from queue: %s (payload=%r)", e, raw)
        # Remove corrupted job from processing queue to avoid poisoning
        await cast(Awaitable[int], client.lrem(URL_INGEST_PROCESSING_QUEUE, 1, raw))
        return None, None


async def ack_url_ingest_job(
    raw: str,
    client: Optional[Redis] = None,
) -> None:
    """Acknowledge completion of a job by removing it from the processing queue."""
    if client is None:
        client = get_redis_client()

    await cast(Awaitable[int], client.lrem(URL_INGEST_PROCESSING_QUEUE, 1, raw))


async def enqueue_file_ingest_job(
    capture_id: uuid.UUID,
    client: Optional[Redis] = None,
) -> bool:
    """Enqueue a new binary file / PDF ingestion job into Redis.

    Returns True if successfully pushed to the Redis list.
    Raises Exception if Redis communication fails.
    """
    if client is None:
        client = get_redis_client()

    job = FileIngestJob(capture_id=capture_id)
    payload = job.model_dump_json()

    # Push to head of Redis list
    await cast(Awaitable[int], client.lpush(FILE_INGEST_QUEUE, payload))
    logger.info("Enqueued file ingest job for capture %s", capture_id)
    return True


async def dequeue_file_ingest_job(
    timeout: int = 2,
    client: Optional[Redis] = None,
) -> tuple[Optional[FileIngestJob], Optional[str]]:
    """Reliably dequeue a file ingest job from Redis using BLMOVE or LMOVE.

    Atomically moves the oldest job from FILE_INGEST_QUEUE (RIGHT)
    into FILE_INGEST_PROCESSING_QUEUE (LEFT).

    Returns a tuple of (FileIngestJob, raw_payload), or (None, None) if timed out.
    """
    if client is None:
        client = get_redis_client()

    if timeout <= 0:
        raw = await client.lmove(
            FILE_INGEST_QUEUE,
            FILE_INGEST_PROCESSING_QUEUE,
            src="RIGHT",
            dest="LEFT",
        )
    else:
        raw = await client.blmove(
            FILE_INGEST_QUEUE,
            FILE_INGEST_PROCESSING_QUEUE,
            timeout,
            src="RIGHT",
            dest="LEFT",
        )
    if raw is None:
        return None, None


    try:
        job = FileIngestJob.model_validate_json(raw)
        return job, raw
    except Exception as e:
        logger.error("Failed to parse file job payload from queue: %s (payload=%r)", e, raw)
        # Remove corrupted job from processing queue to avoid poisoning
        await cast(Awaitable[int], client.lrem(FILE_INGEST_PROCESSING_QUEUE, 1, raw))
        return None, None


async def ack_file_ingest_job(
    raw: str,
    client: Optional[Redis] = None,
) -> None:
    """Acknowledge completion of a file ingest job by removing it from the processing queue."""
    if client is None:
        client = get_redis_client()

    await cast(Awaitable[int], client.lrem(FILE_INGEST_PROCESSING_QUEUE, 1, raw))


async def enqueue_github_repo_sync_job(
    connection_id: uuid.UUID,
    client: Optional[Redis] = None,
) -> bool:
    """Enqueue a new GitHub repository synchronization job into Redis."""
    if client is None:
        client = get_redis_client()

    job = GitHubRepoSyncJob(connection_id=connection_id)
    payload = job.model_dump_json()

    await cast(Awaitable[int], client.lpush(GITHUB_REPO_SYNC_QUEUE, payload))
    logger.info("Enqueued GitHub repo sync job for connection %s", connection_id)
    return True


async def dequeue_github_repo_sync_job(
    timeout: int = 2,
    client: Optional[Redis] = None,
) -> tuple[Optional[GitHubRepoSyncJob], Optional[str]]:
    """Reliably dequeue a GitHub repo sync job from Redis using BLMOVE or LMOVE.

    Atomically moves the oldest job from GITHUB_REPO_SYNC_QUEUE (RIGHT)
    into GITHUB_REPO_SYNC_PROCESSING_QUEUE (LEFT).
    """
    if client is None:
        client = get_redis_client()

    if timeout <= 0:
        raw = await client.lmove(
            GITHUB_REPO_SYNC_QUEUE,
            GITHUB_REPO_SYNC_PROCESSING_QUEUE,
            src="RIGHT",
            dest="LEFT",
        )
    else:
        raw = await client.blmove(
            GITHUB_REPO_SYNC_QUEUE,
            GITHUB_REPO_SYNC_PROCESSING_QUEUE,
            timeout,
            src="RIGHT",
            dest="LEFT",
        )
    if raw is None:
        return None, None

    try:
        job = GitHubRepoSyncJob.model_validate_json(raw)
        return job, raw
    except Exception as e:
        logger.error("Failed to parse GitHub repo sync job payload from queue: %s (payload=%r)", e, raw)
        await cast(Awaitable[int], client.lrem(GITHUB_REPO_SYNC_PROCESSING_QUEUE, 1, raw))
        return None, None


async def ack_github_repo_sync_job(
    raw: str,
    client: Optional[Redis] = None,
) -> None:
    """Acknowledge completion of a GitHub repo sync job by removing it from the processing queue."""
    if client is None:
        client = get_redis_client()

    await cast(Awaitable[int], client.lrem(GITHUB_REPO_SYNC_PROCESSING_QUEUE, 1, raw))


async def recover_stranded_github_repo_sync_jobs(
    client: Optional[Redis] = None,
    max_retries: int = 3,
) -> int:
    """Recover jobs stranded in GITHUB_REPO_SYNC_PROCESSING_QUEUE after worker crashes.

    Atomically inspects items in the processing queue.
    If retry_count < max_retries, moves the job back to GITHUB_REPO_SYNC_QUEUE with incremented retry count.
    If retry_count >= max_retries, drops the dead job and logs an error to prevent poison pill loops.

    Returns the number of jobs recovered.
    """
    if client is None:
        client = get_redis_client()

    recovered_count = 0
    try:
        items = await cast(Awaitable[list[Any]], client.lrange(GITHUB_REPO_SYNC_PROCESSING_QUEUE, 0, -1))
        if not items:
            return 0

        for raw_item in items:
            raw_str = raw_item if isinstance(raw_item, str) else raw_item.decode("utf-8")
            try:
                job_data = json.loads(raw_str)
                retry_count = int(job_data.get("retry_count", 0)) + 1
                job_data["retry_count"] = retry_count

                await cast(Awaitable[int], client.lrem(GITHUB_REPO_SYNC_PROCESSING_QUEUE, 1, raw_str))

                if retry_count <= max_retries:
                    updated_payload = json.dumps(job_data)
                    await cast(Awaitable[int], client.lpush(GITHUB_REPO_SYNC_QUEUE, updated_payload))
                    logger.warning(
                        "Recovered stranded GitHub repo sync job for connection %s (retry %d/%d)",
                        job_data.get("connection_id"),
                        retry_count,
                        max_retries,
                    )
                    recovered_count += 1
                else:
                    logger.error(
                        "Discarded unrecoverable GitHub repo sync job for connection %s after %d failed attempts",
                        job_data.get("connection_id"),
                        max_retries,
                    )
            except Exception as item_err:
                logger.error("Failed to recover processing item %r: %s", raw_str, item_err)
                await cast(Awaitable[int], client.lrem(GITHUB_REPO_SYNC_PROCESSING_QUEUE, 1, raw_str))
    except Exception as exc:
        logger.error("Failed to inspect stranded GitHub repo sync jobs: %s", exc)

    return recovered_count



