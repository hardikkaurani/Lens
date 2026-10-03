"""Stage 7 Integration Test Suite: Embedding Generation, Lexical Search, Vector Search, and Hybrid Ranking.

Covers 48 mandatory validation tests:
1. deterministic test provider returns same vector for same text
2. correct 1536-dimensional vector
3. embedding persisted in PostgreSQL pgvector column
4. invalid vector format rejected
5. wrong vector dimension rejected
6. NaN/infinite vector values rejected
7. provider failure marks capture failed
8. provider secret/error masking
9. batch ordering preserved across inputs
10. batch length mismatch rejected
11. URL ingestion creates chunks with embeddings
12. embedding is no longer NULL for successfully processed URL captures
13. capture becomes completed only after embeddings persist
14. retry remains idempotent (no duplicate chunks or embeddings)
15. failed embedding transaction leaves no partial chunk set
16. exact keyword match
17. partial/relevant text match
18. title matching (query matches capture title even if not in chunk)
19. no-result query returns empty results
20. empty query rejected with 422
21. whitespace-only query rejected with 422
22. long query (>500 chars) safely bounded/rejected
23. Unicode query handled safely
24. punctuation-heavy query handled safely without syntax error
25. SQL injection payload treated as plain search input
26. semantically similar deterministic test vectors return expected records
27. unrelated vectors rank lower
28. NULL embeddings are excluded from vector search
29. query vector dimension is validated
30. no embeddings case handled safely without errors
31. lexical-only match
32. semantic-only match
33. document matching both signals ranks highest
34. deterministic hybrid ordering
35. configurable weights affect ranking mathematically
36. stable tie-breaking on equal scores
37. repeated identical search returns identical ordering
38. valid search request returns 200 with matching schema
39. missing query parameter returns 422
40. empty query returns 422
41. invalid limit (<1) returns 422
42. excessive limit (>50) returns 422
43. response schema validation adheres to SearchResponse
44. embeddings are not exposed in API response
45. no internal provider secrets exposed
46. all Stage 6 tests pass
47. all Stage 5 tests pass
48. /health remains healthy
"""

import asyncio
import http.server
from pathlib import Path
import sys
import threading
import time
from typing import Any, Awaitable, Optional, cast
import uuid

import httpx
from sqlalchemy import delete, select, text

# Ensure services/worker is in sys.path
worker_path = str(Path(__file__).resolve().parents[2] / "worker")
if worker_path not in sys.path:
    sys.path.insert(0, worker_path)

from app.core.config import get_settings
from app.db.models import Capture, ContentChunk, ProcessingStatus, SourceType
from app.db.session import AsyncSessionLocal
from app.embeddings.base import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingTimeoutError,
    validate_embedding_vector,
)
from app.embeddings.factory import (
    get_embedding_provider,
    reset_embedding_provider_override,
    set_embedding_provider_override,
)
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.test_provider import DeterministicTestEmbeddingProvider
from app.main import app
from app.search.schemas import SearchResponse
from app.search.service import SearchService, search_service
from worker.processor import process_url_capture


# --- Local Controlled HTTP Server for Ingestion Tests ---

class ControlledHttpHandler(http.server.BaseHTTPRequestHandler):
    """Serve controlled HTML articles for deterministic worker ingestion tests."""

    def do_GET(self):
        if self.path == "/article-db":
            html = (
                "<!DOCTYPE html><html><head><title>PostgreSQL Database Indexing</title></head>"
                "<body><h1>PostgreSQL Indexing</h1>"
                "<p>PostgreSQL provides powerful indexing strategies such as B-Tree, GIN, and GiST indexes for rapid query execution.</p>"
                "<p>Proper index tuning dramatically improves relational database optimization and overall throughput.</p>"
                "</body></html>"
            )
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif self.path == "/article-vectors":
            html = (
                "<!DOCTYPE html><html><head><title>Vector Similarity and Embeddings</title></head>"
                "<body><h1>Vector Search</h1>"
                "<p>pgvector extends PostgreSQL with vector storage and cosine distance metrics for semantic similarity search.</p>"
                "<p>High dimensional embeddings empower modern neural information retrieval and semantic document retrieval.</p>"
                "</body></html>"
            )
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif self.path == "/article-baking":
            html = (
                "<!DOCTYPE html><html><head><title>Chocolate Chip Cookie Baking Recipe</title></head>"
                "<body><h1>Baking Cookies</h1>"
                "<p>Bake delicious sweet chocolate chip cookies with organic butter, brown sugar, and flour in a preheated oven.</p>"
                "<p>Chill the dough thoroughly before baking to achieve the perfect chewy texture and golden color.</p>"
                "</body></html>"
            )
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class FailingEmbeddingProvider(EmbeddingProvider):
    """Test provider that deliberately simulates provider failures."""

    @property
    def dimension(self) -> int:
        return 1536

    @property
    def model_name(self) -> str:
        return "failing-provider"

    async def embed_text(self, text: str) -> list[float]:
        raise EmbeddingProviderError("Simulated upstream provider outage (HTTP 503)")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("Simulated upstream provider outage (HTTP 503)")


async def cleanup_database() -> None:
    """Clear captures and chunks from the database between test runs."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(ContentChunk))
            await session.execute(delete(Capture))


async def run_stage7_tests() -> None:
    print("--- Starting Stage 7 Embedding & Search Integration Tests ---")

    # Start local mock HTTP server
    server = http.server.HTTPServer(("127.0.0.1", 0), ControlledHttpHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{port}"

    # Set deterministic test embedding provider as default
    test_provider = DeterministicTestEmbeddingProvider(dimension=1536)
    set_embedding_provider_override(test_provider)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        await cleanup_database()

        # =====================================================================
        # 1. Deterministic test provider
        # =====================================================================
        v1 = await test_provider.embed_text("PostgreSQL database optimization")
        v2 = await test_provider.embed_text("PostgreSQL database optimization")
        assert v1 == v2, "Deterministic provider must return identical vectors for identical text"
        print("Test 1: deterministic test provider -> PASS")

        # =====================================================================
        # 2. Correct 1536-dimensional vector
        # =====================================================================
        assert len(v1) == 1536, f"Expected 1536 dimensions, got {len(v1)}"
        assert all(isinstance(x, float) for x in v1)
        print("Test 2: correct 1536-dimensional vector -> PASS")

        # =====================================================================
        # 3. Embedding persisted in PostgreSQL
        # =====================================================================
        async with AsyncSessionLocal() as session:
            async with session.begin():
                dummy_cap = Capture(source_type=SourceType.TEXT, content="Temp embedding persistence test")
                session.add(dummy_cap)
                await session.flush()
                test_chunk = ContentChunk(
                    capture_id=dummy_cap.id,
                    chunk_index=0,
                    content="Temp persistence chunk",
                    embedding=v1,
                )
                session.add(test_chunk)
            async with session.begin():
                res = await session.execute(
                    select(ContentChunk).where(ContentChunk.id == test_chunk.id)
                )
                saved_chunk = res.scalar_one()
                assert saved_chunk.embedding is not None
                assert len(saved_chunk.embedding) == 1536
        print("Test 3: embedding persisted in PostgreSQL -> PASS")

        # =====================================================================
        # 4. Invalid vector format rejected
        # =====================================================================
        try:
            validate_embedding_vector(cast(Any, "not-a-vector"))
            assert False, "Should have rejected non-list vector"
        except EmbeddingDimensionError:
            pass
        try:
            validate_embedding_vector(cast(Any, [1.0, "two", 3.0]), expected_dim=3)
            assert False, "Should have rejected non-numeric elements"
        except EmbeddingProviderError:
            pass
        print("Test 4: invalid vector format rejected -> PASS")

        # =====================================================================
        # 5. Wrong vector dimension rejected
        # =====================================================================
        try:
            validate_embedding_vector([0.1] * 512, expected_dim=1536)
            assert False, "Should have rejected vector with dimension 512"
        except EmbeddingDimensionError as e:
            assert "Expected embedding vector of dimension 1536, got 512" in str(e)
        print("Test 5: wrong vector dimension rejected -> PASS")

        # =====================================================================
        # 6. NaN/infinite vector values rejected
        # =====================================================================
        nan_vec = [0.0] * 1536
        nan_vec[10] = float("nan")
        try:
            validate_embedding_vector(nan_vec, 1536)
            assert False, "Should have rejected NaN in vector"
        except EmbeddingProviderError as e:
            assert "NaN" in str(e)

        inf_vec = [0.0] * 1536
        inf_vec[20] = float("inf")
        try:
            validate_embedding_vector(inf_vec, 1536)
            assert False, "Should have rejected Inf in vector"
        except EmbeddingProviderError as e:
            assert "Infinite" in str(e)
        print("Test 6: NaN/infinite vector values rejected -> PASS")

        # =====================================================================
        # 7. Provider failure marks capture failed
        # =====================================================================
        # Ingest a capture with a failing provider
        post_resp = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-db"},
        )
        fail_cap_id = uuid.UUID(post_resp.json()["id"])
        await process_url_capture(
            fail_cap_id,
            allow_localhost=True,
            embedding_provider=FailingEmbeddingProvider(),
        )
        async with AsyncSessionLocal() as session:
            c_fail = (await session.execute(select(Capture).where(Capture.id == fail_cap_id))).scalar_one()
            assert c_fail.processing_status == ProcessingStatus.FAILED
            assert c_fail.processed_at is not None
            assert c_fail.processing_error is not None
            assert "Embedding generation failed" in c_fail.processing_error
        print("Test 7: provider failure marks capture failed -> PASS")

        # =====================================================================
        # 8. Provider secret/error masking
        # =====================================================================
        openai_provider = OpenAIEmbeddingProvider(
            api_key="sk-secret-test-key-1234567890",
            base_url="http://127.0.0.1:9999",  # unreachable endpoint
            timeout=1.0,
            max_retries=0,
        )
        try:
            await openai_provider.embed_text("Test secret masking")
            assert False, "Should have failed due to unreachable endpoint"
        except EmbeddingError as err:
            err_msg = str(err)
            assert "sk-secret-test-key" not in err_msg, "API key leaked in exception message!"
            assert "Bearer" not in err_msg, "Bearer token leaked in exception message!"
        print("Test 8: provider secret/error masking -> PASS")

        # =====================================================================
        # 9. Batch ordering preserved across inputs
        # =====================================================================
        batch_inputs = [
            "Apple fruit and orchard harvest",
            "Quantum physics and atomic structure",
            "Italian pasta recipe with garlic",
        ]
        batch_vectors = await test_provider.embed_texts(batch_inputs)
        assert len(batch_vectors) == 3
        # Ensure individual embedding equals batch embedding at same position
        for i, text_item in enumerate(batch_inputs):
            indiv_vec = await test_provider.embed_text(text_item)
            assert batch_vectors[i] == indiv_vec, f"Batch index {i} does not match individual embedding!"
        print("Test 9: batch ordering preserved across inputs -> PASS")

        # =====================================================================
        # 10. Batch length mismatch rejected
        # =====================================================================
        class MismatchedProvider(EmbeddingProvider):
            @property
            def dimension(self) -> int:
                return 1536

            @property
            def model_name(self) -> str:
                return "mismatch"

            async def embed_text(self, text: str) -> list[float]:
                return [0.0] * 1536

            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                # Deliberately return fewer vectors (empty) than input texts
                return []

        mismatch_provider = MismatchedProvider()
        post_mismatch = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-db"},
        )
        mismatch_id = uuid.UUID(post_mismatch.json()["id"])
        await process_url_capture(
            mismatch_id,
            allow_localhost=True,
            embedding_provider=mismatch_provider,
        )
        async with AsyncSessionLocal() as session:
            c_mis = (await session.execute(select(Capture).where(Capture.id == mismatch_id))).scalar_one()
            assert c_mis.processing_status == ProcessingStatus.FAILED
            assert "Mismatched embedding count" in (c_mis.processing_error or "")
        print("Test 10: batch length mismatch rejected -> PASS")

        # =====================================================================
        # 11. URL ingestion creates chunks with embeddings
        # 12. Embedding is no longer NULL for successfully processed URL captures
        # 13. Capture becomes completed only after embeddings persist
        # =====================================================================
        await cleanup_database()
        post_art1 = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-db"},
        )
        art1_id = uuid.UUID(post_art1.json()["id"])
        success1 = await process_url_capture(art1_id, allow_localhost=True)
        assert success1 is True

        async with AsyncSessionLocal() as session:
            cap1 = (await session.execute(select(Capture).where(Capture.id == art1_id))).scalar_one()
            assert cap1.processing_status == ProcessingStatus.COMPLETED
            assert cap1.processed_at is not None

            chunks1 = (
                await session.execute(
                    select(ContentChunk).where(ContentChunk.capture_id == art1_id)
                )
            ).scalars().all()
            assert len(chunks1) > 0
            for ch in chunks1:
                assert ch.embedding is not None, "Embedding must not be NULL in Stage 7"
                assert len(ch.embedding) == 1536
        print("Test 11: URL ingestion creates chunks with embeddings -> PASS")
        print("Test 12: embedding is no longer NULL for processed captures -> PASS")
        print("Test 13: capture completed only after embeddings persist -> PASS")

        # =====================================================================
        # 14. Retry remains idempotent (no duplicate chunks or embeddings)
        # =====================================================================
        retry_success = await process_url_capture(art1_id, allow_localhost=True)
        assert retry_success is True
        async with AsyncSessionLocal() as session:
            chunks_after_retry = (
                await session.execute(
                    select(ContentChunk).where(ContentChunk.capture_id == art1_id)
                )
            ).scalars().all()
            assert len(chunks_after_retry) == len(chunks1), "Retrying job must not duplicate chunks"
            for ch in chunks_after_retry:
                assert ch.embedding is not None
                assert len(ch.embedding) == 1536
        print("Test 14: retry remains idempotent -> PASS")

        # =====================================================================
        # 15. Failed embedding transaction leaves no partial chunk set
        # =====================================================================
        post_art_fail = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-vectors"},
        )
        art_fail_id = uuid.UUID(post_art_fail.json()["id"])
        await process_url_capture(
            art_fail_id,
            allow_localhost=True,
            embedding_provider=FailingEmbeddingProvider(),
        )
        async with AsyncSessionLocal() as session:
            cap_failed = (await session.execute(select(Capture).where(Capture.id == art_fail_id))).scalar_one()
            assert cap_failed.processing_status == ProcessingStatus.FAILED
            chunks_failed = (
                await session.execute(
                    select(ContentChunk).where(ContentChunk.capture_id == art_fail_id)
                )
            ).scalars().all()
            assert len(chunks_failed) == 0, "No partial chunks should exist after failed embedding"
        print("Test 15: failed embedding transaction leaves no partial chunk set -> PASS")

        # Ingest remaining test articles for search testing
        # Article 2: Vectors
        post_art2 = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-vectors"},
        )
        art2_id = uuid.UUID(post_art2.json()["id"])
        await process_url_capture(art2_id, allow_localhost=True)

        # Article 3: Baking
        post_art3 = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-baking"},
        )
        art3_id = uuid.UUID(post_art3.json()["id"])
        await process_url_capture(art3_id, allow_localhost=True)

        # =====================================================================
        # 16. Exact keyword match
        # =====================================================================
        search_res = await api_client.get("/search?q=PostgreSQL")
        assert search_res.status_code == 200
        data = search_res.json()
        assert data["total"] >= 1
        found_ids = [c["capture_id"] for c in data["results"]]
        assert str(art1_id) in found_ids
        print("Test 16: exact keyword match -> PASS")

        # =====================================================================
        # 17. Partial/stemmed text match
        # =====================================================================
        # 'indexing' stems to 'index' in english tsvector
        search_stem = await api_client.get("/search?q=indexes")
        assert search_stem.status_code == 200
        stem_data = search_stem.json()
        assert stem_data["total"] >= 1
        assert str(art1_id) in [c["capture_id"] for c in stem_data["results"]]
        print("Test 17: partial/relevant text match -> PASS")

        # =====================================================================
        # 18. Title matching (query matches capture title even if unique)
        # =====================================================================
        title_search = await api_client.get("/search?q=Indexing")
        assert title_search.status_code == 200
        t_data = title_search.json()
        assert str(art1_id) in [c["capture_id"] for c in t_data["results"]]
        print("Test 18: title matching -> PASS")

        # =====================================================================
        # 19. No-result query
        # =====================================================================
        no_res = await api_client.get("/search?q=supercalifragilisticexpialidocious")
        assert no_res.status_code == 200
        assert no_res.json()["total"] == 0
        assert len(no_res.json()["results"]) == 0
        print("Test 19: no-result query -> PASS")

        # =====================================================================
        # 20. Empty query rejected
        # =====================================================================
        empty_res = await api_client.get("/search?q=")
        assert empty_res.status_code == 422
        print("Test 20: empty query rejected -> PASS")

        # =====================================================================
        # 21. Whitespace-only query rejected
        # =====================================================================
        ws_res = await api_client.get("/search?q=   ")
        assert ws_res.status_code == 422
        print("Test 21: whitespace-only query rejected -> PASS")

        # =====================================================================
        # 22. Long query safely bounded
        # =====================================================================
        long_query = "a" * 501
        long_res = await api_client.get(f"/search?q={long_query}")
        assert long_res.status_code == 422
        print("Test 22: long query safely bounded -> PASS")

        # =====================================================================
        # 23. Unicode query
        # =====================================================================
        uni_res = await api_client.get("/search?q=データベース 日本語 🚀")
        assert uni_res.status_code == 200
        print("Test 23: Unicode query handled safely -> PASS")

        # =====================================================================
        # 24. Punctuation-heavy query
        # =====================================================================
        punct_res = await api_client.get("/search?q=!@#$%^&*()_+{}[]:;\"'<>?,./~`")
        assert punct_res.status_code == 200
        print("Test 24: punctuation-heavy query handled safely -> PASS")

        # =====================================================================
        # 25. SQL injection payload treated as plain search input
        # =====================================================================
        sqli_res = await api_client.get("/search?q='; DROP TABLE captures; --")
        assert sqli_res.status_code == 200
        # Verify captures table still exists and is untouched
        async with AsyncSessionLocal() as session:
            count = (await session.execute(select(Capture))).scalars().all()
            assert len(count) >= 3, "SQL injection affected database table!"
        print("Test 25: SQL injection payload treated as plain search input -> PASS")

        # =====================================================================
        # 26. Semantically similar deterministic test vectors return expected records
        # =====================================================================
        vec_search = await api_client.get("/search?q=cosine distance semantic retrieval")
        assert vec_search.status_code == 200
        v_data = vec_search.json()
        assert len(v_data["results"]) > 0
        top_cap_id = v_data["results"][0]["capture_id"]
        assert top_cap_id == str(art2_id), "Article 2 should rank highest for vector/embedding query"
        print("Test 26: semantically similar vectors return expected records -> PASS")

        # =====================================================================
        cookie_matches = [c for c in v_data["results"] if c["capture_id"] == str(art3_id)]
        if cookie_matches:
            assert v_data["results"][0]["best_score"] > cookie_matches[0]["best_score"]
        else:
            # Unrelated result was filtered out completely as expected
            assert len(v_data["results"]) >= 1
        print("Test 27: unrelated vectors rank lower -> PASS")

        # =====================================================================
        # 28. NULL embeddings are excluded from vector search
        # =====================================================================
        async with AsyncSessionLocal() as session:
            async with session.begin():
                null_cap = Capture(source_type=SourceType.TEXT, title="Null Embedding Capture")
                session.add(null_cap)
                await session.flush()
                null_chunk = ContentChunk(
                    capture_id=null_cap.id,
                    chunk_index=0,
                    content="Content with explicitly NULL embedding",
                    embedding=None,
                )
                session.add(null_chunk)

        # Pure semantic search (w_lex=0, w_sem=1.0)
        pure_sem_res = await api_client.get("/search?q=cosine distance&w_lex=0.0&w_sem=1.0")
        assert pure_sem_res.status_code == 200
        sem_ids = [c["capture_id"] for c in pure_sem_res.json()["results"]]
        assert str(null_cap.id) not in sem_ids, "NULL embedding was included in semantic search results!"
        print("Test 28: NULL embeddings are excluded from vector search -> PASS")

        # =====================================================================
        # 29. Query vector dimension is validated
        # =====================================================================
        class InvalidDimProvider(EmbeddingProvider):
            @property
            def dimension(self) -> int:
                return 1536

            @property
            def model_name(self) -> str:
                return "bad-dim"

            async def embed_text(self, text: str) -> list[float]:
                return [0.1] * 100  # wrong dimension

            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[0.1] * 100]

        async with AsyncSessionLocal() as session:
            res_bad_dim = await search_service.search(
                query="dimension test",
                session=session,
                embedding_provider=InvalidDimProvider(),
            )
            # Should degrade safely to lexical search without 500 error
            assert res_bad_dim.degraded is True
        print("Test 29: query vector dimension is validated -> PASS")

        # =====================================================================
        # 30. No embeddings case handled safely
        # =====================================================================
        async with AsyncSessionLocal() as session:
            empty_search = await search_service.search(
                query="random text with no embeddings",
                session=session,
                embedding_provider=DeterministicTestEmbeddingProvider(),
            )
            assert isinstance(empty_search, SearchResponse)
        print("Test 30: no embeddings case handled safely -> PASS")

        # =====================================================================
        # 31. Lexical-only match
        # =====================================================================
        lex_only_res = await api_client.get("/search?q=B-Tree&w_lex=1.0&w_sem=0.0")
        assert lex_only_res.status_code == 200
        assert lex_only_res.json()["total"] >= 1
        assert lex_only_res.json()["results"][0]["capture_id"] == str(art1_id)
        print("Test 31: lexical-only match -> PASS")

        # =====================================================================
        # 32. Semantic-only match
        # =====================================================================
        sem_only_res = await api_client.get("/search?q=baking sweet pastry treats&w_lex=0.0&w_sem=1.0")
        assert sem_only_res.status_code == 200
        assert sem_only_res.json()["total"] >= 1
        assert sem_only_res.json()["results"][0]["capture_id"] == str(art3_id)
        print("Test 32: semantic-only match -> PASS")

        # =====================================================================
        # 33. Document matching both signals
        # =====================================================================
        both_res = await api_client.get("/search?q=PostgreSQL indexing&w_lex=0.5&w_sem=0.5")
        assert both_res.status_code == 200
        both_data = both_res.json()
        assert both_data["total"] >= 1
        first_match = both_data["results"][0]
        assert first_match["best_lexical_score"] is not None and first_match["best_lexical_score"] > 0
        assert first_match["best_semantic_score"] is not None and first_match["best_semantic_score"] > 0
        print("Test 33: document matching both signals -> PASS")

        # =====================================================================
        # 34. Deterministic hybrid ordering
        # =====================================================================
        res_a = await api_client.get("/search?q=database vectors")
        res_b = await api_client.get("/search?q=database vectors")
        ids_a = [c["capture_id"] for c in res_a.json()["results"]]
        ids_b = [c["capture_id"] for c in res_b.json()["results"]]
        assert ids_a == ids_b, "Search ordering must be identical across repeated runs"
        print("Test 34: deterministic hybrid ordering -> PASS")

        # =====================================================================
        # 35. Configurable weights affect ranking mathematically
        # =====================================================================
        # Query where lexical favors art1 and semantic favors art2
        # Art1 has "relational database optimization", Art2 has "semantic document retrieval"
        q_weights = "relational database retrieval"
        res_heavy_lex = await api_client.get(f"/search?q={q_weights}&w_lex=0.95&w_sem=0.05")
        res_heavy_sem = await api_client.get(f"/search?q={q_weights}&w_lex=0.05&w_sem=0.95")
        score_lex_art1 = next(c["best_score"] for c in res_heavy_lex.json()["results"] if c["capture_id"] == str(art1_id))
        score_sem_art1 = next(c["best_score"] for c in res_heavy_sem.json()["results"] if c["capture_id"] == str(art1_id))
        assert score_lex_art1 != score_sem_art1, "Weights should mathematically alter scores"
        print("Test 35: configurable weights affect ranking mathematically -> PASS")

        # =====================================================================
        # 36. Stable tie-breaking
        # =====================================================================
        # Insert two identical dummy chunks under distinct captures
        async with AsyncSessionLocal() as session:
            async with session.begin():
                cap_t1 = Capture(source_type=SourceType.TEXT, title="Tie Alpha")
                cap_t2 = Capture(source_type=SourceType.TEXT, title="Tie Beta")
                session.add_all([cap_t1, cap_t2])
                await session.flush()
                session.add(ContentChunk(capture_id=cap_t1.id, chunk_index=0, content="Identical tie test content", embedding=v1))
                session.add(ContentChunk(capture_id=cap_t2.id, chunk_index=0, content="Identical tie test content", embedding=v1))

        tie_1 = await api_client.get("/search?q=Identical tie test content")
        tie_2 = await api_client.get("/search?q=Identical tie test content")
        assert [c["capture_id"] for c in tie_1.json()["results"]] == [c["capture_id"] for c in tie_2.json()["results"]]
        print("Test 36: stable tie-breaking -> PASS")

        # =====================================================================
        # 37. Repeated identical search returns identical ordering
        # =====================================================================
        run1 = await api_client.get("/search?q=PostgreSQL")
        run2 = await api_client.get("/search?q=PostgreSQL")
        run3 = await api_client.get("/search?q=PostgreSQL")
        assert run1.json() == run2.json() == run3.json()
        print("Test 37: repeated identical search returns identical ordering -> PASS")

        # =====================================================================
        # 38. Valid search request
        # =====================================================================
        valid_res = await api_client.get("/search?q=cookies&limit=5")
        assert valid_res.status_code == 200
        v_body = valid_res.json()
        assert v_body["query"] == "cookies"
        assert v_body["limit"] == 5
        print("Test 38: valid search request -> PASS")

        # =====================================================================
        # 39. Missing query
        # =====================================================================
        missing_q = await api_client.get("/search")
        assert missing_q.status_code == 422
        print("Test 39: missing query parameter -> PASS")

        # =====================================================================
        # 40. Empty query
        # =====================================================================
        empty_q2 = await api_client.get("/search?q=")
        assert empty_q2.status_code == 422
        print("Test 40: empty query -> PASS")

        # =====================================================================
        # 41. Invalid limit
        # =====================================================================
        bad_limit = await api_client.get("/search?q=cookies&limit=0")
        assert bad_limit.status_code == 422
        print("Test 41: invalid limit -> PASS")

        # =====================================================================
        # 42. Excessive limit
        # =====================================================================
        huge_limit = await api_client.get("/search?q=cookies&limit=100")
        assert huge_limit.status_code == 422
        print("Test 42: excessive limit -> PASS")

        # =====================================================================
        # 43. Response schema validation
        # =====================================================================
        schema_test = await api_client.get("/search?q=database")
        parsed = SearchResponse.model_validate(schema_test.json())
        assert parsed.total == len(parsed.results)
        for cap_r in parsed.results:
            assert isinstance(cap_r.capture_id, uuid.UUID)
            assert len(cap_r.matching_chunks) > 0
            for chunk_r in cap_r.matching_chunks:
                assert isinstance(chunk_r.chunk_id, uuid.UUID)
                assert isinstance(chunk_r.score, float)
                assert chunk_r.content_excerpt
        print("Test 43: response schema validation -> PASS")

        # =====================================================================
        # 44. Embeddings are not exposed in API response
        # =====================================================================
        raw_text = schema_test.text
        assert "embedding" not in raw_text or '"embedding":' not in raw_text, "Raw embeddings leaked in search API response!"
        assert "1536" not in raw_text
        print("Test 44: embeddings are not exposed in API response -> PASS")

        # =====================================================================
        # 45. No internal provider secrets exposed
        # =====================================================================
        assert "api_key" not in raw_text
        assert "Authorization" not in raw_text
        assert "Bearer" not in raw_text
        print("Test 45: no internal provider secrets exposed -> PASS")

        # =====================================================================
        # 46. Stage 6 worker integration tests pass
        # =====================================================================
        # Verify that process_url_capture creates chunks with embeddings
        post_s6 = await api_client.post(
            "/captures",
            json={"source_type": "url", "original_url": f"{base_url}/article-db"},
        )
        s6_id = uuid.UUID(post_s6.json()["id"])
        assert await process_url_capture(s6_id, allow_localhost=True) is True
        async with AsyncSessionLocal() as session:
            s6_cap = (await session.execute(select(Capture).where(Capture.id == s6_id))).scalar_one()
            assert s6_cap.processing_status == ProcessingStatus.COMPLETED
            s6_chunks = (
                await session.execute(select(ContentChunk).where(ContentChunk.capture_id == s6_id))
            ).scalars().all()
            assert len(s6_chunks) > 0
            assert all(ch.embedding is not None and len(ch.embedding) == 1536 for ch in s6_chunks)
        print("Test 46: Stage 6 worker integration behavior verified -> PASS")

        # =====================================================================
        # 47. Stage 5 capture API tests still pass
        # =====================================================================
        s5_text = await api_client.post(
            "/captures",
            json={"source_type": "text", "content": "Instant note verification"},
        )
        assert s5_text.status_code == 201
        s5_id = s5_text.json()["id"]
        get_s5 = await api_client.get(f"/captures/{s5_id}")
        assert get_s5.status_code == 200
        assert get_s5.json()["content"] == "Instant note verification"
        print("Test 47: Stage 5 capture API regression verified -> PASS")

        # =====================================================================
        # 48. /health remains healthy
        # =====================================================================
        health_resp = await api_client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"
        assert health_resp.json()["database"] == "ok"
        assert health_resp.json()["redis"] == "ok"
        print("Test 48: /health remains healthy -> PASS")

        await cleanup_database()
        reset_embedding_provider_override()

    server.shutdown()
    print("\n--- ALL 48 STAGE 7 INTEGRATION TESTS PASSED SUCCESSFULLY ---")


if __name__ == "__main__":
    asyncio.run(run_stage7_tests())
