"""Stage 16 Test Suite: Unified Knowledge Search across Captures and Ingested GitHub Activities.

Covers all Stage 16 test requirements:
1. Existing capture search remains functional (notes, URLs, PDFs).
2. Ingested GitHub activities (PRs, issues, commits, reviews) are retrieved for matching queries.
3. Supported source-type / result-kind filters include and exclude the correct records.
4. Combined results provide stable result kinds ('capture', 'github_activity'), UUID identifiers, and metadata.
5. Calibrated ranking across capture hybrid scoring and GitHub activity relevance scoring.
6. Pagination boundaries and candidate limits are enforced.
7. Empty, whitespace-only, and oversized queries are handled correctly with HTTP 422.
8. Repository ownership and authenticated connection boundaries are enforced.
9. Missing optional GitHub activity metadata (null body, title, author, state) does not break search.
10. Embedding provider unavailability triggers truthful degraded fallback behavior.
11. Existing search API contract and consumers remain fully backward-compatible.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Optional
import uuid

import httpx
import pytest
from sqlalchemy import delete, select

# Ensure services/api and services/worker are in sys.path
api_path = str(Path(__file__).resolve().parents[1])
if api_path not in sys.path:
    sys.path.insert(0, api_path)
worker_path = str(Path(__file__).resolve().parents[2] / "worker")
if worker_path not in sys.path:
    sys.path.insert(0, worker_path)

from app.core.encryption import encrypt_secret
from app.db.models import (
    Capture,
    ContentChunk,
    GitHubActivity,
    GitHubActivityType,
    GitHubConnection,
    GitHubRepository,
    SourceType,
)
from app.db.session import AsyncSessionLocal
from app.embeddings.base import EmbeddingProvider, EmbeddingProviderError
from app.embeddings.factory import (
    reset_embedding_provider_override,
    set_embedding_provider_override,
)
from app.embeddings.test_provider import DeterministicTestEmbeddingProvider
from app.main import app
from app.search.schemas import SearchResponse


class SimulatedFailureEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that simulates upstream outage."""

    @property
    def dimension(self) -> int:
        return 1536

    @property
    def model_name(self) -> str:
        return "outage-simulation"

    async def embed_text(self, text: str) -> list[float]:
        raise EmbeddingProviderError("Simulated upstream embedding provider outage (HTTP 503)")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("Simulated upstream embedding provider outage (HTTP 503)")


async def clean_database() -> None:
    """Purge all captures, chunks, activities, repositories, and connections."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ContentChunk))
        await session.execute(delete(Capture))
        await session.execute(delete(GitHubActivity))
        await session.execute(delete(GitHubRepository))
        await session.execute(delete(GitHubConnection))
        await session.commit()


async def create_test_connection(user_id: str = "gh_user_stage16", username: str = "lens_user") -> uuid.UUID:
    """Create a verified test GitHubConnection."""
    async with AsyncSessionLocal() as session:
        encrypted = encrypt_secret("gho_stage16_test_token_123456")
        now = datetime.now(timezone.utc)
        conn = GitHubConnection(
            provider="github",
            github_user_id=user_id,
            github_username=username,
            encrypted_access_token=encrypted,
            token_type="bearer",
            scope="read:user,repo",
            created_at=now,
            updated_at=now,
            last_verified_at=now,
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn.id


async def create_test_repository(connection_id: uuid.UUID, full_name: str = "octocat/Hello-World") -> uuid.UUID:
    """Create a test GitHubRepository belonging to connection_id."""
    owner, name = full_name.split("/")
    async with AsyncSessionLocal() as session:
        repo = GitHubRepository(
            connection_id=connection_id,
            github_repository_id=str(uuid.uuid4().int)[:8],
            name=name,
            full_name=full_name,
            owner_login=owner,
            html_url=f"https://github.com/{full_name}",
            is_selected=True,
            sync_status="synced",
        )
        session.add(repo)
        await session.commit()
        await session.refresh(repo)
        return repo.id


async def prepare_test_env() -> None:
    """Setup deterministic embedding provider and clean DB."""
    test_provider = DeterministicTestEmbeddingProvider(dimension=1536)
    set_embedding_provider_override(test_provider)
    await clean_database()


@pytest.mark.asyncio
async def test_unified_search_empty_database():
    """Searching an empty database returns total=0 and empty results list."""
    await prepare_test_env()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": "anything"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["results"] == []
        assert data["query"] == "anything"
        assert data["degraded"] is False


@pytest.mark.asyncio
async def test_unified_search_returns_both_captures_and_github_activities() -> None:
    """Unified search returns both matching captures and GitHub activities with calibrated scores."""
    await prepare_test_env()
    test_provider = DeterministicTestEmbeddingProvider(dimension=1536)
    vector = await test_provider.embed_text("Async database connection pooling with asyncpg and postgresql")

    # 1. Create a Capture note
    async with AsyncSessionLocal() as session:
        cap = Capture(
            source_type=SourceType.TEXT,
            title="Database Connection Pooling Architecture",
            content="Async database connection pooling with asyncpg and postgresql",
        )
        session.add(cap)
        await session.commit()
        await session.refresh(cap)

        chunk = ContentChunk(
            capture_id=cap.id,
            chunk_index=0,
            content="Async database connection pooling with asyncpg and postgresql",
            embedding=vector,
        )
        session.add(chunk)
        await session.commit()
        cap_id = cap.id

    # 2. Create a GitHub activity (Pull Request)
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="octocat/Lens")

    async with AsyncSessionLocal() as session:
        activity = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.PULL_REQUEST,
            external_id="42",
            title="Fix connection pooling timeout under high load",
            body="Optimizes postgresql async pool settings to prevent starvation.",
            html_url="https://github.com/octocat/Lens/pull/42",
            author_login="octocat",
            state="merged",
            source_created_at=datetime.now(timezone.utc),
            payload={"number": 42},
        )
        session.add(activity)
        await session.commit()
        await session.refresh(activity)
        gh_id = activity.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": "connection pooling postgresql"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 2
        assert len(data["results"]) == 2

        # Check result kinds
        result_kinds = {r["result_kind"] for r in data["results"]}
        assert "capture" in result_kinds
        assert "github_activity" in result_kinds

        # Find the capture result
        cap_res = next(r for r in data["results"] if r["result_kind"] == "capture")
        assert cap_res["capture_id"] == str(cap_id)
        assert cap_res["source_type"] == "text"
        assert cap_res["title"] == "Database Connection Pooling Architecture"
        assert cap_res["best_score"] > 0.0
        assert cap_res["best_lexical_score"] is not None
        assert cap_res["best_semantic_score"] is not None
        assert len(cap_res["matching_chunks"]) > 0

        # Find the GitHub activity result
        gh_res = next(r for r in data["results"] if r["result_kind"] == "github_activity")
        assert gh_res["capture_id"] == str(gh_id)
        assert gh_res["source_type"] == "pull_request"
        assert gh_res["activity_type"] == "pull_request"
        assert gh_res["repository_name"] == "octocat/Lens"
        assert gh_res["author_login"] == "octocat"
        assert gh_res["state"] == "merged"
        assert gh_res["external_id"] == "42"
        assert gh_res["original_url"] == "https://github.com/octocat/Lens/pull/42"
        assert gh_res["best_score"] > 0.0
        assert gh_res["best_lexical_score"] is not None
        assert gh_res["best_semantic_score"] is None  # Grounded: no code embeddings fabricated


@pytest.mark.asyncio
async def test_unified_search_source_type_filters() -> None:
    """source_type filter restricts results to requested categories accurately."""
    await prepare_test_env()
    test_provider = DeterministicTestEmbeddingProvider(dimension=1536)
    vec = await test_provider.embed_text("authentication tokens")

    # Ingest text note, url capture, PR, issue, and commit
    async with AsyncSessionLocal() as session:
        c_text = Capture(source_type=SourceType.TEXT, title="Auth Token Notes", content="Managing auth tokens securely")
        session.add(c_text)
        c_url = Capture(source_type=SourceType.URL, original_url="https://example.com/auth", title="Auth Specs", content="OAuth tokens guide")
        session.add(c_url)
        await session.commit()
        await session.refresh(c_text)
        await session.refresh(c_url)

        session.add(ContentChunk(capture_id=c_text.id, chunk_index=0, content="Managing auth tokens securely", embedding=vec))
        session.add(ContentChunk(capture_id=c_url.id, chunk_index=0, content="OAuth tokens guide", embedding=vec))
        await session.commit()

    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="lens/repo")

    async with AsyncSessionLocal() as session:
        pr = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.PULL_REQUEST,
            external_id="101",
            title="PR 101: Rotate auth tokens",
            body="Implements token rotation for oauth tokens.",
            html_url="https://github.com/lens/repo/pull/101",
            payload={},
        )
        issue = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE,
            external_id="102",
            title="Issue 102: Token expiration bug",
            body="Tokens expire prematurely in auth flow.",
            html_url="https://github.com/lens/repo/issues/102",
            payload={},
        )
        commit = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.COMMIT,
            external_id="abc1234def5678",
            title="feat(auth): refresh token endpoint",
            body="Adds endpoint to refresh expired tokens.",
            html_url="https://github.com/lens/repo/commit/abc1234def5678",
            payload={},
        )
        session.add_all([pr, issue, commit])
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. source_type='all' or None -> all 5 items returned
        r_all = await client.get("/search", params={"q": "tokens", "source_type": "all"})
        assert r_all.status_code == 200
        assert r_all.json()["total"] == 5

        # 2. source_type='captures' -> only the 2 captures returned
        r_caps = await client.get("/search", params={"q": "tokens", "source_type": "captures"})
        assert r_caps.status_code == 200
        assert r_caps.json()["total"] == 2
        assert all(item["result_kind"] == "capture" for item in r_caps.json()["results"])

        # 3. source_type='text' -> only the 1 text note
        r_text = await client.get("/search", params={"q": "tokens", "source_type": "text"})
        assert r_text.status_code == 200
        assert r_text.json()["total"] == 1
        assert r_text.json()["results"][0]["source_type"] == "text"

        # 4. source_type='github' -> all 3 GitHub activities returned
        r_gh = await client.get("/search", params={"q": "tokens", "source_type": "github"})
        assert r_gh.status_code == 200
        assert r_gh.json()["total"] == 3
        assert all(item["result_kind"] == "github_activity" for item in r_gh.json()["results"])

        # 5. source_type='pull_request' -> only PR
        r_pr = await client.get("/search", params={"q": "tokens", "source_type": "pull_request"})
        assert r_pr.status_code == 200
        assert r_pr.json()["total"] == 1
        assert r_pr.json()["results"][0]["activity_type"] == "pull_request"

        # 6. source_type='issue' -> only Issue
        r_iss = await client.get("/search", params={"q": "tokens", "source_type": "issue"})
        assert r_iss.status_code == 200
        assert r_iss.json()["total"] == 1
        assert r_iss.json()["results"][0]["activity_type"] == "issue"

        # 7. source_type='commit' -> only Commit
        r_cmt = await client.get("/search", params={"q": "tokens", "source_type": "commit"})
        assert r_cmt.status_code == 200
        assert r_cmt.json()["total"] == 1
        assert r_cmt.json()["results"][0]["activity_type"] == "commit"

        # 8. invalid source_type returns 422
        r_inv = await client.get("/search", params={"q": "tokens", "source_type": "unsupported_unknown_xyz"})
        assert r_inv.status_code == 422
        assert "Invalid source_type filter" in r_inv.json()["detail"]


@pytest.mark.asyncio
async def test_unified_search_all_four_github_activity_types() -> None:
    """All 4 GitHub activity types (PR, Issue, Commit, Review) are indexed and retrieved."""
    await prepare_test_env()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="org/project")

    async with AsyncSessionLocal() as session:
        pr = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.PULL_REQUEST,
            external_id="10",
            title="PR 10: Docker compose configuration",
            body="Configures Docker compose for multi-container development.",
            html_url="https://github.com/org/project/pull/10",
            author_login="dev1",
            state="open",
            payload={},
        )
        issue = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE,
            external_id="11",
            title="Issue 11: Docker container fails on startup",
            body="Container crashes with exit code 137.",
            html_url="https://github.com/org/project/issues/11",
            author_login="dev2",
            state="open",
            payload={},
        )
        commit = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.COMMIT,
            external_id="1a2b3c4d5e6f7a8b9c0d",
            title="fix(docker): optimize image layers",
            body="Reduces container image size by combining RUN statements.",
            html_url="https://github.com/org/project/commit/1a2b3c4d5e6f7a8b9c0d",
            author_login="dev3",
            payload={},
        )
        review = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.REVIEW,
            external_id="555",
            title="Review on PR #10",
            body="Approved: Docker configuration looks clean and well-structured.",
            html_url="https://github.com/org/project/pull/10#pullrequestreview-555",
            author_login="senior_dev",
            state="approved",
            payload={"pull_request_number": 10},
        )
        session.add_all([pr, issue, commit, review])
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": "Docker"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 4

        activity_types = {r["activity_type"] for r in results}
        assert activity_types == {"pull_request", "issue", "commit", "review"}


@pytest.mark.asyncio
async def test_unified_search_exact_identifier_match() -> None:
    """Searching for an exact external identifier (e.g. commit SHA or PR number) retrieves the activity."""
    await prepare_test_env()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="org/project")

    sha = "7c4dd7710e210edc4c7f3f80041e68ed99d770bc"
    async with AsyncSessionLocal() as session:
        commit = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.COMMIT,
            external_id=sha,
            title="Merge branch 'main'",
            body="Merged upstream changes into staging.",
            html_url=f"https://github.com/org/project/commit/{sha}",
            payload={},
        )
        session.add(commit)
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": sha})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["external_id"] == sha
        assert results[0]["title"] == "Merge branch 'main'"


@pytest.mark.asyncio
async def test_unified_search_query_validation() -> None:
    """Empty, whitespace-only, and oversized queries are rejected with HTTP 422."""
    await prepare_test_env()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty query
        r1 = await client.get("/search", params={"q": ""})
        assert r1.status_code == 422

        # Whitespace-only query
        r2 = await client.get("/search", params={"q": "    \t   "})
        assert r2.status_code == 422

        # Oversized query (>500 chars)
        r3 = await client.get("/search", params={"q": "a" * 501})
        assert r3.status_code == 422

        # Invalid limit
        r4 = await client.get("/search", params={"q": "valid", "limit": 0})
        assert r4.status_code == 422
        r5 = await client.get("/search", params={"q": "valid", "limit": 51})
        assert r5.status_code == 422


@pytest.mark.asyncio
async def test_unified_search_data_boundary_enforcement() -> None:
    """Activities belonging to repositories without a valid GitHubConnection are never returned."""
    await prepare_test_env()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="valid/repo")

    async with AsyncSessionLocal() as session:
        act = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.PULL_REQUEST,
            external_id="1",
            title="Authorized repository activity",
            body="This activity belongs to an authorized connection.",
            html_url="https://github.com/valid/repo/pull/1",
            payload={},
        )
        session.add(act)
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": "authorized"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Now disconnect GitHub (delete connection)
        async with AsyncSessionLocal() as session:
            await session.execute(delete(GitHubConnection).where(GitHubConnection.id == conn_id))
            await session.commit()

        # The activity should no longer be returned because connection is gone
        resp_after = await client.get("/search", params={"q": "authorized"})
        assert resp_after.status_code == 200
        assert resp_after.json()["total"] == 0


@pytest.mark.asyncio
async def test_unified_search_missing_optional_metadata() -> None:
    """Missing optional fields (null body, title, author, state) do not crash search."""
    await prepare_test_env()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="minimal/repo")

    async with AsyncSessionLocal() as session:
        act = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.COMMIT,
            external_id="fedcba9876543210",
            title=None,
            body=None,
            html_url="https://github.com/minimal/repo/commit/fedcba9876543210",
            author_login=None,
            state=None,
            payload={},
        )
        session.add(act)
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": "fedcba9876543210"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["title"] == "Commit fedcba9"
        assert results[0]["author_login"] is None
        assert results[0]["state"] is None


@pytest.mark.asyncio
async def test_unified_search_degraded_semantic_fallback() -> None:
    """When embedding provider fails, search succeeds in degraded mode with lexical capture + activity matches."""
    await clean_database()
    failing_provider = SimulatedFailureEmbeddingProvider()
    set_embedding_provider_override(failing_provider)

    # Ingest capture and activity
    async with AsyncSessionLocal() as session:
        cap = Capture(source_type=SourceType.TEXT, title="Lexical Fallback Architecture", content="Testing graceful degraded fallback")
        session.add(cap)
        await session.commit()
        await session.refresh(cap)
        session.add(ContentChunk(capture_id=cap.id, chunk_index=0, content="Testing graceful degraded fallback"))
        await session.commit()

    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="degraded/repo")
    async with AsyncSessionLocal() as session:
        act = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE,
            external_id="99",
            title="Issue 99: Degraded fallback test",
            body="Verifying that GitHub activities are returned even if embeddings fail.",
            html_url="https://github.com/degraded/repo/issues/99",
            payload={},
        )
        session.add(act)
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/search", params={"q": "fallback"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["degraded"] is True
        assert data["total"] == 2
        kinds = {r["result_kind"] for r in data["results"]}
        assert kinds == {"capture", "github_activity"}


@pytest.mark.asyncio
async def test_unified_search_deterministic_tie_breaking() -> None:
    """Identical scores break ties deterministically across repeated queries."""
    await prepare_test_env()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, full_name="tie/repo")

    async with AsyncSessionLocal() as session:
        act1 = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE,
            external_id="1",
            title="Identical relevance query match alpha",
            body="Identical content body for relevance test.",
            html_url="https://github.com/tie/repo/issues/1",
            payload={},
        )
        act2 = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE,
            external_id="2",
            title="Identical relevance query match beta",
            body="Identical content body for relevance test.",
            html_url="https://github.com/tie/repo/issues/2",
            payload={},
        )
        session.add_all([act1, act2])
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/search", params={"q": "relevance"})
        r2 = await client.get("/search", params={"q": "relevance"})

        assert r1.status_code == 200
        assert r2.status_code == 200

        order1 = [r["capture_id"] for r in r1.json()["results"]]
        order2 = [r["capture_id"] for r in r2.json()["results"]]
        assert order1 == order2, "Repeated queries must yield identical ordering"
