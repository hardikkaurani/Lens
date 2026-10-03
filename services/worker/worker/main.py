"""Worker main loop and execution entrypoint for LENS background processing."""

import argparse
import asyncio
import logging
import signal
import sys
from typing import Optional

# Setup sys.path via worker package init
import worker  # noqa: F401

from app.db.session import close_connections
from app.queue.job import (
    ack_file_ingest_job,
    ack_url_ingest_job,
    dequeue_file_ingest_job,
    dequeue_url_ingest_job,
)
from worker.processor import process_file_capture, process_url_capture

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lens.worker")


async def process_one_job(
    timeout: int = 1,
    allow_localhost: bool = False,
) -> bool:
    """Dequeue and process a single job from the Redis queue.

    Checks URL ingest queue and file ingest queue.
    Returns:
        True if a job was dequeued and processed; False if both queues were empty.
    """
    # 1. Non-blocking check on URL queue first
    url_job, url_raw = await dequeue_url_ingest_job(timeout=0)
    if url_job is not None and url_raw is not None:
        logger.info("Worker picked up job %s for capture %s", url_job.type, url_job.capture_id)
        try:
            await process_url_capture(url_job.capture_id, allow_localhost=allow_localhost)
        finally:
            await ack_url_ingest_job(url_raw)
            logger.debug("Acknowledged job for capture %s", url_job.capture_id)
        return True

    # 2. Non-blocking check on File queue
    file_job, file_raw = await dequeue_file_ingest_job(timeout=0)
    if file_job is not None and file_raw is not None:
        logger.info("Worker picked up job %s for capture %s", file_job.type, file_job.capture_id)
        try:
            await process_file_capture(file_job.capture_id)
        finally:
            await ack_file_ingest_job(file_raw)
            logger.debug("Acknowledged file job for capture %s", file_job.capture_id)
        return True

    # 3. If neither had an immediate job and timeout > 0, wait on URL queue
    if timeout > 0:
        url_job, url_raw = await dequeue_url_ingest_job(timeout=timeout)
        if url_job is not None and url_raw is not None:
            logger.info("Worker picked up job %s for capture %s", url_job.type, url_job.capture_id)
            try:
                await process_url_capture(url_job.capture_id, allow_localhost=allow_localhost)
            finally:
                await ack_url_ingest_job(url_raw)
                logger.debug("Acknowledged job for capture %s", url_job.capture_id)
            return True

        # Quick check on file queue in case one arrived during wait
        file_job, file_raw = await dequeue_file_ingest_job(timeout=0)
        if file_job is not None and file_raw is not None:
            logger.info("Worker picked up job %s for capture %s", file_job.type, file_job.capture_id)
            try:
                await process_file_capture(file_job.capture_id)
            finally:
                await ack_file_ingest_job(file_raw)
                logger.debug("Acknowledged file job for capture %s", file_job.capture_id)
            return True

    return False



async def run_worker(
    once: bool = False,
    poll_timeout: int = 2,
    allow_localhost: bool = False,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Run the worker loop continuously or for a single job."""
    logger.info("LENS Background Worker started (mode=%s)", "single-job" if once else "continuous")

    if stop_event is None:
        stop_event = asyncio.Event()

    while not stop_event.is_set():
        try:
            processed = await process_one_job(
                timeout=poll_timeout,
                allow_localhost=allow_localhost,
            )
            if once:
                logger.info("Single-job execution finished (job_processed=%s)", processed)
                break
        except asyncio.CancelledError:
            logger.info("Worker task received cancellation signal")
            break
        except Exception as e:
            logger.exception("Unexpected error in worker execution loop: %s", e)
            if once:
                break
            await asyncio.sleep(1)


def main() -> None:
    """CLI entrypoint for worker service."""
    parser = argparse.ArgumentParser(description="LENS Background Processing Worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single job from the queue and exit.",
    )
    parser.add_argument(
        "--allow-localhost",
        action="store_true",
        help="Allow fetching from loopback addresses (for local integration testing only).",
    )
    args = parser.parse_args()

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Received termination signal; shutting down worker gracefully...")
        stop_event.set()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Register OS signals where supported
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

    try:
        loop.run_until_complete(
            run_worker(
                once=args.once,
                allow_localhost=args.allow_localhost,
                stop_event=stop_event,
            )
        )
    finally:
        loop.run_until_complete(close_connections())
        loop.close()
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    main()
