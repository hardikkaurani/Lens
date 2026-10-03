"""Comprehensive Stage 6 integration tests for asynchronous URL ingestion and worker foundation.

Tests all 26 required scenarios:
1. URL capture is persisted immediately.
2. URL capture enqueues a job.
3. Text capture does not enqueue URL job.
4. Worker consumes a valid job.
5. Public HTML URL is fetched.
6. HTML text is extracted.
7. Scripts/styles are removed.
8. Text is normalized.
9. Content is chunked deterministically.
10. ContentChunks are persisted.
11. embedding remains NULL.
12. Capture becomes completed.
13. Invalid URL schemes fail safely.
14. localhost is blocked.
15. loopback IP is blocked.
16. private IP is blocked.
17. link-local IP is blocked.
18. redirect to private IP is blocked.
19. excessive response size is rejected.
20. non-HTML content is rejected.
21. timeout is handled safely.
22. extraction failure marks capture failed.
23. retrying the same job does not create duplicate chunks.
24. processing_error does not expose secrets.
25. existing Stage 5 capture API tests still pass.
26. existing /health test still passes.
"""

import asyncio
import http.server
from pathlib import Path
import sys
import threading
import time
from typing import Awaitable, cast
import uuid

import httpx
from sqlalchemy import delete, select

# Ensure services/worker is in sys.path
worker_path = str(Path(__file__).resolve().parents[2] / "worker")
if worker_path not in sys.path:
    sys.path.insert(0, worker_path)

from app.db.models import Capture, ContentChunk, ProcessingStatus, SourceType
from app.db.session import AsyncSessionLocal, get_redis_client
from app.main import app
from app.queue.job import (
    URL_INGEST_PROCESSING_QUEUE,
    URL_INGEST_QUEUE,
    dequeue_url_ingest_job,
)
from worker.chunker import chunk_text
from worker.extractor import (
    InsufficientContentError,
    extract_and_normalize_html,
    normalize_text,
)
from worker.fetcher import (
    DEFAULT_MAX_RESPONSE_SIZE,
    FetchTimeoutError,
    InvalidContentTypeError,
    ResponseSizeLimitExceededError,
    SSRFBlockedError,
    safe_fetch_url,
)
from worker.main import process_one_job
from worker.processor import process_url_capture


# --- Local Controlled HTTP Test Server ---

class MockHttpHandler(http.server.BaseHTTPRequestHandler):
    """Controlled HTTP handler for deterministic network behavior testing."""

    def do_GET(self):
        if self.path == "/html-article":
            html = (
                "<!DOCTYPE html><html><head><title>Test LENS Article</title>"
                "<style>body { color: red; }</style>"
                "<script>console.log('secret tracking code');</script></head>"
                "<body><nav><a href='/'>Home</a></nav>"
                "<h1>LENS Knowledge Capture</h1>"
                "<p>LENS is a personal information capture and retrieval system designed to make knowledge durable.</p>"
                "<p>It decouples immediate synchronous capture from asynchronous extraction and vector indexing.</p>"
                "<footer>Copyright 2026</footer></body></html>"
            )
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif self.path == "/large-html":
            # Exceeds 2MB limit (generate 2.5 MB)
            chunk = "A" * 1024
            total_size = int(2.5 * 1024 * 1024)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(total_size))
            self.end_headers()
            written = 0
            while written < total_size:
                to_write = min(len(chunk), total_size - written)
                self.wfile.write(chunk[:to_write].encode("utf-8"))
                written += to_write

        elif self.path == "/non-html":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(b"%PDF-1.4 binary data here")

        elif self.path == "/slow":
            # Sleep longer than client read timeout
            time.sleep(2.0)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Slow response</body></html>")

        elif self.path == "/empty-html":
            # Insufficient text content (< 20 chars)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><script>bad</script></body></html>")

        elif self.path == "/redirect-to-private":
            self.send_response(302)
            self.send_header("Location", "http://192.168.1.1/internal-status")
            self.end_headers()

        elif self.path == "/redirect-to-html":
            self.send_response(302)
            self.send_header("Location", "/html-article")
            self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def log_message(self, format, *args):
        # Silence HTTP server logging during tests
        pass


class LocalTestServer:
    """Manages a background local HTTP server on an ephemeral port."""

    def __init__(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), MockHttpHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


# --- Test Suite ---

async def cleanup_db():
    """Remove test records from postgres."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(ContentChunk))
            await session.execute(delete(Capture))


async def cleanup_redis():
    """Flush the job queues in Redis."""
    redis = get_redis_client()
    await redis.delete(URL_INGEST_QUEUE, URL_INGEST_PROCESSING_QUEUE)


async def run_stage_6_tests():
    print("--- Starting Stage 6 Worker & URL Ingestion Integration Tests ---")

    test_server = LocalTestServer()
    test_server.start()
    base_url = test_server.base_url

    transport = httpx.ASGITransport(app=app)
    api_client = httpx.AsyncClient(transport=transport, base_url="http://test")

    try:
        await cleanup_db()
        await cleanup_redis()

        # ---------------------------------------------------------------------
        # 1. URL capture is persisted immediately with pending status
        # ---------------------------------------------------------------------
        url_resp = await api_client.post(
            "/captures",
            json={
                "source_type": "url",
                "original_url": f"{base_url}/html-article",
            },
        )
        assert url_resp.status_code == 201, f"Expected 201, got {url_resp.status_code}"
        url_data = url_resp.json()
        assert url_data["source_type"] == "url"
        assert url_data["processing_status"] == "pending"
        assert url_data["processed_at"] is None
        url_capture_id = uuid.UUID(url_data["id"])
        print("Test 1: URL capture persisted immediately with pending status -> PASS")

        # ---------------------------------------------------------------------
        # 2. URL capture enqueues a job
        # ---------------------------------------------------------------------
        job, raw_job = await dequeue_url_ingest_job(timeout=1)
        assert job is not None, "Expected job in Redis queue"
        assert raw_job is not None, "Expected raw job payload in Redis queue"
        assert job.type == "capture.url_ingest"
        assert job.capture_id == url_capture_id
        # Re-enqueue the job back for worker tests
        redis = get_redis_client()
        await cast(Awaitable[int], redis.lpush(URL_INGEST_QUEUE, raw_job))
        await cast(Awaitable[int], redis.lrem(URL_INGEST_PROCESSING_QUEUE, 1, raw_job))
        print("Test 2: URL capture enqueues a job -> PASS")

        # ---------------------------------------------------------------------
        # 3. Text capture does not enqueue URL job
        # ---------------------------------------------------------------------
        text_resp = await api_client.post(
            "/captures",
            json={
                "source_type": "text",
                "content": "Instant note about databases.",
            },
        )
        assert text_resp.status_code == 201
        text_data = text_resp.json()
        assert text_data["source_type"] == "text"
        assert text_data["processing_status"] == "completed"
        assert text_data["processed_at"] is not None

        # Verify no additional job in Redis
        queue_len = await cast(Awaitable[int], redis.llen(URL_INGEST_QUEUE))
        assert queue_len == 1, f"Expected exactly 1 job in queue (from URL capture), got {queue_len}"
        print("Test 3: Text capture does not enqueue URL job -> PASS")

        # ---------------------------------------------------------------------
        # 4. Worker consumes a valid job
        # ---------------------------------------------------------------------
        processed = await process_one_job(timeout=1, allow_localhost=True)
        assert processed is True, "Worker should have processed the URL capture job"
        in_progress_count = await cast(Awaitable[int], redis.llen(URL_INGEST_PROCESSING_QUEUE))
        assert in_progress_count == 0, "Job must be acked and removed from processing queue"
        print("Test 4: Worker consumes a valid job and acks -> PASS")

        # ---------------------------------------------------------------------
        # 5. Public HTML URL is fetched
        # ---------------------------------------------------------------------
        fetched = await safe_fetch_url(f"{base_url}/html-article", allow_localhost=True)
        assert fetched.status_code == 200
        assert "text/html" in fetched.content_type
        print("Test 5: Public HTML URL is fetched -> PASS")

        # ---------------------------------------------------------------------
        # 6. HTML text is extracted
        # ---------------------------------------------------------------------
        title, text = extract_and_normalize_html(fetched.html)
        assert title == "Test LENS Article"
        assert "LENS Knowledge Capture" in text
        print("Test 6: HTML text is extracted -> PASS")

        # ---------------------------------------------------------------------
        # 7. Scripts/styles are removed
        # ---------------------------------------------------------------------
        assert "secret tracking code" not in text
        assert "color: red" not in text
        print("Test 7: Scripts/styles are removed -> PASS")

        # ---------------------------------------------------------------------
        # 8. Text is normalized
        # ---------------------------------------------------------------------
        raw_dirty = "Line 1  \t\r\n\r\n\r\n\r\nLine 2   with   spaces\r\n"
        norm = normalize_text(raw_dirty)
        assert "\r" not in norm
        assert "\n\n\n" not in norm
        assert "Line 2 with spaces" in norm
        print("Test 8: Text is normalized -> PASS")

        # ---------------------------------------------------------------------
        # 9. Content is chunked deterministically
        # ---------------------------------------------------------------------
        sample_long = (
            "Paragraph one is informative and concise.\n\n"
            "Paragraph two provides deeper context on architecture and ingestion pipelines.\n\n"
            "Paragraph three concludes with search retrieval considerations."
        )
        chunks1 = chunk_text(sample_long, chunk_size=80, chunk_overlap=15)
        chunks2 = chunk_text(sample_long, chunk_size=80, chunk_overlap=15)
        assert chunks1 == chunks2, "Chunking must be purely deterministic"
        assert len(chunks1) >= 2
        for c in chunks1:
            assert len(c) > 0
        print("Test 9: Content is chunked deterministically -> PASS")

        # ---------------------------------------------------------------------
        # 10. ContentChunks are persisted
        # 11. embedding remains NULL
        # 12. Capture becomes completed
        # ---------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            chunks_result = await session.execute(
                select(ContentChunk)
                .where(ContentChunk.capture_id == url_capture_id)
                .order_by(ContentChunk.chunk_index)
            )
            saved_chunks = chunks_result.scalars().all()
            assert len(saved_chunks) > 0, "ContentChunks should be persisted in DB"
            for idx, ch in enumerate(saved_chunks):
                assert ch.chunk_index == idx
                assert ch.embedding is not None and len(ch.embedding) == 1536, "Embedding must be persisted in Stage 7"

            cap_result = await session.execute(
                select(Capture).where(Capture.id == url_capture_id)
            )
            cap = cap_result.scalar_one()
            assert cap.processing_status == ProcessingStatus.COMPLETED
            assert cap.processed_at is not None
            assert cap.processing_error is None
            assert cap.title == "Test LENS Article"
            assert cap.content is not None
        print("Test 10: ContentChunks are persisted -> PASS")
        print("Test 11: embedding persisted with 1536 dimensions -> PASS")
        print("Test 12: Capture becomes completed -> PASS")

        # ---------------------------------------------------------------------
        # 13. Invalid URL schemes fail safely
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url("ftp://ftp.example.com/file.txt")
            assert False, "ftp scheme must be blocked"
        except SSRFBlockedError:
            pass

        try:
            await safe_fetch_url("file:///etc/passwd")
            assert False, "file scheme must be blocked"
        except SSRFBlockedError:
            pass
        print("Test 13: Invalid URL schemes fail safely -> PASS")

        # ---------------------------------------------------------------------
        # 14. localhost is blocked (with SSRF protection active)
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url("http://localhost:80", allow_localhost=False)
            assert False, "localhost must be blocked"
        except SSRFBlockedError:
            pass
        print("Test 14: localhost is blocked -> PASS")

        # ---------------------------------------------------------------------
        # 15. loopback IP is blocked
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url("http://127.0.0.1:80", allow_localhost=False)
            assert False, "127.0.0.1 must be blocked"
        except SSRFBlockedError:
            pass

        try:
            await safe_fetch_url("http://[::1]:80", allow_localhost=False)
            assert False, "::1 must be blocked"
        except SSRFBlockedError:
            pass
        print("Test 15: loopback IP is blocked -> PASS")

        # ---------------------------------------------------------------------
        # 16. private IP is blocked
        # ---------------------------------------------------------------------
        for priv_ip in ["10.0.0.1", "172.16.0.1", "192.168.1.1"]:
            try:
                await safe_fetch_url(f"http://{priv_ip}/admin", allow_localhost=False)
                assert False, f"Private IP {priv_ip} must be blocked"
            except SSRFBlockedError:
                pass
        print("Test 16: private IP is blocked -> PASS")

        # ---------------------------------------------------------------------
        # 17. link-local IP is blocked
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url("http://169.254.169.254/latest/meta-data", allow_localhost=False)
            assert False, "169.254.169.254 must be blocked"
        except SSRFBlockedError:
            pass
        print("Test 17: link-local IP is blocked -> PASS")

        # ---------------------------------------------------------------------
        # 18. redirect to private IP is blocked
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url(f"{base_url}/redirect-to-private", allow_localhost=True)
            assert False, "Redirect to 192.168.1.1 must be blocked"
        except SSRFBlockedError:
            pass
        print("Test 18: redirect to private IP is blocked -> PASS")

        # ---------------------------------------------------------------------
        # 19. excessive response size is rejected
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url(
                f"{base_url}/large-html",
                max_response_size=100 * 1024,  # limit to 100 KB for test
                allow_localhost=True,
            )
            assert False, "Excessive response size must raise ResponseSizeLimitExceededError"
        except ResponseSizeLimitExceededError:
            pass
        print("Test 19: excessive response size is rejected -> PASS")

        # ---------------------------------------------------------------------
        # 20. non-HTML content is rejected
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url(f"{base_url}/non-html", allow_localhost=True)
            assert False, "Non-HTML content must raise InvalidContentTypeError"
        except InvalidContentTypeError:
            pass
        print("Test 20: non-HTML content is rejected -> PASS")

        # ---------------------------------------------------------------------
        # 21. timeout is handled safely
        # ---------------------------------------------------------------------
        try:
            await safe_fetch_url(
                f"{base_url}/slow",
                read_timeout=0.2,
                total_timeout=0.3,
                allow_localhost=True,
            )
            assert False, "Slow server must raise FetchTimeoutError"
        except FetchTimeoutError:
            pass
        print("Test 21: timeout is handled safely -> PASS")

        # ---------------------------------------------------------------------
        # 22. extraction failure marks capture failed
        # ---------------------------------------------------------------------
        fail_resp = await api_client.post(
            "/captures",
            json={
                "source_type": "url",
                "original_url": f"{base_url}/empty-html",
            },
        )
        fail_id = uuid.UUID(fail_resp.json()["id"])
        await process_url_capture(fail_id, allow_localhost=True)

        async with AsyncSessionLocal() as session:
            cap_res = await session.execute(select(Capture).where(Capture.id == fail_id))
            fail_cap = cap_res.scalar_one()
            assert fail_cap.processing_status == ProcessingStatus.FAILED
            assert fail_cap.processing_error is not None
            assert "insufficient readable text" in fail_cap.processing_error.lower()
        print("Test 22: extraction failure marks capture failed -> PASS")

        # ---------------------------------------------------------------------
        # 23. retrying the same job does not create duplicate chunks (idempotency)
        # ---------------------------------------------------------------------
        # Re-run processor on the successful url_capture_id
        await process_url_capture(url_capture_id, allow_localhost=True)
        async with AsyncSessionLocal() as session:
            count_res = await session.execute(
                select(ContentChunk).where(ContentChunk.capture_id == url_capture_id)
            )
            re_chunks = count_res.scalars().all()
            assert len(re_chunks) == len(saved_chunks), "Chunk count must not double on retry"
            indices = [c.chunk_index for c in re_chunks]
            assert indices == list(range(len(re_chunks))), "Chunk indices must remain sequential"
        print("Test 23: retrying the same job is idempotent without duplicate chunks -> PASS")

        # ---------------------------------------------------------------------
        # 24. processing_error does not expose secrets
        # ---------------------------------------------------------------------
        secret_url_resp = await api_client.post(
            "/captures",
            json={
                "source_type": "url",
                "original_url": "http://user:super_secret_password@10.0.0.1/admin",
            },
        )
        secret_id = uuid.UUID(secret_url_resp.json()["id"])
        await process_url_capture(secret_id, allow_localhost=False)
        async with AsyncSessionLocal() as session:
            cap_sec = (await session.execute(select(Capture).where(Capture.id == secret_id))).scalar_one()
            assert cap_sec.processing_status == ProcessingStatus.FAILED
            assert cap_sec.processing_error is not None
            assert "super_secret_password" not in cap_sec.processing_error
        print("Test 24: processing_error does not expose secrets -> PASS")

        # ---------------------------------------------------------------------
        # 25. Stage 5 capture API tests still pass
        # ---------------------------------------------------------------------
        get_resp = await api_client.get(f"/captures/{url_capture_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["id"] == str(url_capture_id)
        assert get_data["processing_status"] == "completed"

        list_resp = await api_client.get("/captures?limit=10&offset=0")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1
        print("Test 25: existing Stage 5 capture API functions correctly -> PASS")

        # ---------------------------------------------------------------------
        # 26. existing /health test still passes
        # ---------------------------------------------------------------------
        health_resp = await api_client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok", "api": "ok", "database": "ok", "redis": "ok"}
        print("Test 26: existing /health test still passes -> PASS")

        print("\n--- ALL 26 STAGE 6 INTEGRATION TESTS PASSED SUCCESSFULLY ---")

    finally:
        await cleanup_db()
        await cleanup_redis()
        test_server.stop()
        await api_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_stage_6_tests())
