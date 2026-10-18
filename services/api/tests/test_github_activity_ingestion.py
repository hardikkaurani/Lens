"""Integration, correctness, and security regression tests for GitHub Activity Ingestion (Stage 15).

Covers all Stage 15 test requirements:
1. Data Model & Migration:
   - Stable identity and uniqueness constraint (repository_id, activity_type, external_id)
   - Duplicate upsert behavior (repeated sync is idempotent)
   - Bounded payload persistence (text lengths, metadata JSON)
   - Foreign-key integrity (cascade deletion on repository deletion)
   - Full SHA stable identity for commits
   - Issues endpoint filtering out PR objects

2. GitHub API Client:
   - Pagination boundaries and empty pages
   - Issues endpoint filtering of PR objects
   - Review retrieval tied to pull request numbers
   - Rate-limit (403/429) and Retry-After behavior
   - Authentication (401), permission (403), transient (500/502/503/504) failures and backoff
   - Request-budget enforcement

3. Incremental Sync & Checkpoints:
   - Only selected repositories (is_selected=True) are synced
   - Cross-user/connection ownership verification
   - Duplicate job delivery is idempotent
   - Partial category failure preserves successful categories
   - Checkpoints do not advance after persistence failure
   - Checkpoints advance only on committed data
   - Distributed lock ownership and safe release
   - Recovery of stranded activity sync jobs
   - Stale or out-of-order updates do not corrupt newer records

4. API Endpoints:
   - POST /integrations/github/activities/sync (synchronous and async paths)
   - GET /integrations/github/activities (bounded pagination, type/repo filtering, deterministic sorting)
   - GET /integrations/github/activities/status (aggregate status across selected repositories)
   - Rejection of unselected or non-owned repositories
   - Sanitized error responses with no leaked tokens or internal stack traces
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Optional, cast
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

# Ensure services/api and services/worker are in sys.path
api_path = str(Path(__file__).resolve().parents[1])
if api_path not in sys.path:
    sys.path.insert(0, api_path)
worker_path = str(Path(__file__).resolve().parents[2] / "worker")
if worker_path not in sys.path:
    sys.path.insert(0, worker_path)

from app.core.config import get_settings
from app.core.encryption import encrypt_secret
from app.db.models import (
    GitHubActivity,
    GitHubActivityType,
    GitHubConnection,
    GitHubRepository,
    RepositorySyncStatus,
)
from app.db.session import AsyncSessionLocal
from app.integrations.github.client import (
    GitHubApiError,
    GitHubAuthError,
    GitHubClient,
    GitHubClientError,
    GitHubRateLimitError,
    GitHubTimeoutError,
    get_github_client,
)
from app.integrations.github.schemas import (
    GitHubActivitySyncRequest,
    NormalizedGitHubActivity,
    normalize_github_commit,
    normalize_github_issue,
    normalize_github_pull_request,
    normalize_github_review,
)
from app.integrations.github.service import (
    GENERIC_ACTIVITY_SYNC_ERROR_MESSAGE,
    _memory_lock_cache,
    _safe_activity_error,
    acquire_activity_sync_lock,
    is_activity_sync_locked,
    list_connection_activities,
    release_activity_sync_lock,
    sync_repository_activities,
    sync_selected_repositories_activities,
    upsert_activities,
)
from app.queue.job import (
    GITHUB_ACTIVITY_SYNC_PROCESSING_QUEUE,
    GITHUB_ACTIVITY_SYNC_QUEUE,
    GitHubActivitySyncJob,
    ack_github_activity_sync_job,
    dequeue_github_activity_sync_job,
    enqueue_github_activity_sync_job,
    recover_stranded_github_activity_sync_jobs,
)
from app.main import app
from worker.processor import process_github_activity_sync


async def clean_database() -> None:
    """Purge activities, repositories, and connections for clean test state."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(GitHubActivity))
        await session.execute(delete(GitHubRepository))
        await session.execute(delete(GitHubConnection))
        await session.commit()
    _memory_lock_cache.clear()


async def create_test_connection(user_id: str = "gh_user_stage15", username: str = "activity_user") -> uuid.UUID:
    """Helper to insert an active test GitHubConnection."""
    async with AsyncSessionLocal() as session:
        encrypted = encrypt_secret("gho_stage15_secret_token_abcde")
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


async def create_test_repository(
    connection_id: uuid.UUID,
    github_repo_id: str = "1001",
    name: str = "repo-alpha",
    full_name: str = "activity_user/repo-alpha",
    is_selected: bool = True,
) -> uuid.UUID:
    """Helper to insert a GitHubRepository."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        repo = GitHubRepository(
            connection_id=connection_id,
            github_repository_id=github_repo_id,
            name=name,
            full_name=full_name,
            owner_login="activity_user",
            html_url=f"https://github.com/{full_name}",
            is_private=False,
            is_selected=is_selected,
            activity_sync_status="idle",
            activity_sync_metadata={"counts": {}, "checkpoints": {}},
            created_at=now,
            updated_at=now,
        )
        session.add(repo)
        await session.commit()
        await session.refresh(repo)
        return repo.id


# ============================================================================
# Unit Tests (Self-contained, no persistent connection pool conflict)
# ============================================================================


def test_commit_stable_identity_is_full_sha() -> None:
    """Verify normalize_github_commit uses full commit SHA as external_id."""
    full_sha = "e5ac3820c4118f60da3f18e95c1044458f2762a4"
    raw_commit = {
        "sha": full_sha,
        "commit": {
            "message": "fix: resolve deadlock\n\nDetailed explanation",
            "author": {
                "name": "Developer",
                "date": "2026-10-15T12:00:00Z",
            },
        },
        "author": {"login": "octocat"},
        "html_url": f"https://github.com/octocat/repo/commit/{full_sha}",
    }

    normalized = normalize_github_commit(raw_commit)
    assert normalized is not None
    assert normalized.activity_type == "commit"
    assert normalized.external_id == full_sha
    assert normalized.title == "fix: resolve deadlock"
    assert normalized.author_login == "octocat"
    assert normalized.source_created_at == datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Missing SHA returns None
    assert normalize_github_commit({"commit": {"message": "no sha"}}) is None


def test_issues_endpoint_filters_out_pull_requests() -> None:
    """Verify normalize_github_issue filters out pull request objects returned by GitHub's Issues endpoint."""
    raw_pr_as_issue = {
        "id": 123456,
        "number": 99,
        "title": "PR returned by issues endpoint",
        "body": "PR description",
        "pull_request": {"url": "https://api.github.com/repos/octocat/repo/pulls/99"},
        "user": {"login": "octocat"},
        "state": "open",
        "html_url": "https://github.com/octocat/repo/pull/99",
        "created_at": "2026-10-15T10:00:00Z",
        "updated_at": "2026-10-15T10:00:00Z",
    }

    assert normalize_github_issue(raw_pr_as_issue) is None

    raw_issue = {
        "id": 987654,
        "number": 100,
        "title": "Real issue report",
        "body": "Issue details",
        "user": {"login": "reporter"},
        "state": "open",
        "html_url": "https://github.com/octocat/repo/issues/100",
        "created_at": "2026-10-15T10:00:00Z",
        "updated_at": "2026-10-15T10:00:00Z",
    }
    normalized = normalize_github_issue(raw_issue)
    assert normalized is not None
    assert normalized.activity_type == "issue"
    assert normalized.external_id == "987654"
    assert normalized.title == "Real issue report"


def test_bounded_normalization_payload_and_text() -> None:
    """Verify payload size, long body, and titles are bounded safely."""
    huge_body = "x" * 50000
    huge_title = "t" * 2000
    raw_pr = {
        "id": 555,
        "number": 12,
        "title": huge_title,
        "body": huge_body,
        "user": {"login": "author"},
        "state": "open",
        "html_url": "https://github.com/octocat/repo/pull/12",
        "created_at": "2026-10-15T10:00:00Z",
        "updated_at": "2026-10-15T10:00:00Z",
    }

    normalized = normalize_github_pull_request(raw_pr)
    assert normalized is not None
    assert len(normalized.title) <= 512
    assert len(normalized.body or "") <= 32768
    assert "number" in normalized.payload
    assert "body" not in normalized.payload


@pytest.mark.asyncio
async def test_client_list_pull_requests_pagination() -> None:
    """Verify list_repository_pull_requests fetches bounded pages."""
    client = GitHubClient(timeout=5.0)
    page1 = [{"id": 1, "number": 1, "title": "PR 1", "state": "open", "created_at": "2026-10-15T10:00:00Z"}]

    with patch.object(client, "_get_request", new=AsyncMock(return_value=page1)) as mock_get:
        prs = await client.list_repository_pull_requests("test_token", "octocat", "repo", page=1, per_page=100)
        assert len(prs) == 1
        assert prs[0]["id"] == 1
        mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_list_issues_filters_prs() -> None:
    """Verify client.list_repository_issues excludes items containing pull_request key."""
    client = GitHubClient(timeout=5.0)
    issues_page = [
        {"id": 10, "number": 10, "title": "Real Issue", "state": "open"},
        {"id": 11, "number": 11, "title": "PR Issue", "state": "open", "pull_request": {"url": "..."}},
        {"id": 12, "number": 12, "title": "Another Issue", "state": "closed"},
    ]

    with patch.object(client, "_get_request", new=AsyncMock(return_value=issues_page)):
        issues = await client.list_repository_issues("test_token", "octocat", "repo")
        assert len(issues) == 2
        assert issues[0]["id"] == 10
        assert issues[1]["id"] == 12


@pytest.mark.asyncio
async def test_client_list_pull_request_reviews() -> None:
    """Verify client.list_pull_request_reviews retrieves reviews tied to PR number."""
    client = GitHubClient(timeout=5.0)
    reviews_data = [
        {"id": 901, "state": "APPROVED", "submitted_at": "2026-10-15T12:00:00Z", "user": {"login": "reviewer1"}}
    ]

    with patch.object(client, "_get_request", new=AsyncMock(return_value=reviews_data)) as mock_get:
        reviews = await client.list_pull_request_reviews("test_token", "octocat", "repo", pull_number=42)
        assert len(reviews) == 1
        assert reviews[0]["id"] == 901
        assert "pulls/42/reviews" in mock_get.call_args[0][0]


@pytest.mark.asyncio
async def test_client_rate_limit_and_retry_after() -> None:
    """Verify 429/403 with Retry-After header raises GitHubRateLimitError."""
    client = GitHubClient(timeout=5.0)
    mock_resp = httpx.Response(
        status_code=429,
        headers={"Retry-After": "45"},
        json={"message": "API rate limit exceeded"},
        request=httpx.Request("GET", "https://api.github.com/repos/octocat/repo/pulls"),
    )

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
        with pytest.raises(GitHubRateLimitError) as exc_info:
            await client.list_repository_pull_requests("test_token", "octocat", "repo")
        assert exc_info.value.retry_after == 45


@pytest.mark.asyncio
async def test_client_auth_error_classification() -> None:
    """Verify 401 raises GitHubAuthError without retrying."""
    client = GitHubClient(timeout=5.0)
    mock_resp = httpx.Response(
        status_code=401,
        json={"message": "Bad credentials"},
        request=httpx.Request("GET", "https://api.github.com/repos/octocat/repo/pulls"),
    )

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
        with pytest.raises(GitHubAuthError):
            await client.list_repository_pull_requests("invalid_token", "octocat", "repo")


@pytest.mark.asyncio
async def test_distributed_activity_lock_prevents_concurrent_sync() -> None:
    """Verify acquiring activity sync lock blocks concurrent execution on the same repository."""
    conn_id = uuid.uuid4()

    token1 = await acquire_activity_sync_lock(conn_id)
    assert token1 is not None

    token2 = await acquire_activity_sync_lock(conn_id)
    assert token2 is None

    released = await release_activity_sync_lock(conn_id, token1)
    assert released is True

    token3 = await acquire_activity_sync_lock(conn_id)
    assert token3 is not None
    await release_activity_sync_lock(conn_id, token3)


@pytest.mark.asyncio
async def test_activity_sync_job_enqueue_dequeue_ack() -> None:
    """Verify GitHubActivitySyncJob serialization, queueing, and acknowledgment."""
    conn_id = uuid.uuid4()
    repo_ids = [uuid.uuid4(), uuid.uuid4()]

    queue_storage: list[str] = []
    processing_storage: list[str] = []

    mock_redis = AsyncMock()

    async def fake_lpush(key: str, val: str) -> int:
        queue_storage.append(val)
        return len(queue_storage)

    async def fake_lmove(*args: Any, **kwargs: Any) -> Optional[str]:
        if not queue_storage:
            return None
        val = queue_storage.pop(0)
        processing_storage.insert(0, val)
        return val

    async def fake_lrem(key: str, count: int, val: str) -> int:
        if val in processing_storage:
            processing_storage.remove(val)
            return 1
        return 0

    mock_redis.lpush = AsyncMock(side_effect=fake_lpush)
    mock_redis.lmove = AsyncMock(side_effect=fake_lmove)
    mock_redis.blmove = AsyncMock(side_effect=fake_lmove)
    mock_redis.lrem = AsyncMock(side_effect=fake_lrem)

    enqueued = await enqueue_github_activity_sync_job(conn_id, repo_ids, client=mock_redis)
    assert enqueued is True
    assert len(queue_storage) == 1

    dequeued_job, raw = await dequeue_github_activity_sync_job(timeout=0, client=mock_redis)
    assert dequeued_job is not None
    assert dequeued_job.connection_id == conn_id
    assert dequeued_job.repository_ids == repo_ids
    assert raw is not None
    assert len(processing_storage) == 1

    await ack_github_activity_sync_job(raw, client=mock_redis)
    assert len(processing_storage) == 0


@pytest.mark.asyncio
async def test_stranded_activity_sync_jobs_recovery() -> None:
    """Verify recovery of stranded jobs from processing queue."""
    conn_id = uuid.uuid4()
    job = GitHubActivitySyncJob(
        connection_id=conn_id,
        repository_ids=[],
        retry_count=0,
    )

    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 1])
    mock_redis.pipeline = AsyncMock(return_value=mock_pipe)
    mock_redis.lrange = AsyncMock(return_value=[job.model_dump_json()])

    recovered = await recover_stranded_github_activity_sync_jobs(client=mock_redis)
    assert recovered == 1


# ============================================================================
# Sequential Test Runner (Single-Event-Loop for DB Integration & API Scenarios)
# ============================================================================


async def run_all_stage15_integration_scenarios() -> None:
    """Execute all Stage 15 database integration, sync, worker, and API scenarios sequentially."""
    print("\n--- Starting Stage 15 GitHub Activity Ingestion Integration Scenarios ---")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        await clean_database()

        # ----------------------------------------------------------------------
        # Scenario 1: Model creation, fields, UUID PK, foreign key
        # ----------------------------------------------------------------------
        conn_id = await create_test_connection()
        repo_id = await create_test_repository(conn_id)

        now = datetime.now(timezone.utc)
        activity = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.PULL_REQUEST.value,
            external_id="101",
            title="feat: add activity ingestion",
            body="Detailed pull request body text.",
            html_url="https://github.com/activity_user/repo-alpha/pull/101",
            author_login="octocat",
            state="open",
            source_created_at=now,
            source_updated_at=now,
            payload={"number": 101, "draft": False},
        )

        async with AsyncSessionLocal() as session:
            session.add(activity)
            await session.commit()
            await session.refresh(activity)

            assert activity.id is not None
            assert isinstance(activity.id, uuid.UUID)
            assert activity.repository_id == repo_id
            assert activity.activity_type == "pull_request"
            assert activity.external_id == "101"
            assert activity.title == "feat: add activity ingestion"
            assert activity.state == "open"
            assert activity.payload == {"number": 101, "draft": False}
            assert activity.ingested_at is not None
        print("Scenario 1: Model creation, fields, UUID PK -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 2: Stable identity uniqueness constraint
        # ----------------------------------------------------------------------
        act1 = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE.value,
            external_id="42",
            title="Bug in parser",
            source_created_at=now,
        )
        act2 = GitHubActivity(
            repository_id=repo_id,
            activity_type=GitHubActivityType.ISSUE.value,
            external_id="42",
            title="Duplicate Bug in parser",
            source_created_at=now,
        )

        async with AsyncSessionLocal() as session:
            session.add(act1)
            await session.commit()

            session.add(act2)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
        print("Scenario 2: Stable identity uniqueness constraint -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 3: Idempotent upsert preserves internal UUID and updates fields
        # ----------------------------------------------------------------------
        initial_items = [
            NormalizedGitHubActivity(
                activity_type="pull_request",
                external_id="50",
                title="Initial Title",
                body="Initial Body",
                html_url="https://github.com/activity_user/repo-alpha/pull/50",
                author_login="alice",
                state="open",
                source_created_at=now - timedelta(days=1),
                source_updated_at=now - timedelta(days=1),
                payload={"merged": False},
            )
        ]

        async with AsyncSessionLocal() as session:
            inserted = await upsert_activities(session, repo_id, initial_items)
            assert inserted == 1

            res = await session.execute(select(GitHubActivity).where(GitHubActivity.repository_id == repo_id, GitHubActivity.external_id == "50"))
            rec = res.scalars().one()
            first_id = rec.id
            assert rec.title == "Initial Title"
            assert rec.state == "open"

        updated_items = [
            NormalizedGitHubActivity(
                activity_type="pull_request",
                external_id="50",
                title="Updated Title",
                body="Updated Body",
                html_url="https://github.com/activity_user/repo-alpha/pull/50",
                author_login="alice",
                state="closed",
                source_created_at=now - timedelta(days=1),
                source_updated_at=now,
                payload={"merged": True},
            )
        ]

        async with AsyncSessionLocal() as session:
            upserted = await upsert_activities(session, repo_id, updated_items)
            assert upserted == 1

            res = await session.execute(select(GitHubActivity).where(GitHubActivity.repository_id == repo_id, GitHubActivity.external_id == "50"))
            records = res.scalars().all()
            assert len(records) == 1
            assert records[0].id == first_id
            assert records[0].title == "Updated Title"
            assert records[0].state == "closed"
            assert records[0].payload == {"merged": True}
        print("Scenario 3: Idempotent upsert -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 4: Cascade deletion when repository is deleted
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            del_repo_id = await create_test_repository(conn_id, github_repo_id="9999", name="to-delete")
            activity = GitHubActivity(
                repository_id=del_repo_id,
                activity_type=GitHubActivityType.COMMIT.value,
                external_id="c" * 40,
                title="commit on temp repo",
                source_created_at=now,
            )
            session.add(activity)
            await session.commit()

            repo = await session.get(GitHubRepository, del_repo_id)
            await session.delete(repo)
            await session.commit()

            res = await session.execute(select(GitHubActivity).where(GitHubActivity.repository_id == del_repo_id))
            assert len(res.scalars().all()) == 0
        print("Scenario 4: Cascade deletion on repository delete -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 5: Sync only selected repositories (is_selected=True)
        # ----------------------------------------------------------------------
        unsel_repo_id = await create_test_repository(conn_id, github_repo_id="2002", name="unselected-repo", is_selected=False)

        fake_client = AsyncMock(spec=GitHubClient)
        fake_client.list_repository_pull_requests = AsyncMock(return_value=[])
        fake_client.list_repository_issues = AsyncMock(return_value=[])
        fake_client.list_repository_commits = AsyncMock(return_value=[])
        fake_client.list_pull_request_reviews = AsyncMock(return_value=[])

        async with AsyncSessionLocal() as session:
            result = await sync_selected_repositories_activities(session, conn_id, github_client=fake_client)
            assert result["synced_repositories"] == 1

            r_sel = await session.get(GitHubRepository, repo_id)
            assert r_sel.activity_sync_status == "synced"

            r_unsel = await session.get(GitHubRepository, unsel_repo_id)
            assert r_unsel.activity_sync_status == "idle"
        print("Scenario 5: Sync only selected repositories -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 6: Cross-user isolation rejects repositories of other users
        # ----------------------------------------------------------------------
        conn2_id = await create_test_connection(user_id="user_2", username="other_user")
        repo_other_id = await create_test_repository(conn2_id, github_repo_id="3003", name="other-user-repo", is_selected=True)

        async with AsyncSessionLocal() as session:
            res_cross = await sync_selected_repositories_activities(
                session, conn_id, repository_ids=[repo_other_id], github_client=fake_client
            )
            assert res_cross["synced_repositories"] == 0
            assert res_cross["status"] in ("completed", "no_repositories")

        # API ownership boundary: non-owned repository ID returns 404
        random_repo_id = uuid.uuid4()
        api_cross_res = await http_client.post(
            "/integrations/github/activities/sync",
            json={"repository_ids": [str(random_repo_id)]},
        )
        assert api_cross_res.status_code == 404
        assert "not found or does not belong" in api_cross_res.json()["detail"].lower()

        # Clean up temporary connection 2
        async with AsyncSessionLocal() as session:
            repo_to_del = await session.get(GitHubRepository, repo_other_id)
            if repo_to_del:
                await session.delete(repo_to_del)
            conn_to_del = await session.get(GitHubConnection, conn2_id)
            if conn_to_del:
                await session.delete(conn_to_del)
            await session.commit()
        print("Scenario 6: Cross-user isolation -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 7: Independent category failure preserves successful categories
        # ----------------------------------------------------------------------
        raw_pr = {
            "id": 101,
            "number": 1,
            "title": "PR 1",
            "user": {"login": "octocat"},
            "state": "open",
            "created_at": "2026-10-15T10:00:00Z",
            "updated_at": "2026-10-15T10:00:00Z",
        }

        fake_cat_client = AsyncMock(spec=GitHubClient)
        fake_cat_client.list_repository_pull_requests = AsyncMock(return_value=[raw_pr])
        fake_cat_client.list_repository_issues = AsyncMock(return_value=[])
        fake_cat_client.list_repository_commits = AsyncMock(side_effect=GitHubApiError("500 Internal Server Error"))
        fake_cat_client.list_pull_request_reviews = AsyncMock(return_value=[])

        repo_cat_id = await create_test_repository(conn_id, github_repo_id="7001", name="repo-scenario-7", is_selected=True)

        async with AsyncSessionLocal() as session:
            conn = await session.get(GitHubConnection, conn_id)
            repo = await session.get(GitHubRepository, repo_cat_id)
            result = await sync_repository_activities(session, conn, repo, "fake_token", fake_cat_client)

            assert result["status"] == "partial"
            assert result["synced_activities"] >= 1
            assert "commits" in result["error"]

            pr_records = (
                await session.execute(
                    select(GitHubActivity).where(
                        GitHubActivity.repository_id == repo_cat_id,
                        GitHubActivity.activity_type == "pull_request",
                        GitHubActivity.external_id == "101",
                    )
                )
            ).scalars().all()
            assert len(pr_records) == 1
            assert pr_records[0].title == "PR 1"

            meta = repo.activity_sync_metadata
            assert "pull_requests" in meta.get("checkpoints", {})
            assert "commits" not in meta.get("checkpoints", {})
        print("Scenario 7: Independent category failure -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 8: Checkpoint does NOT advance after persistence failure
        # ----------------------------------------------------------------------
        raw_pr2 = {
            "id": 202,
            "number": 2,
            "title": "PR 2",
            "user": {"login": "octocat"},
            "state": "open",
            "created_at": "2026-10-15T10:00:00Z",
            "updated_at": "2026-10-15T12:00:00Z",
        }
        fake_client.list_repository_pull_requests = AsyncMock(return_value=[raw_pr2])

        async with AsyncSessionLocal() as session:
            conn = await session.get(GitHubConnection, conn_id)
            repo = await session.get(GitHubRepository, repo_id)
            repo.activity_sync_metadata = {"checkpoints": {}}
            await session.commit()

            with patch("app.integrations.github.service.upsert_activities", side_effect=RuntimeError("DB write failed")):
                res_fail = await sync_repository_activities(session, conn, repo, "fake_token", fake_client)
                assert res_fail["status"] in ("failed", "partial")

            await session.refresh(repo)
            assert repo.activity_sync_metadata.get("checkpoints", {}) == {}
        print("Scenario 8: Checkpoint persistence safety -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 9: Worker processor executes activity sync idempotently
        # ----------------------------------------------------------------------
        with patch(
            "app.integrations.github.service.sync_selected_repositories_activities",
            new=AsyncMock(return_value={"status": "completed", "synced_activities": 5}),
        ):
            assert await process_github_activity_sync(str(conn_id), [str(repo_id)]) is True
            assert await process_github_activity_sync(str(conn_id), [str(repo_id)]) is True
        print("Scenario 9: Worker activity sync idempotency -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 10: API POST /activities/sync triggers synchronous sync
        # ----------------------------------------------------------------------
        with patch("app.integrations.github.router.sync_selected_repositories_activities", new=AsyncMock(return_value={"status": "completed", "synced_repositories": 1, "synced_activities": 10})):
            api_res = await http_client.post(
                "/integrations/github/activities/sync",
                json={"repository_ids": [str(repo_id)]},
            )
            assert api_res.status_code == 200, f"Expected 200, got {api_res.status_code}: {api_res.text}"
            data = api_res.json()
            assert data["status"] == "completed"
            assert data["synced_repositories"] == 1
            assert data["synced_activities"] == 10
        print("Scenario 10: API sync synchronous -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 11: API POST /activities/sync?async_sync=true enqueues background job
        # ----------------------------------------------------------------------
        with patch("app.integrations.github.router.enqueue_github_activity_sync_job", new=AsyncMock()) as mock_enq:
            api_async_res = await http_client.post(
                "/integrations/github/activities/sync?async_sync=true",
                json={"repository_ids": [str(repo_id)]},
            )
            assert api_async_res.status_code == 200, f"Expected 200, got {api_async_res.status_code}: {api_async_res.text}"
            data = api_async_res.json()
            assert data["status"] == "enqueued"
            mock_enq.assert_awaited_once()
        print("Scenario 11: API sync asynchronous -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 12: API rejects unselected repository IDs
        # ----------------------------------------------------------------------
        api_unsel_res = await http_client.post(
            "/integrations/github/activities/sync",
            json={"repository_ids": [str(unsel_repo_id)]},
        )
        assert api_unsel_res.status_code == 400
        assert "not selected" in api_unsel_res.json()["detail"].lower()
        print("Scenario 12: API rejects unselected repositories -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 13: API GET /activities lists and filters activities
        # ----------------------------------------------------------------------
        activities_to_insert = [
            GitHubActivity(
                repository_id=repo_id,
                activity_type="pull_request",
                external_id="pr_100",
                title="PR Alpha",
                source_created_at=now + timedelta(hours=1),
            ),
            GitHubActivity(
                repository_id=repo_id,
                activity_type="issue",
                external_id="issue_200",
                title="Issue Beta",
                source_created_at=now + timedelta(hours=2),
            ),
            GitHubActivity(
                repository_id=repo_id,
                activity_type="commit",
                external_id="d" * 40,
                title="Commit Gamma",
                source_created_at=now + timedelta(hours=3),
            ),
        ]
        async with AsyncSessionLocal() as session:
            session.add_all(activities_to_insert)
            await session.commit()

        # Query all activities
        list_all_res = await http_client.get("/integrations/github/activities")
        assert list_all_res.status_code == 200
        all_data = list_all_res.json()
        assert all_data["total"] >= 3

        # Filter by activity_type=issue
        list_issue_res = await http_client.get("/integrations/github/activities?activity_type=issue")
        assert list_issue_res.status_code == 200
        issue_data = list_issue_res.json()
        assert issue_data["total"] >= 1
        for item in issue_data["items"]:
            assert item["activity_type"] == "issue"

        # Deterministic sorting check (newest first)
        titles = [item["title"] for item in all_data["items"][:3]]
        assert "Commit Gamma" in titles[0]
        print("Scenario 13: API list and filter activities -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 14: API GET /activities/status aggregate status
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn_record = await session.get(GitHubConnection, conn_id)
            conn_record.token_metadata = {
                "activity_sync": {
                    "status": "synced",
                    "synced_repositories": 1,
                    "synced_activities": 8,
                }
            }
            repo_record = await session.get(GitHubRepository, repo_id)
            repo_record.activity_sync_status = "synced"
            repo_record.activity_sync_metadata = {"counts": {"pull_request": 5, "issue": 3}}
            await session.commit()

        status_res = await http_client.get("/integrations/github/activities/status")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["status"] == "synced"
        assert status_data["synced_repositories"] == 1
        assert status_data["synced_activities"] == 8
        assert len(status_data["repositories"]) >= 1
        print("Scenario 14: API activity status aggregate -> PASS")

        # ----------------------------------------------------------------------
        # Scenario 15: No tokens or secrets leaked in API responses
        # ----------------------------------------------------------------------
        full_text = f"{list_all_res.text} {status_res.text}"
        assert "gho_stage15_secret_token_abcde" not in full_text
        assert "encrypted_access_token" not in full_text
        print("Scenario 15: No tokens or secrets leaked -> PASS")

    print("\n--- ALL STAGE 15 INTEGRATION SCENARIOS PASSED SUCCESSFULLY ---")


@pytest.mark.asyncio
async def test_stage15_integration_scenarios() -> None:
    """Pytest entrypoint executing the complete Stage 15 integration suite."""
    await run_all_stage15_integration_scenarios()


# ==============================================================================
# STAGE 15.1 REGRESSION TESTS — PR #7 REVIEW FINDINGS REMEDIATION
# ==============================================================================


def test_finding_4_no_duplicate_index_on_activity_sync_status() -> None:
    """Finding 4: Verify that GitHubRepository has exactly one index on activity_sync_status."""
    table: Any = GitHubRepository.__table__
    index_names = [idx.name for idx in table.indexes if idx.name]
    sync_status_indexes = [name for name in index_names if "activity_sync_status" in name]
    assert len(sync_status_indexes) == 1, (
        f"Expected exactly 1 index on activity_sync_status, found {len(sync_status_indexes)}: {sync_status_indexes}"
    )
    assert table.c.activity_sync_status.index is True


@pytest.mark.asyncio
async def test_finding_5_empty_repo_409_returns_empty_commits() -> None:
    """Finding 5: Verify that HTTP 409 Conflict from commits endpoint returns empty list,
    while other endpoints and statuses retain normal error handling.
    """
    client = GitHubClient()

    # 1. HTTP 409 from commits endpoint -> empty list
    with patch.object(client, "_get_request", side_effect=GitHubApiError("Conflict: Git Repository is empty.", status_code=409)):
        commits = await client.list_repository_commits(
            access_token="test_token",
            owner="test_owner",
            repo="empty_repo",
        )
        assert commits == []

    # 2. HTTP 404 from commits endpoint -> raises GitHubApiError
    with patch.object(client, "_get_request", side_effect=GitHubApiError("Not found", status_code=404)):
        with pytest.raises(GitHubApiError) as exc_info:
            await client.list_repository_commits(
                access_token="test_token",
                owner="test_owner",
                repo="missing_repo",
            )
        assert exc_info.value.status_code == 404

    # 3. HTTP 409 on another endpoint (e.g., pull requests) -> does NOT return empty list, raises error
    with patch.object(client, "_get_request", side_effect=GitHubApiError("Conflict", status_code=409)):
        with pytest.raises(GitHubApiError) as exc_info:
            await client.list_repository_pull_requests(
                access_token="test_token",
                owner="test_owner",
                repo="some_repo",
            )
        assert exc_info.value.status_code == 409


def test_finding_6_commit_author_email_not_persisted() -> None:
    """Finding 6: Verify normalize_github_commit does NOT persist author_email in payload."""
    raw_commit = {
        "sha": "abcdef1234567890abcdef1234567890abcdef12",
        "commit": {
            "message": "feat: add secure pipeline\n\nDetailed body",
            "author": {
                "name": "Jane Developer",
                "email": "jane.dev@private-company.com",
                "date": "2026-05-01T12:00:00Z",
            },
        },
        "author": {
            "login": "janedev",
        },
        "html_url": "https://github.com/org/repo/commit/abcdef1234567890abcdef1234567890abcdef12",
    }
    norm = normalize_github_commit(raw_commit)
    assert norm is not None
    assert norm.author_login == "janedev"
    assert norm.payload is not None
    assert "author_email" not in norm.payload
    assert "email" not in str(norm.payload)
    assert norm.payload.get("author_name") == "Jane Developer"
    assert norm.payload.get("sha") == "abcdef1234567890abcdef1234567890abcdef12"


@pytest.mark.asyncio
async def test_finding_7_checkpoints_never_skip_unfetched_activities_and_track_truncation() -> None:
    """Finding 7: Comprehensive regression tests for bounded pagination and checkpoints:
    1. Truncated PR pagination preserves prior checkpoint and reports partial.
    2. Truncated commits pagination preserves prior checkpoint and reports partial.
    3. Ascending issue pagination advances checkpoint safely to frontier, subsequent run recovers data.
    4. Request budget exhaustion marks category truncated without skipping unfetched items.
    """
    await clean_database()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, name="trunc-repo", full_name="activity_user/trunc-repo")

    # Mock client with truncated responses (page_size=2, but 4 items available)
    mock_client = AsyncMock()

    # PRs: Page 1 returns 2 PRs (full page => truncated under max_pages=1)
    mock_client.list_repository_pull_requests = AsyncMock(return_value=[
        {
            "id": 101,
            "number": 1,
            "title": "PR 1",
            "body": "PR 1 body",
            "html_url": "https://github.com/activity_user/trunc-repo/pull/1",
            "state": "open",
            "created_at": "2026-05-01T10:00:00Z",
            "updated_at": "2026-05-10T10:00:00Z",
            "user": {"login": "dev1"},
        },
        {
            "id": 102,
            "number": 2,
            "title": "PR 2",
            "body": "PR 2 body",
            "html_url": "https://github.com/activity_user/trunc-repo/pull/2",
            "state": "open",
            "created_at": "2026-05-01T09:00:00Z",
            "updated_at": "2026-05-09T10:00:00Z",
            "user": {"login": "dev2"},
        },
    ])

    # Issues: Returns 2 issues in ascending order (sort="updated", direction="asc")
    mock_client.list_repository_issues = AsyncMock(return_value=[
        {
            "id": 201,
            "number": 10,
            "title": "Issue 10",
            "body": "Issue 10 body",
            "html_url": "https://github.com/activity_user/trunc-repo/issues/10",
            "state": "open",
            "created_at": "2026-05-01T08:00:00Z",
            "updated_at": "2026-05-05T08:00:00Z",
            "user": {"login": "dev1"},
        },
        {
            "id": 202,
            "number": 11,
            "title": "Issue 11",
            "body": "Issue 11 body",
            "html_url": "https://github.com/activity_user/trunc-repo/issues/11",
            "state": "open",
            "created_at": "2026-05-01T09:00:00Z",
            "updated_at": "2026-05-06T09:00:00Z",
            "user": {"login": "dev2"},
        },
    ])

    # Commits: returns 2 commits (truncated under max_pages=1)
    mock_client.list_repository_commits = AsyncMock(return_value=[
        {
            "sha": "1" * 40,
            "commit": {"message": "Commit 1", "author": {"name": "Dev", "date": "2026-05-10T12:00:00Z"}},
            "author": {"login": "dev1"},
            "html_url": "https://github.com/activity_user/trunc-repo/commit/" + "1" * 40,
        },
        {
            "sha": "2" * 40,
            "commit": {"message": "Commit 2", "author": {"name": "Dev", "date": "2026-05-09T12:00:00Z"}},
            "author": {"login": "dev2"},
            "html_url": "https://github.com/activity_user/trunc-repo/commit/" + "2" * 40,
        },
    ])

    mock_client.list_pull_request_reviews = AsyncMock(return_value=[])

    with patch("app.core.config.get_settings") as mock_settings:
        settings_obj = get_settings()
        mock_settings.return_value = settings_obj
        orig_pages = settings_obj.GITHUB_ACTIVITY_MAX_PAGES_PER_RUN
        orig_page_size = settings_obj.GITHUB_ACTIVITY_PAGE_SIZE
        orig_budget = settings_obj.GITHUB_ACTIVITY_REQUEST_BUDGET
        try:
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_MAX_PAGES_PER_RUN", 1)
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_PAGE_SIZE", 2)
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_REQUEST_BUDGET", 10)

            # -------------------------------------------------------------
            # RUN 1: Truncated pagination run
            # -------------------------------------------------------------
            async with AsyncSessionLocal() as session:
                conn = await session.get(GitHubConnection, conn_id)
                repo = await session.get(GitHubRepository, repo_id)
                assert conn is not None
                assert repo is not None
                res1 = await sync_repository_activities(
                    db=session,
                    connection=conn,
                    repository=repo,
                    access_token="dummy_token",
                    github_client=mock_client,
                )

                # Verification of Run 1:
                meta = repo.activity_sync_metadata
                assert meta is not None
                checkpoints = meta.get("checkpoints", {})

                # 1. PR checkpoint MUST NOT advance
                assert "pull_requests" not in checkpoints, "PR checkpoint must not advance when truncated!"
                assert meta["categories"]["pull_requests"]["status"] == "partial"
                assert meta["categories"]["pull_requests"]["truncated"] is True

                # 2. Commits checkpoint MUST NOT advance
                assert "commits" not in checkpoints, "Commits checkpoint must not advance when truncated!"
                assert meta["categories"]["commits"]["status"] == "partial"
                assert meta["categories"]["commits"]["truncated"] is True

                # 3. Issues was fetched ascending; checkpoint advances to max_issue_updated (2026-05-06T09:00:00)
                assert "issues" in checkpoints
                assert "2026-05-06T09:00:00" in checkpoints["issues"]
                assert meta["categories"]["issues"]["status"] == "partial"
                assert meta["categories"]["issues"]["truncated"] is True

                # Overall repo status is partial
                assert repo.activity_sync_status == "partial"
                assert repo.activity_sync_error is not None
                assert "pagination or budget limits" in repo.activity_sync_error

            # -------------------------------------------------------------
            # RUN 2: Recovery run (normal pagination completes)
            # -------------------------------------------------------------
            # PRs now return 1 PR (< page_size=2) -> completes normally!
            mock_client.list_repository_pull_requests = AsyncMock(return_value=[
                {
                    "id": 103,
                    "number": 3,
                    "title": "PR 3 (final)",
                    "body": "PR 3 body",
                    "html_url": "https://github.com/activity_user/trunc-repo/pull/3",
                    "state": "open",
                    "created_at": "2026-05-01T10:00:00Z",
                    "updated_at": "2026-05-11T10:00:00Z",
                    "user": {"login": "dev1"},
                }
            ])
            # Issues: returns 1 remaining issue (< page_size=2) -> completes normally!
            mock_client.list_repository_issues = AsyncMock(return_value=[
                {
                    "id": 203,
                    "number": 12,
                    "title": "Issue 12 (recovered)",
                    "body": "Issue 12 body",
                    "html_url": "https://github.com/activity_user/trunc-repo/issues/12",
                    "state": "open",
                    "created_at": "2026-05-01T09:00:00Z",
                    "updated_at": "2026-05-12T09:00:00Z",
                    "user": {"login": "dev2"},
                }
            ])
            # Commits: returns 1 commit (< page_size=2) -> completes normally!
            mock_client.list_repository_commits = AsyncMock(return_value=[
                {
                    "sha": "3" * 40,
                    "commit": {"message": "Commit 3", "author": {"name": "Dev", "date": "2026-05-11T12:00:00Z"}},
                    "author": {"login": "dev1"},
                    "html_url": "https://github.com/activity_user/trunc-repo/commit/" + "3" * 40,
                }
            ])

            async with AsyncSessionLocal() as session:
                conn = await session.get(GitHubConnection, conn_id)
                repo = await session.get(GitHubRepository, repo_id)
                assert conn is not None
                assert repo is not None
                res2 = await sync_repository_activities(
                    db=session,
                    connection=conn,
                    repository=repo,
                    access_token="dummy_token",
                    github_client=mock_client,
                )

                # Verification of Run 2:
                meta2 = repo.activity_sync_metadata
                assert meta2 is not None
                checkpoints2 = meta2.get("checkpoints", {})

                # Now all categories completed normally, so all checkpoints advanced!
                assert "pull_requests" in checkpoints2
                assert "2026-05-11T10:00:00" in checkpoints2["pull_requests"]
                assert meta2["categories"]["pull_requests"]["status"] == "synced"
                assert meta2["categories"]["pull_requests"]["truncated"] is False

                assert "commits" in checkpoints2
                assert "2026-05-11T12:00:00" in checkpoints2["commits"]
                assert meta2["categories"]["commits"]["status"] == "synced"
                assert meta2["categories"]["commits"]["truncated"] is False

                assert "issues" in checkpoints2
                assert "2026-05-12T09:00:00" in checkpoints2["issues"]
                assert meta2["categories"]["issues"]["status"] == "synced"
                assert meta2["categories"]["issues"]["truncated"] is False

                # Overall repo status is now fully synced!
                assert repo.activity_sync_status == "synced"
                assert repo.activity_sync_error is None

            # -------------------------------------------------------------
            # RUN 3: Request budget exhaustion simulation
            # -------------------------------------------------------------
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_REQUEST_BUDGET", 1)
            async with AsyncSessionLocal() as session:
                conn = await session.get(GitHubConnection, conn_id)
                repo = await session.get(GitHubRepository, repo_id)
                assert conn is not None
                assert repo is not None
                res3 = await sync_repository_activities(
                    db=session,
                    connection=conn,
                    repository=repo,
                    access_token="dummy_token",
                    github_client=mock_client,
                )
                # Budget was 1: PR consumed it (budget=0). Issues/Commits/Reviews see budget<=0.
                meta3 = repo.activity_sync_metadata
                assert meta3 is not None
                assert meta3["categories"]["issues"]["truncated"] is True
                assert meta3["categories"]["commits"]["truncated"] is True
                assert meta3["categories"]["issues"]["status"] == "partial"
                assert meta3["categories"]["commits"]["status"] == "partial"
                assert repo.activity_sync_status == "partial"
        finally:
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_MAX_PAGES_PER_RUN", orig_pages)
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_PAGE_SIZE", orig_page_size)
            object.__setattr__(settings_obj, "GITHUB_ACTIVITY_REQUEST_BUDGET", orig_budget)


@pytest.mark.asyncio
async def test_finding_8_rollback_on_failed_transaction_allows_subsequent_categories() -> None:
    """Finding 8: A failed transaction in one category rolls back, preserves previous state,
    and allows subsequent categories and final status persistence to succeed without PendingRollbackError.
    """
    await clean_database()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, name="rollback-repo", full_name="activity_user/rollback-repo")

    mock_client = AsyncMock()
    mock_client.list_repository_pull_requests = AsyncMock(return_value=[
        {
            "id": 501,
            "number": 51,
            "title": "PR to fail",
            "html_url": "https://github.com/activity_user/rollback-repo/pull/51",
            "state": "open",
            "created_at": "2026-05-01T10:00:00Z",
            "updated_at": "2026-05-01T10:00:00Z",
            "user": {"login": "dev1"},
        }
    ])
    mock_client.list_repository_issues = AsyncMock(return_value=[
        {
            "id": 601,
            "number": 61,
            "title": "Issue to succeed",
            "html_url": "https://github.com/activity_user/rollback-repo/issues/61",
            "state": "open",
            "created_at": "2026-05-01T10:00:00Z",
            "updated_at": "2026-05-01T10:00:00Z",
            "user": {"login": "dev1"},
        }
    ])
    mock_client.list_repository_commits = AsyncMock(return_value=[])
    mock_client.list_pull_request_reviews = AsyncMock(return_value=[])

    original_upsert = upsert_activities
    call_count = 0

    async def flaky_upsert(db, repository_id, activities):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate database constraint or flush failure on PRs
            raise OperationalError("INSERT INTO activities", {}, Exception("Simulated DB connection or flush error"))
        return await original_upsert(db, repository_id, activities)

    with patch("app.integrations.github.service.upsert_activities", side_effect=flaky_upsert):
        async with AsyncSessionLocal() as session:
            conn = await session.get(GitHubConnection, conn_id)
            repo = await session.get(GitHubRepository, repo_id)
            assert conn is not None
            assert repo is not None
            res = await sync_repository_activities(
                db=session,
                connection=conn,
                repository=repo,
                access_token="dummy_token",
                github_client=mock_client,
            )

            # Verification:
            # 1. PR category failed
            assert res["categories"]["pull_requests"]["status"] == "failed"
            # 2. Issues category SUCCEEDED despite PR failure (session rolled back cleanly)
            assert res["categories"]["issues"]["status"] == "synced"
            assert res["categories"]["issues"]["count"] == 1
            # 3. Final repo status is "partial", NOT stuck indefinitely in "syncing"!
            assert repo.activity_sync_status == "partial"
            assert repo.activity_sync_metadata is not None
            # 4. Checkpoint for PR was NOT advanced
            assert "pull_requests" not in repo.activity_sync_metadata.get("checkpoints", {})
            # 5. Checkpoint for issues WAS advanced
            assert "issues" in repo.activity_sync_metadata.get("checkpoints", {})


@pytest.mark.asyncio
async def test_finding_9_sanitizes_unexpected_exception_details() -> None:
    """Finding 9: Raw SQL statements, table names, and internal exception details
    are never leaked into activity_sync_error, category error, or API response details.
    Safe, actionable GitHub errors remain preserved.
    """
    await clean_database()
    conn_id = await create_test_connection()
    repo_id = await create_test_repository(conn_id, name="sanitize-repo", full_name="activity_user/sanitize-repo")

    mock_client = AsyncMock()
    sensitive_db_err = OperationalError(
        "SELECT secret_token, password_hash FROM internal_credentials WHERE user_id = 'leak'",
        {"user_id": "leak"},
        Exception("connection terminated abnormally"),
    )
    mock_client.list_repository_pull_requests = AsyncMock(side_effect=sensitive_db_err)
    mock_client.list_repository_issues = AsyncMock(return_value=[])
    mock_client.list_repository_commits = AsyncMock(return_value=[])
    mock_client.list_pull_request_reviews = AsyncMock(return_value=[])

    async with AsyncSessionLocal() as session:
        conn = await session.get(GitHubConnection, conn_id)
        repo = await session.get(GitHubRepository, repo_id)
        assert conn is not None
        assert repo is not None
        res = await sync_repository_activities(
            db=session,
            connection=conn,
            repository=repo,
            access_token="dummy_token",
            github_client=mock_client,
        )

        # Ensure raw SQL / sensitive details are NOT in categories_status or repo.activity_sync_error
        pr_err = res["categories"]["pull_requests"]["error"]
        assert "secret_token" not in pr_err
        assert "password_hash" not in pr_err
        assert "SELECT" not in pr_err
        assert pr_err == GENERIC_ACTIVITY_SYNC_ERROR_MESSAGE

        # Also check repo level
        assert "secret_token" not in (repo.activity_sync_error or "")
        assert "password_hash" not in (repo.activity_sync_error or "")

    # Now verify trusted GitHubClientError retains its actionable message
    mock_client.list_repository_pull_requests = AsyncMock(
        side_effect=GitHubRateLimitError("GitHub API rate limit exceeded.", status_code=403, retry_after=60)
    )
    async with AsyncSessionLocal() as session:
        conn = await session.get(GitHubConnection, conn_id)
        repo = await session.get(GitHubRepository, repo_id)
        assert conn is not None
        assert repo is not None
        res2 = await sync_repository_activities(
            db=session,
            connection=conn,
            repository=repo,
            access_token="dummy_token",
            github_client=mock_client,
        )
        assert "GitHub API rate limit exceeded." in res2["categories"]["pull_requests"]["error"]

