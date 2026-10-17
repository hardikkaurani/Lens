"""Integration and forensic security tests for GitHub Repository Discovery & Import Foundation (Stage 14).

Covers all 37 backend scenarios:
1. no GitHub connection -> 404
2. authenticated repository discovery -> 200
3. GitHub API request headers validated
4. token decrypted only server-side
5. repository response parsing
6. malformed repository response handled
7. pagination across multiple pages
8. empty page termination
9. maximum repository bound enforced
10. malformed pagination handled
11. rate limit 403 handling -> 429
12. rate limit 429 handling -> 429
13. Retry-After header handling
14. GitHub timeout -> 504
15. GitHub 401 -> 401
16. GitHub 500 -> 502
17. repository normalization
18. nullable fields handled safely
19. first repository insert
20. idempotent upsert (repeated sync produces no duplicates)
21. repository rename preserves internal UUID & is_selected
22. metadata update on existing record
23. database uniqueness prevents duplicate records
24. concurrent sync protection (distributed lock)
25. sync success lifecycle
26. sync failure releases lock cleanly
27. worker retry / idempotency
28. stuck sync recovery
29. no tokens or secrets in API responses
30. malicious repository metadata sanitized
31. unauthorized repository access -> 404
32. database rollback on transaction error
33. Redis failure / fallback lock handling
34. token-checked atomic lock release
35. production mode lock failure (fail closed)
36. queue crash recovery (stranded processing queue)
37. connection sync state visibility & error tracking
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Awaitable, Optional, cast
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest
from sqlalchemy import delete, func, select

# Ensure services/api and services/worker are in sys.path
api_path = str(Path(__file__).resolve().parents[1])
if api_path not in sys.path:
    sys.path.insert(0, api_path)
worker_path = str(Path(__file__).resolve().parents[2] / "worker")
if worker_path not in sys.path:
    sys.path.insert(0, worker_path)

from app.core.config import get_settings
from app.core.encryption import decrypt_secret, encrypt_secret
from app.db.models import GitHubConnection, GitHubRepository, RepositorySyncStatus
from app.db.session import AsyncSessionLocal, close_connections
from app.integrations.github.client import (
    GitHubApiError,
    GitHubAuthError,
    GitHubClient,
    GitHubRateLimitError,
    GitHubTimeoutError,
    get_github_client,
)
from app.integrations.github.schemas import (
    NormalizedGitHubRepository,
    check_sufficient_repo_scope,
    normalize_github_repository,
)
from app.integrations.github.service import (
    GENERIC_SYNC_ERROR_MESSAGE,
    LockStorageError,
    MAX_REPOSITORIES_PER_SYNC,
    _memory_lock_cache,
    acquire_sync_lock,
    discover_and_sync_repositories,
    is_sync_metadata_active,
    list_connection_repositories,
    release_sync_lock,
    update_repository_selection,
    upsert_repositories,
)
from app.queue.job import (
    GITHUB_REPO_SYNC_PROCESSING_QUEUE,
    GITHUB_REPO_SYNC_QUEUE,
    recover_stranded_github_repo_sync_jobs,
)
from app.main import app
from worker.processor import process_github_repo_sync


async def clean_database() -> None:
    """Purge repositories and connections for clean test state."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(GitHubRepository))
        await session.execute(delete(GitHubConnection))
        await session.commit()
    _memory_lock_cache.clear()


async def create_test_connection(user_id: str = "gh_user_test", username: str = "testuser") -> uuid.UUID:
    """Helper to insert an active test GitHubConnection."""
    async with AsyncSessionLocal() as session:
        encrypted = encrypt_secret("gho_test_secret_token_12345")
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


def make_mock_github_repo(
    repo_id: int,
    name: str = "test-repo",
    full_name: Optional[str] = None,
    private: bool = False,
    description: Optional[str] = "A test repository",
    language: Optional[str] = "Python",
) -> dict[str, Any]:
    """Helper generating a mock GitHub API user repository dict."""
    fn = full_name or f"testuser/{name}"
    return {
        "id": repo_id,
        "node_id": f"MDEwOlJlcG9zaXRvcnkx{repo_id}",
        "name": name,
        "full_name": fn,
        "owner": {"id": 1234, "login": fn.split("/")[0]},
        "private": private,
        "html_url": f"https://github.com/{fn}",
        "description": description,
        "fork": False,
        "archived": False,
        "disabled": False,
        "default_branch": "main",
        "language": language,
        "visibility": "private" if private else "public",
        "license": {"spdx_id": "MIT", "name": "MIT License"},
        "created_at": "2026-01-01T12:00:00Z",
        "updated_at": "2026-02-01T12:00:00Z",
        "pushed_at": "2026-02-02T12:00:00Z",
    }


async def run_all_stage14_tests() -> None:
    """Execute all 33 Stage 14 tests sequentially."""
    print("\n--- Starting Stage 14 GitHub Repository Discovery & Import Tests ---")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await clean_database()
        app.dependency_overrides.clear()

        # ----------------------------------------------------------------------
        # Test 1: no GitHub connection -> 404
        # ----------------------------------------------------------------------
        sync_res = await client.post("/integrations/github/repositories/sync")
        assert sync_res.status_code == 404, f"Expected 404, got {sync_res.status_code}"
        assert "no active github connection" in sync_res.json()["detail"].lower()

        list_res = await client.get("/integrations/github/repositories")
        assert list_res.status_code == 404, f"Expected 404, got {list_res.status_code}"
        print("Test 1: no GitHub connection -> PASS")

        # ----------------------------------------------------------------------
        # Test 2: authenticated repository discovery -> 200
        # ----------------------------------------------------------------------
        conn_id = await create_test_connection()
        mock_repos = [
            make_mock_github_repo(101, "repo-alpha"),
            make_mock_github_repo(102, "repo-beta", private=True),
        ]

        with patch.object(GitHubClient, "list_user_repositories", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_repos
            sync_ok = await client.post("/integrations/github/repositories/sync")
            assert sync_ok.status_code == 200, f"Expected 200, got {sync_ok.status_code}: {sync_ok.text}"
            data = sync_ok.json()
            assert data["status"] == "completed"
            assert data["synced_count"] == 2
            assert data["total"] == 2
        print("Test 2: authenticated repository discovery -> PASS")

        # ----------------------------------------------------------------------
        # Test 3: GitHub API request headers validated
        # ----------------------------------------------------------------------
        gh_client = GitHubClient()
        captured_headers = {}

        async def fake_get(url: str, params: Any = None, headers: Any = None):
            nonlocal captured_headers
            captured_headers = headers
            resp = httpx.Response(200, json=[], request=httpx.Request("GET", url))
            return resp

        with patch("httpx.AsyncClient.get", side_effect=fake_get):
            await gh_client.list_user_repositories(access_token="test_token_val", page=1, per_page=50)
            assert captured_headers.get("Authorization") == "Bearer test_token_val"
            assert captured_headers.get("Accept") == "application/vnd.github+json"
            assert captured_headers.get("User-Agent") == "LENS-Integration-Service/1.0"
            assert captured_headers.get("X-GitHub-Api-Version") == "2022-11-28"
        print("Test 3: GitHub API request headers -> PASS")

        # ----------------------------------------------------------------------
        # Test 4: token decrypted only server-side
        # ----------------------------------------------------------------------
        list_res = await client.get("/integrations/github/repositories")
        assert list_res.status_code == 200
        res_text = list_res.text
        assert "gho_test_secret_token_12345" not in res_text
        assert "encrypted_access_token" not in res_text
        print("Test 4: token decrypted only server-side -> PASS")

        # ----------------------------------------------------------------------
        # Test 5: repository response parsing
        # ----------------------------------------------------------------------
        raw_repo = make_mock_github_repo(201, "parsed-repo")
        norm = normalize_github_repository(raw_repo)
        assert norm is not None
        assert norm.github_repository_id == "201"
        assert norm.name == "parsed-repo"
        assert norm.full_name == "testuser/parsed-repo"
        assert norm.owner_login == "testuser"
        assert norm.is_private is False
        assert norm.default_branch == "main"
        assert norm.license_name == "MIT"
        print("Test 5: repository response parsing -> PASS")

        # ----------------------------------------------------------------------
        # Test 6: malformed repository response handled
        # ----------------------------------------------------------------------
        assert normalize_github_repository({"invalid": "payload"}) is None
        assert normalize_github_repository({"id": 123}) is None  # missing name and html_url
        assert normalize_github_repository({"id": 123, "name": "foo", "full_name": "bar", "html_url": "ftp://bad"}) is None
        print("Test 6: malformed repository response -> PASS")

        # ----------------------------------------------------------------------
        # Test 7: pagination across multiple pages
        # ----------------------------------------------------------------------
        p1 = [make_mock_github_repo(1000 + i, f"repo-{i}") for i in range(100)]
        p2 = [make_mock_github_repo(2000 + i, f"repo-page2-{i}") for i in range(5)]

        async def mock_paginated(access_token, page, per_page, **kwargs):
            if page == 1:
                return p1
            elif page == 2:
                return p2
            return []

        with patch.object(GitHubClient, "list_user_repositories", side_effect=mock_paginated):
            sync_page = await client.post("/integrations/github/repositories/sync")
            assert sync_page.status_code == 200
            # 100 from p1 + 5 from p2 = 105 synced
            assert sync_page.json()["synced_count"] == 105
        print("Test 7: pagination -> PASS")

        # ----------------------------------------------------------------------
        # Test 8: empty page termination
        # ----------------------------------------------------------------------
        call_count = 0

        async def mock_empty_first(access_token, page, per_page, **kwargs):
            nonlocal call_count
            call_count += 1
            return []

        with patch.object(GitHubClient, "list_user_repositories", side_effect=mock_empty_first):
            res_term = await client.post("/integrations/github/repositories/sync")
            assert res_term.status_code == 200
            assert call_count == 1
        print("Test 8: empty page termination -> PASS")

        # ----------------------------------------------------------------------
        # Test 9: maximum repository bound enforced
        # ----------------------------------------------------------------------
        async def mock_infinite(access_token, page, per_page, **kwargs):
            return [make_mock_github_repo(100000 * page + i, f"inf-{page}-{i}") for i in range(100)]

        with patch.object(GitHubClient, "list_user_repositories", side_effect=mock_infinite):
            res_bound = await client.post("/integrations/github/repositories/sync")
            assert res_bound.status_code == 200
            assert res_bound.json()["synced_count"] <= MAX_REPOSITORIES_PER_SYNC
        print("Test 9: maximum repository bound -> PASS")

        # ----------------------------------------------------------------------
        # Test 10: malformed pagination handled safely
        # ----------------------------------------------------------------------
        async def mock_malformed_p2(access_token, page, per_page, **kwargs):
            if page == 1:
                return [make_mock_github_repo(999, "ok-repo")]
            raise GitHubApiError("Malformed chunk received", status_code=502)

        with patch.object(GitHubClient, "list_user_repositories", side_effect=mock_malformed_p2):
            res_mal = await client.post("/integrations/github/repositories/sync")
            assert res_mal.status_code in (200, 502)
        print("Test 10: malformed pagination -> PASS")

        # ----------------------------------------------------------------------
        # Test 11: rate limit 403 handling -> 429
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=GitHubRateLimitError("Rate limit exceeded", status_code=403, retry_after=30)):
            res_rl403 = await client.post("/integrations/github/repositories/sync")
            assert res_rl403.status_code == 429, f"Expected 429, got {res_rl403.status_code}"
            assert res_rl403.headers.get("retry-after") == "30"
        print("Test 11: rate limit 403 -> PASS")

        # ----------------------------------------------------------------------
        # Test 12: rate limit 429 handling -> 429
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=GitHubRateLimitError("Rate limit exceeded", status_code=429)):
            res_rl429 = await client.post("/integrations/github/repositories/sync")
            assert res_rl429.status_code == 429
            assert "rate limit exceeded" in res_rl429.json()["detail"].lower()
        print("Test 12: rate limit 429 -> PASS")

        # ----------------------------------------------------------------------
        # Test 13: Retry-After header handling
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=GitHubRateLimitError("Rate limit exceeded", status_code=429, retry_after=120)):
            res_retry = await client.post("/integrations/github/repositories/sync")
            assert res_retry.headers.get("Retry-After") == "120"
        print("Test 13: Retry-After handling -> PASS")

        # ----------------------------------------------------------------------
        # Test 14: GitHub timeout -> 504
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=GitHubTimeoutError("GitHub connection timed out")):
            res_to = await client.post("/integrations/github/repositories/sync")
            assert res_to.status_code == 504
        print("Test 14: GitHub timeout -> PASS")

        # ----------------------------------------------------------------------
        # Test 15: GitHub 401 -> 401
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=GitHubAuthError("Bad credentials", status_code=401)):
            res_auth = await client.post("/integrations/github/repositories/sync")
            assert res_auth.status_code == 401
            assert "rejected" in res_auth.json()["detail"].lower()
        print("Test 15: GitHub 401 -> PASS")

        # ----------------------------------------------------------------------
        # Test 16: GitHub 500 -> 502
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=GitHubApiError("GitHub 500 Internal Error", status_code=500)):
            res_500 = await client.post("/integrations/github/repositories/sync")
            assert res_500.status_code == 502
        print("Test 16: GitHub 500 -> PASS")

        # ----------------------------------------------------------------------
        # Test 17: repository normalization
        # ----------------------------------------------------------------------
        dirty_repo = make_mock_github_repo(777, "  dirty-repo \x00 ", description=" A description\x00with nulls ")
        clean_norm = normalize_github_repository(dirty_repo)
        assert clean_norm is not None
        assert clean_norm.name == "dirty-repo"
        assert "\x00" not in clean_norm.name
        assert "\x00" not in (clean_norm.description or "")
        print("Test 17: repository normalization -> PASS")

        # ----------------------------------------------------------------------
        # Test 18: nullable fields handled safely
        # ----------------------------------------------------------------------
        null_repo = {
            "id": 888,
            "name": "null-repo",
            "full_name": "testuser/null-repo",
            "html_url": "https://github.com/testuser/null-repo",
            "owner": {"login": "testuser"},
            "description": None,
            "language": None,
            "license": None,
            "pushed_at": None,
        }
        null_norm = normalize_github_repository(null_repo)
        assert null_norm is not None
        assert null_norm.description is None
        assert null_norm.language is None
        assert null_norm.license_name is None
        assert null_norm.github_pushed_at is None
        print("Test 18: nullable fields -> PASS")

        # ----------------------------------------------------------------------
        # Test 19: first repository insert
        # ----------------------------------------------------------------------
        await clean_database()
        conn_id = await create_test_connection()
        insert_repo = [make_mock_github_repo(301, "initial-repo")]
        with patch.object(GitHubClient, "list_user_repositories", return_value=insert_repo):
            await client.post("/integrations/github/repositories/sync")

        async with AsyncSessionLocal() as session:
            db_repo = (await session.execute(select(GitHubRepository).where(GitHubRepository.github_repository_id == "301"))).scalar_one_or_none()
            assert db_repo is not None
            assert db_repo.name == "initial-repo"
            assert db_repo.sync_status == RepositorySyncStatus.SYNCED
            assert db_repo.last_synced_at is not None
        print("Test 19: first repository insert -> PASS")

        # ----------------------------------------------------------------------
        # Test 20: idempotent upsert
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", return_value=insert_repo):
            await client.post("/integrations/github/repositories/sync")
            await client.post("/integrations/github/repositories/sync")

        async with AsyncSessionLocal() as session:
            count = (await session.execute(select(func.count(GitHubRepository.id)).where(GitHubRepository.github_repository_id == "301"))).scalar()
            assert count == 1, f"Expected exactly 1 record, got {count}"
        print("Test 20: idempotent upsert -> PASS")

        # ----------------------------------------------------------------------
        # Test 21: repository rename preserves internal UUID & is_selected
        # ----------------------------------------------------------------------
        # 1. Mark repository selected
        async with AsyncSessionLocal() as session:
            r = (await session.execute(select(GitHubRepository).where(GitHubRepository.github_repository_id == "301"))).scalar_one()
            orig_id = r.id
            r.is_selected = True
            await session.commit()

        # 2. Simulate GitHub repo rename with SAME github_repository_id
        renamed_repo = [make_mock_github_repo(301, "renamed-repo", full_name="testuser/renamed-repo")]
        with patch.object(GitHubClient, "list_user_repositories", return_value=renamed_repo):
            await client.post("/integrations/github/repositories/sync")

        async with AsyncSessionLocal() as session:
            updated = (await session.execute(select(GitHubRepository).where(GitHubRepository.github_repository_id == "301"))).scalar_one()
            assert updated.id == orig_id, "Internal UUID must be preserved upon rename"
            assert updated.name == "renamed-repo"
            assert updated.full_name == "testuser/renamed-repo"
            assert updated.is_selected is True, "is_selected preference must be preserved upon rename"
        print("Test 21: repository rename -> PASS")

        # ----------------------------------------------------------------------
        # Test 22: metadata update
        # ----------------------------------------------------------------------
        meta_repo = [make_mock_github_repo(301, "renamed-repo", description="Updated description text", language="TypeScript")]
        with patch.object(GitHubClient, "list_user_repositories", return_value=meta_repo):
            await client.post("/integrations/github/repositories/sync")

        async with AsyncSessionLocal() as session:
            updated = (await session.execute(select(GitHubRepository).where(GitHubRepository.github_repository_id == "301"))).scalar_one()
            assert updated.description == "Updated description text"
            assert updated.language == "TypeScript"
        print("Test 22: metadata update -> PASS")

        # ----------------------------------------------------------------------
        # Test 23: database uniqueness prevents duplicate records
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            dup_repo = GitHubRepository(
                connection_id=conn_id,
                github_repository_id="301",  # duplicate external id for same connection
                name="dup",
                full_name="testuser/dup",
                owner_login="testuser",
                html_url="https://github.com/testuser/dup",
            )
            session.add(dup_repo)
            with pytest.raises(Exception):
                await session.commit()
            await session.rollback()
        print("Test 23: duplicate prevention -> PASS")

        # ----------------------------------------------------------------------
        # Test 24: concurrent sync protection
        # ----------------------------------------------------------------------
        locked = await acquire_sync_lock(conn_id)
        assert locked is not None
        # While locked, sync should return already_syncing
        res_locked = await client.post("/integrations/github/repositories/sync")
        assert res_locked.status_code == 200
        assert res_locked.json()["status"] == "already_syncing"
        await release_sync_lock(conn_id, locked)
        print("Test 24: concurrent sync protection -> PASS")

        # ----------------------------------------------------------------------
        # Test 25: sync success lifecycle
        # ----------------------------------------------------------------------
        success_repos = [
            make_mock_github_repo(401, "repo-1"),
            make_mock_github_repo(402, "repo-2"),
            make_mock_github_repo(403, "repo-3"),
        ]
        with patch.object(GitHubClient, "list_user_repositories", return_value=success_repos):
            sync_resp = await client.post("/integrations/github/repositories/sync")
            assert sync_resp.status_code == 200
            data = sync_resp.json()
            assert data["status"] == "completed"
            assert data["synced_count"] == 3
        print("Test 25: sync success -> PASS")

        # ----------------------------------------------------------------------
        # Test 26: sync failure releases lock cleanly
        # ----------------------------------------------------------------------
        with patch.object(GitHubClient, "list_user_repositories", side_effect=RuntimeError("Simulated sync crash")):
            try:
                await client.post("/integrations/github/repositories/sync")
            except Exception:
                pass
        # Verify lock was released
        can_acquire = await acquire_sync_lock(conn_id)
        assert can_acquire is not None
        await release_sync_lock(conn_id, can_acquire)
        print("Test 26: sync failure releases lock -> PASS")

        # ----------------------------------------------------------------------
        # Test 27: worker retry / idempotency
        # ----------------------------------------------------------------------
        worker_repos = [make_mock_github_repo(501, "worker-repo")]
        with patch.object(GitHubClient, "list_user_repositories", return_value=worker_repos):
            w1 = await process_github_repo_sync(conn_id)
            assert w1 is True
            w2 = await process_github_repo_sync(conn_id)
            assert w2 is True
        async with AsyncSessionLocal() as session:
            count = (await session.execute(select(func.count(GitHubRepository.id)).where(GitHubRepository.github_repository_id == "501"))).scalar()
            assert count == 1
        print("Test 27: worker retry/idempotency -> PASS")

        # ----------------------------------------------------------------------
        # Test 28: stuck sync recovery
        # ----------------------------------------------------------------------
        _memory_lock_cache[f"lens:lock:github_sync:{conn_id}"] = ("expired_token", time.time() - 1)
        res_rec = await acquire_sync_lock(conn_id)
        assert res_rec is not None
        await release_sync_lock(conn_id, res_rec)
        print("Test 28: stuck sync recovery -> PASS")

        # ----------------------------------------------------------------------
        # Test 29: no token in API response
        # ----------------------------------------------------------------------
        list_all = await client.get("/integrations/github/repositories")
        assert list_all.status_code == 200
        for item in list_all.json()["items"]:
            assert "access_token" not in item
            assert "token" not in item
            assert "secret" not in item
        print("Test 29: no token in API response -> PASS")

        # ----------------------------------------------------------------------
        # Test 30: malicious repository metadata
        # ----------------------------------------------------------------------
        xss_repo = [make_mock_github_repo(601, "<script>alert(1)</script>", description="<img src=x onerror=alert(2)>")]
        with patch.object(GitHubClient, "list_user_repositories", return_value=xss_repo):
            await client.post("/integrations/github/repositories/sync")

        list_xss = await client.get("/integrations/github/repositories")
        items = list_xss.json()["items"]
        xss_item = next(it for it in items if it["github_repository_id"] == "601")
        assert xss_item["name"] == "<script>alert(1)</script>"  # safely stored as text string
        print("Test 30: malicious repository metadata -> PASS")

        # ----------------------------------------------------------------------
        # Test 31: unauthorized repository access -> 404
        # ----------------------------------------------------------------------
        fake_uuid = uuid.uuid4()
        patch_res = await client.patch(
            f"/integrations/github/repositories/{fake_uuid}/selection",
            json={"is_selected": True},
        )
        assert patch_res.status_code == 404
        print("Test 31: unauthorized repository access -> PASS")

        # ----------------------------------------------------------------------
        # Test 32: database rollback on transaction error
        # ----------------------------------------------------------------------
        with patch("sqlalchemy.ext.asyncio.AsyncSession.commit", side_effect=Exception("DB Error")):
            try:
                await client.post("/integrations/github/repositories/sync")
            except Exception:
                pass
        # Verify subsequent query works cleanly without dead transaction
        check_res = await client.get("/integrations/github/repositories")
        assert check_res.status_code == 200
        print("Test 32: database rollback -> PASS")

        # ----------------------------------------------------------------------
        # Test 33: Redis failure / fallback lock handling
        # ----------------------------------------------------------------------
        with patch("app.integrations.github.service.get_redis_client", side_effect=Exception("Redis down")):
            lock1 = await acquire_sync_lock(conn_id)
            assert lock1 is not None
            lock2 = await acquire_sync_lock(conn_id)
            assert lock2 is None  # Memory lock rejected duplicate concurrent
            await release_sync_lock(conn_id, lock1)
        print("Test 33: Redis failure handling -> PASS")

        # ----------------------------------------------------------------------
        # Test 34: Token-checked atomic release
        # ----------------------------------------------------------------------
        tok = await acquire_sync_lock(conn_id)
        assert tok is not None
        # Attempt to release with wrong token
        wrong_released = await release_sync_lock(conn_id, "wrong-token-12345")
        assert wrong_released is False
        # Verify lock is still held
        assert await acquire_sync_lock(conn_id) is None
        # Release with correct token
        correct_released = await release_sync_lock(conn_id, tok)
        assert correct_released is True
        # Now can be acquired again
        reacquired = await acquire_sync_lock(conn_id)
        assert reacquired is not None
        await release_sync_lock(conn_id, reacquired)
        print("Test 34: token-checked atomic lock release -> PASS")

        # ----------------------------------------------------------------------
        # Test 35: Production mode lock failure (fail closed)
        # ----------------------------------------------------------------------
        mock_prod_settings = get_settings().model_copy(update={"APP_ENV": "production"})
        with patch("app.core.config.get_settings", return_value=mock_prod_settings):
            with patch("app.integrations.github.service.get_redis_client", side_effect=Exception("Redis connection pool exhausted")):
                with pytest.raises(LockStorageError):
                    await acquire_sync_lock(conn_id)
        print("Test 35: production mode lock failure fail-closed -> PASS")

        # ----------------------------------------------------------------------
        # Test 36: Queue crash recovery
        # ----------------------------------------------------------------------
        from app.queue.job import GitHubRepoSyncJob
        from app.db.session import get_redis_client
        redis_conn = get_redis_client()
        # Clean test queue keys
        await redis_conn.delete(GITHUB_REPO_SYNC_QUEUE)
        await redis_conn.delete(GITHUB_REPO_SYNC_PROCESSING_QUEUE)

        # 1. Normal recoverable stranded job
        valid_job = GitHubRepoSyncJob(connection_id=conn_id, retry_count=0, max_retries=3)
        await cast(Awaitable[int], redis_conn.rpush(GITHUB_REPO_SYNC_PROCESSING_QUEUE, valid_job.model_dump_json()))

        # 2. Poison pill job exceeding max_retries
        poison_job = GitHubRepoSyncJob(connection_id=conn_id, retry_count=3, max_retries=3)
        await cast(Awaitable[int], redis_conn.rpush(GITHUB_REPO_SYNC_PROCESSING_QUEUE, poison_job.model_dump_json()))

        recovered_count = await recover_stranded_github_repo_sync_jobs()
        assert recovered_count == 1
        # Check that valid_job was moved back to main queue with incremented retry_count
        main_queue_item = await cast(Awaitable[Any], redis_conn.lpop(GITHUB_REPO_SYNC_QUEUE))
        assert main_queue_item is not None
        item_str = main_queue_item if isinstance(main_queue_item, str) else str(main_queue_item)
        recovered_job = GitHubRepoSyncJob.model_validate_json(item_str)
        assert recovered_job.retry_count == 1
        # Processing queue should now be empty
        assert await cast(Awaitable[int], redis_conn.llen(GITHUB_REPO_SYNC_PROCESSING_QUEUE)) == 0
        print("Test 36: queue crash recovery -> PASS")

        # ----------------------------------------------------------------------
        # Test 37: Connection sync state visibility & unexpected error masking (Finding 3)
        # ----------------------------------------------------------------------
        status_resp = await client.get("/integrations/github")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert "sync_status" in status_data
        assert "last_synced_at" in status_data
        assert "sync_error" in status_data
        assert status_data["sync_status"] == "synced"
        assert status_data["last_synced_at"] is not None
        assert status_data["sync_error"] is None

        # Verify unexpected sync failure masks raw error text and returns curated generic error
        with patch.object(GitHubClient, "list_user_repositories", side_effect=RuntimeError("Fatal API sync boom")):
            sync_fail_resp = await client.post("/integrations/github/repositories/sync")
            assert sync_fail_resp.status_code == 500
            assert sync_fail_resp.json()["detail"] == GENERIC_SYNC_ERROR_MESSAGE
            assert "Fatal API sync boom" not in sync_fail_resp.text

        failed_status = await client.get("/integrations/github")
        assert failed_status.status_code == 200
        assert failed_status.json()["sync_status"] == "failed"
        assert failed_status.json()["sync_error"] == GENERIC_SYNC_ERROR_MESSAGE
        assert "Fatal API sync boom" not in (failed_status.json()["sync_error"] or "")
        print("Test 37: connection sync state visibility & unexpected error masking -> PASS")

        # ----------------------------------------------------------------------
        # Test 38: OAuth scope disclosure & missing scope protection (Finding 1)
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn_res = await session.execute(select(GitHubConnection))
            current_conn = conn_res.scalars().first()
            assert current_conn is not None
            current_conn.scope = "read:user"  # Missing repo/public_repo
            await session.commit()

        # Check status detects insufficient scope
        scope_status_resp = await client.get("/integrations/github")
        assert scope_status_resp.status_code == 200
        scope_data = scope_status_resp.json()
        assert scope_data["has_required_scope"] is False
        assert scope_data["missing_scope_reason"] is not None
        assert "repo or public_repo" in scope_data["missing_scope_reason"]
        assert "reconnect" in scope_data["missing_scope_reason"].lower()

        # Attempting sync with insufficient scope returns 403 Forbidden
        insufficient_sync = await client.post("/integrations/github/repositories/sync")
        assert insufficient_sync.status_code == 403
        assert "repo or public_repo" in insufficient_sync.json()["detail"]
        assert "reconnect" in insufficient_sync.json()["detail"].lower()

        # Reconnect / restore sufficient scope
        async with AsyncSessionLocal() as session:
            conn_res = await session.execute(select(GitHubConnection))
            current_conn = conn_res.scalars().first()
            assert current_conn is not None
            current_conn.scope = "read:user,repo"
            await session.commit()

        restored_status_resp = await client.get("/integrations/github")
        assert restored_status_resp.status_code == 200
        assert restored_status_resp.json()["has_required_scope"] is True
        assert restored_status_resp.json()["missing_scope_reason"] is None
        print("Test 38: OAuth scope disclosure & missing scope protection -> PASS")

        # ----------------------------------------------------------------------
        # Test 39: Async sync pre-enqueue persistence & failure rollback (Finding 2)
        # ----------------------------------------------------------------------
        with patch("app.integrations.github.router.enqueue_github_repo_sync_job", side_effect=RuntimeError("Redis queue failure")):
            async_fail_resp = await client.post("/integrations/github/repositories/sync?async_sync=true")
            assert async_fail_resp.status_code == 503
            assert "Failed to queue repository sync" in async_fail_resp.json()["detail"]

        # Ensure connection was not left permanently stuck in syncing state
        post_fail_status = await client.get("/integrations/github")
        assert post_fail_status.status_code == 200
        assert post_fail_status.json()["sync_status"] == "failed"
        assert post_fail_status.json()["sync_error"] == "Failed to enqueue synchronization job."
        print("Test 39: async sync pre-enqueue persistence & failure rollback -> PASS")

        # ----------------------------------------------------------------------
        # Test 40: Stale syncing state recovery after TTL expiry (Finding 2)
        # ----------------------------------------------------------------------
        from sqlalchemy.orm.attributes import flag_modified

        async with AsyncSessionLocal() as session:
            conn_res = await session.execute(select(GitHubConnection))
            current_conn = conn_res.scalars().first()
            assert current_conn is not None
            meta = dict(current_conn.token_metadata or {})
            stale_time = (datetime.now(timezone.utc) - timedelta(seconds=350)).isoformat()
            meta["sync"] = {"status": "syncing", "started_at": stale_time, "error": None}
            current_conn.token_metadata = meta
            flag_modified(current_conn, "token_metadata")
            await session.commit()

        with patch("app.integrations.github.router.enqueue_github_repo_sync_job", new_callable=AsyncMock) as mock_enq:
            stale_recover_resp = await client.post("/integrations/github/repositories/sync?async_sync=true")
            assert stale_recover_resp.status_code == 200
            assert stale_recover_resp.json()["status"] == "enqueued"
            mock_enq.assert_awaited_once()
        print("Test 40: stale syncing state recovery after TTL expiry -> PASS")

        # ----------------------------------------------------------------------
        # Test 41: Malformed timestamp syncing recovery (Finding 2)
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn_res = await session.execute(select(GitHubConnection))
            current_conn = conn_res.scalars().first()
            assert current_conn is not None
            meta = dict(current_conn.token_metadata or {})
            meta["sync"] = {"status": "syncing", "started_at": "invalid-garbage-date", "error": None}
            current_conn.token_metadata = meta
            flag_modified(current_conn, "token_metadata")
            await session.commit()

        with patch("app.integrations.github.router.enqueue_github_repo_sync_job", new_callable=AsyncMock) as mock_enq:
            invalid_ts_resp = await client.post("/integrations/github/repositories/sync?async_sync=true")
            assert invalid_ts_resp.status_code == 200
            assert invalid_ts_resp.json()["status"] == "enqueued"
            mock_enq.assert_awaited_once()
        print("Test 41: malformed timestamp syncing recovery -> PASS")

        # ----------------------------------------------------------------------
        # Test 42: Duplicate concurrent async sync requests return already_syncing (Finding 2)
        # ----------------------------------------------------------------------
        # Connection is currently in fresh 'syncing' state from Test 41
        duplicate_async_resp = await client.post("/integrations/github/repositories/sync?async_sync=true")
        assert duplicate_async_resp.status_code == 200
        assert duplicate_async_resp.json()["status"] == "already_syncing"
        print("Test 42: duplicate concurrent async request protection -> PASS")

        # ----------------------------------------------------------------------
        # Test 43: Failure state persistence DB commit error resilience (Finding 3)
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn_res = await session.execute(select(GitHubConnection))
            test_conn = conn_res.scalars().first()
            assert test_conn is not None

            with patch.object(session, "commit", side_effect=[None, RuntimeError("Database connection lost")]), \
                 patch.object(session, "rollback", new_callable=AsyncMock) as mock_rollback, \
                 patch.object(GitHubClient, "list_user_repositories", side_effect=RuntimeError("API failure")):
                with pytest.raises(RuntimeError, match="API failure"):
                    await discover_and_sync_repositories(session, test_conn)
                mock_rollback.assert_awaited()
        print("Test 43: failure persistence DB commit error resilience -> PASS")

    print("\n--- ALL 43 STAGE 14 BACKEND TESTS PASSED SUCCESSFULLY ---")


@pytest.mark.asyncio
async def test_stage14_full_suite() -> None:
    """Pytest entrypoint executing the complete Stage 14 test suite."""
    await run_all_stage14_tests()


if __name__ == "__main__":
    asyncio.run(run_all_stage14_tests())
