"""Integration test suite for LENS Capture Ingestion API (Stage 5).

Covers:
1. Create text capture.
2. Create URL capture.
3. Create capture with metadata.
4. Reject empty text.
5. Reject invalid URL.
6. Reject unsupported source type.
7. Reject missing required fields.
8. Get capture by ID.
9. Get nonexistent capture -> 404 (and malformed UUID -> 422).
10. List captures.
11. Pagination.
12. Newest-first ordering.
13. Verify metadata persistence.
14. Verify transaction behavior if metadata persistence fails.
"""

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.db.models import Capture, ContentChunk, SourceMetadata
from app.db.session import AsyncSessionLocal, close_connections
from app.main import app


async def clean_database() -> None:
    """Purge all records created during testing."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ContentChunk))
        await session.execute(delete(SourceMetadata))
        await session.execute(delete(Capture))
        await session.commit()


async def run_all_tests() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        print("\n--- Starting Stage 5 Integration Tests ---")

        # Initial cleanup
        await clean_database()

        # ----------------------------------------------------------------------
        # Test 1: Create text capture
        # ----------------------------------------------------------------------
        res1 = await client.post(
            "/captures",
            json={
                "source_type": "text",
                "title": "Design Doc Notes",
                "content": "Architecture decision regarding capture ingestion.",
            },
        )
        assert res1.status_code == 201, f"Test 1 failed: {res1.text}"
        data1 = res1.json()
        assert data1["source_type"] == "text"
        assert data1["title"] == "Design Doc Notes"
        assert data1["content"] == "Architecture decision regarding capture ingestion."
        assert data1["id"] is not None
        assert data1["metadata"] is None
        text_id = data1["id"]
        print("Test 1: Create text capture -> PASS")

        # ----------------------------------------------------------------------
        # Test 2: Create URL capture
        # ----------------------------------------------------------------------
        res2 = await client.post(
            "/captures",
            json={
                "source_type": "url",
                "original_url": "https://fastapi.tiangolo.com/tutorial/",
                "title": "FastAPI Documentation",
            },
        )
        assert res2.status_code == 201, f"Test 2 failed: {res2.text}"
        data2 = res2.json()
        assert data2["source_type"] == "url"
        assert data2["original_url"] == "https://fastapi.tiangolo.com/tutorial/"
        assert data2["title"] == "FastAPI Documentation"
        url_id = data2["id"]
        print("Test 2: Create URL capture -> PASS")

        # ----------------------------------------------------------------------
        # Test 3: Create capture with metadata
        # ----------------------------------------------------------------------
        sample_meta = {
            "author": "tiangolo",
            "domain": "fastapi.tiangolo.com",
            "tags": ["python", "api", "framework"],
        }
        res3 = await client.post(
            "/captures",
            json={
                "source_type": "url",
                "original_url": "https://fastapi.tiangolo.com",
                "title": "FastAPI Homepage",
                "metadata": sample_meta,
            },
        )
        assert res3.status_code == 201, f"Test 3 failed: {res3.text}"
        data3 = res3.json()
        assert data3["metadata"] == sample_meta
        meta_capture_id = data3["id"]
        print("Test 3: Create capture with metadata -> PASS")

        # ----------------------------------------------------------------------
        # Test 4: Reject empty or whitespace-only text
        # ----------------------------------------------------------------------
        res4_empty = await client.post(
            "/captures",
            json={"source_type": "text", "content": ""},
        )
        assert res4_empty.status_code == 422, f"Expected 422, got {res4_empty.status_code}"

        res4_ws = await client.post(
            "/captures",
            json={"source_type": "text", "content": "   \n\t  "},
        )
        assert res4_ws.status_code == 422, f"Expected 422, got {res4_ws.status_code}"
        print("Test 4: Reject empty and whitespace text -> PASS")

        # ----------------------------------------------------------------------
        # Test 5: Reject invalid URL
        # ----------------------------------------------------------------------
        invalid_urls = [
            "not-a-valid-url",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "ftp://example.com/file",
            "/relative/path",
        ]
        for bad_url in invalid_urls:
            res_bad = await client.post(
                "/captures",
                json={"source_type": "url", "original_url": bad_url},
            )
            assert res_bad.status_code == 422, f"Expected 422 for '{bad_url}', got {res_bad.status_code}"
        print("Test 5: Reject invalid URLs and schemes -> PASS")

        # ----------------------------------------------------------------------
        # Test 6: Reject unsupported source types
        # ----------------------------------------------------------------------
        for unsupported in ["image", "pdf", "file", "github", "video", "audio"]:
            res_unsupported = await client.post(
                "/captures",
                json={"source_type": unsupported, "title": "Test"},
            )
            assert res_unsupported.status_code == 422, f"Expected 422 for '{unsupported}', got {res_unsupported.status_code}"
        print("Test 6: Reject unsupported source types -> PASS")

        # ----------------------------------------------------------------------
        # Test 7: Reject missing required fields
        # ----------------------------------------------------------------------
        res7_no_content = await client.post(
            "/captures",
            json={"source_type": "text", "title": "Only Title"},
        )
        assert res7_no_content.status_code == 422

        res7_no_url = await client.post(
            "/captures",
            json={"source_type": "url", "title": "Only Title"},
        )
        assert res7_no_url.status_code == 422
        print("Test 7: Reject missing required fields -> PASS")

        # ----------------------------------------------------------------------
        # Test 8: Get capture by ID
        # ----------------------------------------------------------------------
        res8 = await client.get(f"/captures/{text_id}")
        assert res8.status_code == 200, f"Test 8 failed: {res8.text}"
        data8 = res8.json()
        assert data8["id"] == text_id
        assert data8["title"] == "Design Doc Notes"
        print("Test 8: Get capture by ID -> PASS")

        # ----------------------------------------------------------------------
        # Test 9: Get nonexistent capture -> 404 (and malformed UUID -> 422)
        # ----------------------------------------------------------------------
        random_uuid = str(uuid.uuid4())
        res9_404 = await client.get(f"/captures/{random_uuid}")
        assert res9_404.status_code == 404, f"Expected 404, got {res9_404.status_code}"
        assert "not found" in res9_404.json()["detail"].lower()

        res9_422 = await client.get("/captures/invalid-uuid-format")
        assert res9_422.status_code == 422, f"Expected 422, got {res9_422.status_code}"
        print("Test 9: Get nonexistent capture (404) & malformed UUID (422) -> PASS")

        # ----------------------------------------------------------------------
        # Test 10: List captures
        # ----------------------------------------------------------------------
        res10 = await client.get("/captures")
        assert res10.status_code == 200
        data10 = res10.json()
        assert "items" in data10
        assert data10["total"] == 3
        assert len(data10["items"]) == 3
        assert data10["limit"] == 20
        assert data10["offset"] == 0
        print("Test 10: List captures -> PASS")

        # ----------------------------------------------------------------------
        # Test 11: Pagination
        # ----------------------------------------------------------------------
        res11 = await client.get("/captures?limit=2&offset=1")
        assert res11.status_code == 200
        data11 = res11.json()
        assert data11["total"] == 3
        assert len(data11["items"]) == 2
        assert data11["limit"] == 2
        assert data11["offset"] == 1
        print("Test 11: Pagination (limit & offset) -> PASS")

        # ----------------------------------------------------------------------
        # Test 12: Newest-first ordering
        # ----------------------------------------------------------------------
        res12 = await client.get("/captures?limit=10&offset=0")
        items = res12.json()["items"]
        dates = [item["created_at"] for item in items]
        assert dates == sorted(dates, reverse=True), "Items must be sorted descending by created_at"
        # Most recently created capture should be first
        assert items[0]["id"] == meta_capture_id
        print("Test 12: Newest-first ordering -> PASS")

        # ----------------------------------------------------------------------
        # Test 13: Verify metadata persistence
        # ----------------------------------------------------------------------
        res13 = await client.get(f"/captures/{meta_capture_id}")
        assert res13.status_code == 200
        data13 = res13.json()
        assert data13["metadata"] == sample_meta

        # Verify directly in PostgreSQL
        async with AsyncSessionLocal() as session:
            stmt = select(SourceMetadata).where(SourceMetadata.capture_id == uuid.UUID(meta_capture_id))
            db_meta = (await session.execute(stmt)).scalar_one_or_none()
            assert db_meta is not None
            assert db_meta.payload == sample_meta
        print("Test 13: Verify metadata persistence in DB & API -> PASS")

        # ----------------------------------------------------------------------
        # Test 14: Verify transaction atomicity on failure
        # ----------------------------------------------------------------------
        # Check current count in database
        async with AsyncSessionLocal() as session:
            initial_count = (await session.execute(select(func.count()).select_from(Capture))).scalar()

        # Simulate database failure during SourceMetadata instantiation/addition
        with patch("app.captures.router.SourceMetadata", side_effect=RuntimeError("Simulated metadata failure")):
            res14 = await client.post(
                "/captures",
                json={
                    "source_type": "text",
                    "title": "Should rollback",
                    "content": "This content must not be saved",
                    "metadata": {"some": "data"},
                },
            )
            assert res14.status_code == 500, f"Expected 500, got {res14.status_code}"
            assert "safely rolled back" in res14.json()["detail"].lower()

        # Verify Capture was NOT saved (count unchanged)
        async with AsyncSessionLocal() as session:
            final_count = (await session.execute(select(func.count()).select_from(Capture))).scalar()
            assert final_count == initial_count, f"Transaction was not atomic! Count changed from {initial_count} to {final_count}"
        print("Test 14: Verify transaction atomicity on failure -> PASS")

        # ----------------------------------------------------------------------
        # Final cleanup: purge test records
        # ----------------------------------------------------------------------
        await clean_database()
        async with AsyncSessionLocal() as session:
            post_cleanup_count = (await session.execute(select(func.count()).select_from(Capture))).scalar()
            assert post_cleanup_count == 0, f"Expected 0 records after cleanup, got {post_cleanup_count}"
        print("Final Cleanup: Database cleared -> PASS")

    await close_connections()
    print("\n--- All Stage 5 Integration Tests PASSED Successfully ---")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
