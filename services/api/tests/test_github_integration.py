"""Integration test suite for LENS GitHub Integration & OAuth (Stage 13).

Covers:
1. OAuth configuration missing -> 503
2. Connect endpoint generates redirect to GitHub
3. State is cryptographically random
4. State expires
5. State is single-use
6. Missing state rejected -> 400
7. Mismatched state rejected -> 400
8. Replayed state rejected -> 400
9. OAuth denial handled safely
10. Missing code rejected -> 400
11. Token exchange success
12. Token exchange failure -> 400
13. Malformed token response -> 502
14. GitHub identity retrieval -> verified
15. Malformed GitHub identity response -> 502
16. Connection persistence in DB
17. Token encrypted at rest
18. Plaintext token not persisted
19. Connection status response excludes token
20. Client secret excluded from response
21. Disconnect removes connection
22. Disconnect is idempotent
23. Duplicate callback handling (upsert)
24. GitHub timeout -> 504
25. GitHub provider error -> 502
26. DB failure handling -> 500
27. Malicious username safely handled
28. Open redirect protection
"""

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch
import uuid

import httpx
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.encryption import decrypt_secret, encrypt_secret
from app.db.models import GitHubConnection
from app.db.session import AsyncSessionLocal, close_connections
from app.integrations.github.client import (
    GitHubApiError,
    GitHubAuthError,
    GitHubClient,
    GitHubTimeoutError,
    get_github_client,
)
from app.integrations.github.service import (
    generate_oauth_state,
    store_oauth_state,
    validate_and_consume_oauth_state,
)
from app.main import app


async def clean_github_connections() -> None:
    """Purge github connection records created during testing."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(GitHubConnection))
        await session.commit()


async def run_all_stage13_tests() -> None:
    """Execute all 28 Stage 13 GitHub integration tests sequentially."""
    print("\n--- Starting Stage 13 GitHub Integration Tests ---")

    settings = get_settings()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await clean_github_connections()
        app.dependency_overrides.clear()

        # ----------------------------------------------------------------------
        # 1. OAuth configuration missing
        # ----------------------------------------------------------------------
        with patch.object(settings, "GITHUB_CLIENT_ID", None):
            res1 = await client.get("/integrations/github/connect", follow_redirects=False)
            assert res1.status_code == 503, f"Expected 503, got {res1.status_code}"
            assert "not configured" in res1.json()["detail"].lower()
        print("Test 1: OAuth configuration missing -> PASS")

        # Configure temporary test credentials for subsequent tests
        settings.GITHUB_CLIENT_ID = "test_github_client_id"
        settings.GITHUB_CLIENT_SECRET = "test_github_client_secret"
        settings.FRONTEND_URL = "http://localhost:3000"

        # ----------------------------------------------------------------------
        # 2. Connect endpoint generates redirect to GitHub
        # ----------------------------------------------------------------------
        res2 = await client.get("/integrations/github/connect", follow_redirects=False)
        assert res2.status_code in (302, 307), f"Expected redirect, got {res2.status_code}"
        loc2 = res2.headers.get("location", "")
        assert "github.com/login/oauth/authorize" in loc2
        assert "client_id=test_github_client_id" in loc2
        assert "state=" in loc2
        assert "scope=" in loc2
        assert "lens_oauth_state" in res2.cookies
        state2 = res2.cookies["lens_oauth_state"]
        assert f"state={state2}" in loc2
        print("Test 2: connect endpoint generates redirect -> PASS")

        # ----------------------------------------------------------------------
        # 3. State is cryptographically random (sufficient entropy)
        # ----------------------------------------------------------------------
        states = {generate_oauth_state() for _ in range(50)}
        assert len(states) == 50, "Generated states must be unique"
        for s in states:
            assert len(s) >= 32, "State string must provide sufficient entropy"
        print("Test 3: state is cryptographically random -> PASS")

        # ----------------------------------------------------------------------
        # 4. State expires (TTL expiration check)
        # ----------------------------------------------------------------------
        test_state_exp = generate_oauth_state()
        from app.integrations.github import service as gh_service
        # Simulate an already-expired state in fallback memory store
        gh_service._memory_state_cache[test_state_exp] = (
            json.dumps({"created_at": time.time() - 700}),
            time.time() - 10,
        )
        consumed_exp = await validate_and_consume_oauth_state(test_state_exp)
        assert consumed_exp is None, "Expired state must not be validated"
        print("Test 4: state expires -> PASS")

        # ----------------------------------------------------------------------
        # 5. State is single-use
        # ----------------------------------------------------------------------
        test_state_single = generate_oauth_state()
        await store_oauth_state(test_state_single)
        first_use = await validate_and_consume_oauth_state(test_state_single)
        assert first_use is not None, "First consumption must succeed"
        second_use = await validate_and_consume_oauth_state(test_state_single)
        assert second_use is None, "Second consumption of the same state must fail"
        print("Test 5: state is single-use -> PASS")

        # ----------------------------------------------------------------------
        # 6. Missing state rejected
        # ----------------------------------------------------------------------
        res6 = await client.get("/integrations/github/callback?code=abc", follow_redirects=False)
        assert res6.status_code == 400, f"Expected 400, got {res6.status_code}"
        assert "state" in res6.json()["detail"].lower()
        print("Test 6: missing state rejected -> PASS")

        # ----------------------------------------------------------------------
        # 7. Mismatched state rejected
        # ----------------------------------------------------------------------
        st7_query = generate_oauth_state()
        st7_cookie = generate_oauth_state()
        await store_oauth_state(st7_query)
        client.cookies.set("lens_oauth_state", st7_cookie)
        res7 = await client.get(f"/integrations/github/callback?code=abc&state={st7_query}", follow_redirects=False)
        assert res7.status_code == 400, f"Expected 400, got {res7.status_code}"
        assert "mismatched" in res7.json()["detail"].lower() or "invalid" in res7.json()["detail"].lower()
        print("Test 7: mismatched state rejected -> PASS")

        # ----------------------------------------------------------------------
        # 8. Replayed state rejected
        # ----------------------------------------------------------------------
        st8 = generate_oauth_state()
        await store_oauth_state(st8)
        # Consume once manually
        await validate_and_consume_oauth_state(st8)
        client.cookies.set("lens_oauth_state", st8)
        res8 = await client.get(f"/integrations/github/callback?code=abc&state={st8}", follow_redirects=False)
        assert res8.status_code == 400, f"Expected 400, got {res8.status_code}"
        assert "already been used" in res8.json()["detail"].lower() or "expired" in res8.json()["detail"].lower()
        print("Test 8: replayed state rejected -> PASS")

        # ----------------------------------------------------------------------
        # 9. OAuth denial handled safely
        # ----------------------------------------------------------------------
        res9 = await client.get(
            "/integrations/github/callback?error=access_denied&error_description=User+cancelled",
            follow_redirects=False,
        )
        assert res9.status_code in (302, 307), f"Expected 307 redirect, got {res9.status_code}"
        loc9 = res9.headers.get("location", "")
        assert "github_error=access_denied" in loc9
        print("Test 9: OAuth denial handled safely -> PASS")

        # ----------------------------------------------------------------------
        # 10. Missing code rejected
        # ----------------------------------------------------------------------
        st10 = generate_oauth_state()
        await store_oauth_state(st10)
        client.cookies.set("lens_oauth_state", st10)
        res10 = await client.get(f"/integrations/github/callback?state={st10}", follow_redirects=False)
        assert res10.status_code == 400, f"Expected 400, got {res10.status_code}"
        assert "code" in res10.json()["detail"].lower()
        print("Test 10: missing code rejected -> PASS")

        # ----------------------------------------------------------------------
        # 11. Token exchange success
        # ----------------------------------------------------------------------
        mock_gh = AsyncMock()
        mock_gh.exchange_code_for_token.return_value = {
            "access_token": "gho_test_token_12345",
            "token_type": "bearer",
            "scope": "read:user",
        }
        mock_gh.get_authenticated_user.return_value = {
            "id": "987654",
            "login": "octocat_tester",
        }
        app.dependency_overrides[get_github_client] = lambda: mock_gh

        st11 = generate_oauth_state()
        await store_oauth_state(st11)
        client.cookies.set("lens_oauth_state", st11)

        res11 = await client.get(
            f"/integrations/github/callback?code=valid_code&state={st11}",
            follow_redirects=False,
        )
        assert res11.status_code in (302, 307), f"Expected redirect, got {res11.status_code}"
        assert "github=connected" in res11.headers.get("location", "")
        print("Test 11: token exchange success -> PASS")

        # ----------------------------------------------------------------------
        # 12. Token exchange failure
        # ----------------------------------------------------------------------
        mock_gh_fail = AsyncMock()
        mock_gh_fail.exchange_code_for_token.side_effect = GitHubAuthError("bad_verification_code")
        app.dependency_overrides[get_github_client] = lambda: mock_gh_fail

        st12 = generate_oauth_state()
        await store_oauth_state(st12)
        client.cookies.set("lens_oauth_state", st12)

        res12 = await client.get(
            f"/integrations/github/callback?code=bad_code&state={st12}",
            follow_redirects=False,
        )
        assert res12.status_code == 400, f"Expected 400, got {res12.status_code}"
        assert "bad_verification_code" in res12.json()["detail"]
        print("Test 12: token exchange failure -> PASS")

        # ----------------------------------------------------------------------
        # 13. Malformed token response
        # ----------------------------------------------------------------------
        mock_gh_malformed = AsyncMock()
        mock_gh_malformed.exchange_code_for_token.side_effect = GitHubApiError("Malformed response received from GitHub OAuth service.")
        app.dependency_overrides[get_github_client] = lambda: mock_gh_malformed

        st13 = generate_oauth_state()
        await store_oauth_state(st13)
        client.cookies.set("lens_oauth_state", st13)

        res13 = await client.get(
            f"/integrations/github/callback?code=code13&state={st13}",
            follow_redirects=False,
        )
        assert res13.status_code == 502, f"Expected 502, got {res13.status_code}"
        print("Test 13: malformed token response -> PASS")

        # ----------------------------------------------------------------------
        # 14. GitHub identity retrieval
        # ----------------------------------------------------------------------
        app.dependency_overrides[get_github_client] = lambda: mock_gh
        st14 = generate_oauth_state()
        await store_oauth_state(st14)
        client.cookies.set("lens_oauth_state", st14)

        res14 = await client.get(
            f"/integrations/github/callback?code=code14&state={st14}",
            follow_redirects=False,
        )
        assert res14.status_code in (302, 307)
        assert "github=connected" in res14.headers.get("location", "")
        print("Test 14: GitHub identity retrieval -> PASS")

        # ----------------------------------------------------------------------
        # 15. Malformed GitHub identity response
        # ----------------------------------------------------------------------
        mock_gh_bad_ident = AsyncMock()
        mock_gh_bad_ident.exchange_code_for_token.return_value = {
            "access_token": "token15",
            "token_type": "bearer",
            "scope": "read:user",
        }
        mock_gh_bad_ident.get_authenticated_user.side_effect = GitHubApiError("Malformed user response")
        app.dependency_overrides[get_github_client] = lambda: mock_gh_bad_ident

        st15 = generate_oauth_state()
        await store_oauth_state(st15)
        client.cookies.set("lens_oauth_state", st15)

        res15 = await client.get(
            f"/integrations/github/callback?code=code15&state={st15}",
            follow_redirects=False,
        )
        assert res15.status_code == 502, f"Expected 502, got {res15.status_code}"
        assert "failed to verify github user identity" in res15.json()["detail"].lower()
        print("Test 15: malformed GitHub identity response -> PASS")

        # ----------------------------------------------------------------------
        # 16. Connection persistence in DB
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn16 = (await session.execute(select(GitHubConnection).where(GitHubConnection.provider == "github"))).scalar_one_or_none()
            assert conn16 is not None, "Connection must be persisted in DB"
            assert conn16.github_username == "octocat_tester"
            assert conn16.github_user_id == "987654"
        print("Test 16: connection persistence in DB -> PASS")

        # ----------------------------------------------------------------------
        # 17. Token encrypted at rest
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn17 = (await session.execute(select(GitHubConnection).where(GitHubConnection.provider == "github"))).scalar_one()
            assert conn17.encrypted_access_token != "gho_test_token_12345"
            decrypted = decrypt_secret(conn17.encrypted_access_token)
            assert decrypted == "gho_test_token_12345"
        print("Test 17: token encrypted at rest -> PASS")

        # ----------------------------------------------------------------------
        # 18. Plaintext token not persisted
        # ----------------------------------------------------------------------
        async with AsyncSessionLocal() as session:
            conn18 = (await session.execute(select(GitHubConnection).where(GitHubConnection.provider == "github"))).scalar_one()
            assert "gho_" not in conn18.encrypted_access_token
            # Verify no plaintext token in metadata either
            meta_str = json.dumps(conn18.token_metadata or {})
            assert "gho_" not in meta_str
        print("Test 18: plaintext token not persisted -> PASS")

        # ----------------------------------------------------------------------
        # 19. Connection status response excludes token
        # ----------------------------------------------------------------------
        res19 = await client.get("/integrations/github")
        assert res19.status_code == 200
        data19 = res19.json()
        assert data19["connected"] is True
        assert data19["github_username"] == "octocat_tester"
        assert "access_token" not in data19
        assert "encrypted_access_token" not in data19
        assert "token" not in data19
        print("Test 19: connection status response excludes token -> PASS")

        # ----------------------------------------------------------------------
        # 20. Client secret excluded from response
        # ----------------------------------------------------------------------
        resp_text19 = res19.text
        assert "test_github_client_secret" not in resp_text19
        assert "client_secret" not in data19
        print("Test 20: client secret excluded from response -> PASS")

        # ----------------------------------------------------------------------
        # 21. Disconnect removes connection
        # ----------------------------------------------------------------------
        res21 = await client.delete("/integrations/github")
        assert res21.status_code == 200
        assert res21.json()["status"] == "disconnected"

        async with AsyncSessionLocal() as session:
            conn21 = (await session.execute(select(GitHubConnection).where(GitHubConnection.provider == "github"))).scalar_one_or_none()
            assert conn21 is None, "Connection must be removed from DB upon disconnect"

        status21 = (await client.get("/integrations/github")).json()
        assert status21["connected"] is False
        assert status21["github_username"] is None
        print("Test 21: disconnect removes connection -> PASS")

        # ----------------------------------------------------------------------
        # 22. Disconnect is idempotent
        # ----------------------------------------------------------------------
        res22 = await client.delete("/integrations/github")
        assert res22.status_code == 200
        assert res22.json()["status"] == "disconnected"
        print("Test 22: disconnect is idempotent -> PASS")

        # ----------------------------------------------------------------------
        # 23. Duplicate callback handling (re-connect / upsert)
        # ----------------------------------------------------------------------
        app.dependency_overrides[get_github_client] = lambda: mock_gh
        st23_a = generate_oauth_state()
        await store_oauth_state(st23_a)
        client.cookies.set("lens_oauth_state", st23_a)
        await client.get(f"/integrations/github/callback?code=c1&state={st23_a}", follow_redirects=False)

        st23_b = generate_oauth_state()
        await store_oauth_state(st23_b)
        client.cookies.set("lens_oauth_state", st23_b)
        res23_b = await client.get(f"/integrations/github/callback?code=c2&state={st23_b}", follow_redirects=False)
        assert res23_b.status_code in (302, 307)

        async with AsyncSessionLocal() as session:
            all_conns = (await session.execute(select(GitHubConnection).where(GitHubConnection.provider == "github"))).scalars().all()
            assert len(all_conns) == 1, f"Expected exactly 1 connection record after upsert, got {len(all_conns)}"
        print("Test 23: duplicate callback handling -> PASS")

        # ----------------------------------------------------------------------
        # 24. GitHub timeout
        # ----------------------------------------------------------------------
        mock_gh_timeout = AsyncMock()
        mock_gh_timeout.exchange_code_for_token.side_effect = GitHubTimeoutError("Timed out")
        app.dependency_overrides[get_github_client] = lambda: mock_gh_timeout

        st24 = generate_oauth_state()
        await store_oauth_state(st24)
        client.cookies.set("lens_oauth_state", st24)

        res24 = await client.get(f"/integrations/github/callback?code=c24&state={st24}", follow_redirects=False)
        assert res24.status_code == 504, f"Expected 504, got {res24.status_code}"
        assert "timeout" in res24.json()["detail"].lower()
        print("Test 24: GitHub timeout -> PASS")

        # ----------------------------------------------------------------------
        # 25. GitHub provider error
        # ----------------------------------------------------------------------
        mock_gh_500 = AsyncMock()
        mock_gh_500.exchange_code_for_token.side_effect = GitHubApiError("GitHub upstream outage")
        app.dependency_overrides[get_github_client] = lambda: mock_gh_500

        st25 = generate_oauth_state()
        await store_oauth_state(st25)
        client.cookies.set("lens_oauth_state", st25)

        res25 = await client.get(f"/integrations/github/callback?code=c25&state={st25}", follow_redirects=False)
        assert res25.status_code == 502, f"Expected 502, got {res25.status_code}"
        print("Test 25: GitHub provider error -> PASS")

        # ----------------------------------------------------------------------
        # 26. DB failure handling
        # ----------------------------------------------------------------------
        app.dependency_overrides[get_github_client] = lambda: mock_gh
        st26 = generate_oauth_state()
        await store_oauth_state(st26)
        client.cookies.set("lens_oauth_state", st26)

        with patch("app.integrations.github.router.upsert_github_connection", side_effect=RuntimeError("Simulated DB Crash")):
            res26 = await client.get(f"/integrations/github/callback?code=c26&state={st26}", follow_redirects=False)
            assert res26.status_code == 500, f"Expected 500, got {res26.status_code}"
            assert "database" in res26.json()["detail"].lower()
        print("Test 26: DB failure handling -> PASS")

        # ----------------------------------------------------------------------
        # 27. Malicious username safely handled
        # ----------------------------------------------------------------------
        mock_gh_malicious = AsyncMock()
        mock_gh_malicious.exchange_code_for_token.return_value = {
            "access_token": "token27",
            "token_type": "bearer",
            "scope": "read:user",
        }
        mock_gh_malicious.get_authenticated_user.return_value = {
            "id": "112233",
            "login": "scriptalert1scripthacker",
        }
        app.dependency_overrides[get_github_client] = lambda: mock_gh_malicious

        st27 = generate_oauth_state()
        await store_oauth_state(st27)
        client.cookies.set("lens_oauth_state", st27)

        res27 = await client.get(f"/integrations/github/callback?code=c27&state={st27}", follow_redirects=False)
        assert res27.status_code in (302, 307)

        status27 = (await client.get("/integrations/github")).json()
        assert status27["connected"] is True
        assert status27["github_username"] == "scriptalert1scripthacker"
        print("Test 27: malicious username safely handled -> PASS")

        # ----------------------------------------------------------------------
        # 28. Open redirect protection
        # ----------------------------------------------------------------------
        from app.integrations.github.router import _validate_safe_redirect
        assert _validate_safe_redirect("https://evil.com", "http://localhost:3000") is False
        assert _validate_safe_redirect("//evil.com", "http://localhost:3000") is False
        assert _validate_safe_redirect("javascript:alert(1)", "http://localhost:3000") is False
        assert _validate_safe_redirect("/settings", "http://localhost:3000") is True
        assert _validate_safe_redirect("http://localhost:3000/settings", "http://localhost:3000") is True

        res28 = await client.get("/integrations/github/connect?redirect=https://evil.com", follow_redirects=False)
        assert res28.status_code in (302, 307)
        loc28 = res28.headers.get("location", "")
        # GitHub URL must only redirect to configured backend redirect_uri, not evil.com
        assert "evil.com" not in loc28
        print("Test 28: open redirect protection -> PASS")

        # Final cleanup
        app.dependency_overrides.clear()
        await clean_github_connections()

    await close_connections()
    print("\n--- ALL 28 STAGE 13 INTEGRATION TESTS PASSED SUCCESSFULLY ---")


if __name__ == "__main__":
    asyncio.run(run_all_stage13_tests())
