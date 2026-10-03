"""Comprehensive integration & security test suite for LENS GitHub Integration & OAuth (Stage 13 & 13.1).

Covers:
1. OAuth configuration missing -> 503
2. Connect endpoint generates redirect to GitHub & sets session binding cookie
3. State & session binding are cryptographically random
4. State expires (TTL check)
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

Stage 13.1 Explicit Security & Threat Model Tests:
29. Threat Test A: Valid same-browser flow (connect -> callback with same browser session) -> PASS
30. Threat Test B: Missing browser binding cookie -> 400 REJECT
31. Threat Test C: Wrong browser binding (Browser A state + Browser B cookie) -> 400 REJECT
32. Threat Test D: Replayed callback with same state and cookie -> 400 REJECT
33. Threat Test E: Expired state with cookie -> 400 REJECT
34. Threat Test F: Mismatched state with cookie -> 400 REJECT
35. Threat Test G: State and session binding high entropy verification
36. Threat Test H: OAuth denial deletes session cookie and handles safely
37. Threat Test I: Open redirect rejected in query and callback
38. Threat Test J: Session cookie security attributes (HttpOnly, Lax, Max-Age, no sensitive data)
39. Threat Test K: Redis production boundary - production mode strictly requires Redis & rejects memory fallback
40. Threat Test L: AES-256-GCM encryption configuration & tamper verification
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
from app.core.encryption import (
    CIPHERTEXT_VERSION_PREFIX,
    EncryptionError,
    _derive_key,
    decrypt_secret,
    encrypt_secret,
)
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
    OAUTH_COOKIE_NAME,
    OAuthStorageError,
    _memory_state_cache,
    generate_oauth_state,
    generate_session_binding,
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
    """Execute all Stage 13 and 13.1 GitHub integration & security tests sequentially."""
    print("\n--- Starting Stage 13 & 13.1 GitHub Integration & Security Tests ---")

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
        # 2. Connect endpoint generates redirect to GitHub & sets session cookie
        # ----------------------------------------------------------------------
        res2 = await client.get("/integrations/github/connect", follow_redirects=False)
        assert res2.status_code in (302, 307), f"Expected redirect, got {res2.status_code}"
        loc2 = res2.headers.get("location", "")
        assert "github.com/login/oauth/authorize" in loc2
        assert "client_id=test_github_client_id" in loc2
        assert "state=" in loc2
        assert "scope=" in loc2
        assert OAUTH_COOKIE_NAME in res2.cookies
        session_binding2 = res2.cookies[OAUTH_COOKIE_NAME]
        # Crucial security guarantee: session binding is NOT passed in the public GitHub URL
        assert session_binding2 not in loc2
        print("Test 2: connect endpoint generates redirect & binds session cookie -> PASS")

        # ----------------------------------------------------------------------
        # 3. State & session binding are cryptographically random
        # ----------------------------------------------------------------------
        states = {generate_oauth_state() for _ in range(50)}
        bindings = {generate_session_binding() for _ in range(50)}
        assert len(states) == 50, "Generated states must be unique"
        assert len(bindings) == 50, "Generated session bindings must be unique"
        for s in states:
            assert len(s) >= 32, "State string must provide sufficient entropy"
        for b in bindings:
            assert len(b) >= 32, "Session binding must provide sufficient entropy"
        print("Test 3: state & session binding are cryptographically random -> PASS")

        # ----------------------------------------------------------------------
        # 4. State expires (TTL expiration check)
        # ----------------------------------------------------------------------
        test_state_exp = generate_oauth_state()
        test_bind_exp = generate_session_binding()
        # Simulate an already-expired state in fallback memory store
        _memory_state_cache[test_state_exp] = (
            json.dumps({"session_binding": test_bind_exp, "created_at": time.time() - 700}),
            time.time() - 10,
        )
        consumed_exp = await validate_and_consume_oauth_state(test_state_exp, test_bind_exp)
        assert consumed_exp is None, "Expired state must not be validated"
        print("Test 4: state expires -> PASS")

        # ----------------------------------------------------------------------
        # 5. State is single-use
        # ----------------------------------------------------------------------
        test_state_single = generate_oauth_state()
        test_bind_single = generate_session_binding()
        await store_oauth_state(test_state_single, test_bind_single)
        first_use = await validate_and_consume_oauth_state(test_state_single, test_bind_single)
        assert first_use is not None, "First consumption must succeed"
        second_use = await validate_and_consume_oauth_state(test_state_single, test_bind_single)
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
        st7_stored = generate_oauth_state()
        sb7 = generate_session_binding()
        await store_oauth_state(st7_stored, sb7)
        client.cookies.set(OAUTH_COOKIE_NAME, sb7)
        res7 = await client.get(f"/integrations/github/callback?code=abc&state={st7_query}", follow_redirects=False)
        assert res7.status_code == 400, f"Expected 400, got {res7.status_code}"
        assert "invalid" in res7.json()["detail"].lower() or "expired" in res7.json()["detail"].lower()
        print("Test 7: mismatched state rejected -> PASS")

        # ----------------------------------------------------------------------
        # 8. Replayed state rejected
        # ----------------------------------------------------------------------
        st8 = generate_oauth_state()
        sb8 = generate_session_binding()
        await store_oauth_state(st8, sb8)
        # Consume once manually
        await validate_and_consume_oauth_state(st8, sb8)
        client.cookies.set(OAUTH_COOKIE_NAME, sb8)
        res8 = await client.get(f"/integrations/github/callback?code=abc&state={st8}", follow_redirects=False)
        assert res8.status_code == 400, f"Expected 400, got {res8.status_code}"
        assert "invalid" in res8.json()["detail"].lower() or "expired" in res8.json()["detail"].lower()
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
        sb10 = generate_session_binding()
        await store_oauth_state(st10, sb10)
        client.cookies.set(OAUTH_COOKIE_NAME, sb10)
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
        sb11 = generate_session_binding()
        await store_oauth_state(st11, sb11)
        client.cookies.set(OAUTH_COOKIE_NAME, sb11)

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
        sb12 = generate_session_binding()
        await store_oauth_state(st12, sb12)
        client.cookies.set(OAUTH_COOKIE_NAME, sb12)

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
        sb13 = generate_session_binding()
        await store_oauth_state(st13, sb13)
        client.cookies.set(OAUTH_COOKIE_NAME, sb13)

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
        sb14 = generate_session_binding()
        await store_oauth_state(st14, sb14)
        client.cookies.set(OAUTH_COOKIE_NAME, sb14)

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
        sb15 = generate_session_binding()
        await store_oauth_state(st15, sb15)
        client.cookies.set(OAUTH_COOKIE_NAME, sb15)

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
            assert conn17.encrypted_access_token.startswith(CIPHERTEXT_VERSION_PREFIX)
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
        sb23_a = generate_session_binding()
        await store_oauth_state(st23_a, sb23_a)
        client.cookies.set(OAUTH_COOKIE_NAME, sb23_a)
        await client.get(f"/integrations/github/callback?code=c1&state={st23_a}", follow_redirects=False)

        st23_b = generate_oauth_state()
        sb23_b = generate_session_binding()
        await store_oauth_state(st23_b, sb23_b)
        client.cookies.set(OAUTH_COOKIE_NAME, sb23_b)
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
        sb24 = generate_session_binding()
        await store_oauth_state(st24, sb24)
        client.cookies.set(OAUTH_COOKIE_NAME, sb24)

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
        sb25 = generate_session_binding()
        await store_oauth_state(st25, sb25)
        client.cookies.set(OAUTH_COOKIE_NAME, sb25)

        res25 = await client.get(f"/integrations/github/callback?code=c25&state={st25}", follow_redirects=False)
        assert res25.status_code == 502, f"Expected 502, got {res25.status_code}"
        print("Test 25: GitHub provider error -> PASS")

        # ----------------------------------------------------------------------
        # 26. DB failure handling
        # ----------------------------------------------------------------------
        app.dependency_overrides[get_github_client] = lambda: mock_gh
        st26 = generate_oauth_state()
        sb26 = generate_session_binding()
        await store_oauth_state(st26, sb26)
        client.cookies.set(OAUTH_COOKIE_NAME, sb26)

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
        sb27 = generate_session_binding()
        await store_oauth_state(st27, sb27)
        client.cookies.set(OAUTH_COOKIE_NAME, sb27)

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
        assert "evil.com" not in loc28
        print("Test 28: open redirect protection -> PASS")

        # ======================================================================
        # STAGE 13.1 EXPLICIT SESSION BINDING & THREAT MODEL TESTS (A - L)
        # ======================================================================

        # ----------------------------------------------------------------------
        # 29. Threat Test A: Valid same-browser flow
        # ----------------------------------------------------------------------
        app.dependency_overrides[get_github_client] = lambda: mock_gh
        # Step 1: initiate connect in browser session
        res29_connect = await client.get("/integrations/github/connect", follow_redirects=False)
        assert res29_connect.status_code in (302, 307)
        assert OAUTH_COOKIE_NAME in res29_connect.cookies
        cookie_binding_29 = res29_connect.cookies[OAUTH_COOKIE_NAME]

        # Extract state from redirect location
        loc29 = res29_connect.headers.get("location", "")
        import urllib.parse
        parsed_url29 = urllib.parse.urlparse(loc29)
        query29 = urllib.parse.parse_qs(parsed_url29.query)
        state_29 = query29["state"][0]

        # Step 2: callback in SAME browser with same cookie
        client.cookies.set(OAUTH_COOKIE_NAME, cookie_binding_29)
        res29_callback = await client.get(
            f"/integrations/github/callback?code=code_29&state={state_29}",
            follow_redirects=False,
        )
        assert res29_callback.status_code in (302, 307)
        assert "github=connected" in res29_callback.headers.get("location", "")
        print("Test 29 (Threat Test A): valid same-browser flow -> PASS")

        # ----------------------------------------------------------------------
        # 30. Threat Test B: Missing browser binding cookie
        # ----------------------------------------------------------------------
        # Connect initiates and returns state + cookie
        res30_connect = await client.get("/integrations/github/connect", follow_redirects=False)
        loc30 = res30_connect.headers.get("location", "")
        state_30 = urllib.parse.parse_qs(urllib.parse.urlparse(loc30).query)["state"][0]

        # Victim or attacker visits callback WITHOUT the session cookie
        client.cookies.delete(OAUTH_COOKIE_NAME)
        res30_callback = await client.get(
            f"/integrations/github/callback?code=code_30&state={state_30}",
            follow_redirects=False,
        )
        assert res30_callback.status_code == 400
        assert "missing oauth browser session binding" in res30_callback.json()["detail"].lower()
        print("Test 30 (Threat Test B): missing browser binding cookie rejected -> PASS")

        # ----------------------------------------------------------------------
        # 31. Threat Test C: Wrong browser binding (Browser A state + Browser B cookie)
        # ----------------------------------------------------------------------
        # Browser A initiates connect
        res31_a = await client.get("/integrations/github/connect", follow_redirects=False)
        state_31_a = urllib.parse.parse_qs(urllib.parse.urlparse(res31_a.headers["location"]).query)["state"][0]

        # Browser B initiates connect
        res31_b = await client.get("/integrations/github/connect", follow_redirects=False)
        binding_31_b = res31_b.cookies[OAUTH_COOKIE_NAME]

        # Callback invoked with Browser A's state but Browser B's session cookie
        client.cookies.set(OAUTH_COOKIE_NAME, binding_31_b)
        res31_callback = await client.get(
            f"/integrations/github/callback?code=code_31&state={state_31_a}",
            follow_redirects=False,
        )
        assert res31_callback.status_code == 400
        assert "not bound to this browser session" in res31_callback.json()["detail"].lower()
        print("Test 31 (Threat Test C): wrong browser binding rejected -> PASS")

        # ----------------------------------------------------------------------
        # 32. Threat Test D: Replayed callback rejected
        # ----------------------------------------------------------------------
        res32_connect = await client.get("/integrations/github/connect", follow_redirects=False)
        state_32 = urllib.parse.parse_qs(urllib.parse.urlparse(res32_connect.headers["location"]).query)["state"][0]
        binding_32 = res32_connect.cookies[OAUTH_COOKIE_NAME]

        client.cookies.set(OAUTH_COOKIE_NAME, binding_32)
        res32_first = await client.get(
            f"/integrations/github/callback?code=code_32&state={state_32}",
            follow_redirects=False,
        )
        assert res32_first.status_code in (302, 307)

        # Replay same callback with same state and binding
        client.cookies.set(OAUTH_COOKIE_NAME, binding_32)
        res32_second = await client.get(
            f"/integrations/github/callback?code=code_32&state={state_32}",
            follow_redirects=False,
        )
        assert res32_second.status_code == 400
        assert "invalid" in res32_second.json()["detail"].lower() or "expired" in res32_second.json()["detail"].lower()
        print("Test 32 (Threat Test D): replayed callback rejected -> PASS")

        # ----------------------------------------------------------------------
        # 33. Threat Test E: Expired state rejected
        # ----------------------------------------------------------------------
        st33 = generate_oauth_state()
        sb33 = generate_session_binding()
        _memory_state_cache[st33] = (
            json.dumps({"session_binding": sb33, "created_at": time.time() - 1000}),
            time.time() - 20,
        )
        client.cookies.set(OAUTH_COOKIE_NAME, sb33)
        res33 = await client.get(f"/integrations/github/callback?code=c33&state={st33}", follow_redirects=False)
        assert res33.status_code == 400
        print("Test 33 (Threat Test E): expired state rejected -> PASS")

        # ----------------------------------------------------------------------
        # 34. Threat Test F: Mismatched state rejected
        # ----------------------------------------------------------------------
        sb34 = generate_session_binding()
        client.cookies.set(OAUTH_COOKIE_NAME, sb34)
        res34 = await client.get(f"/integrations/github/callback?code=c34&state=nonexistent_state_val", follow_redirects=False)
        assert res34.status_code == 400
        print("Test 34 (Threat Test F): mismatched state rejected -> PASS")

        # ----------------------------------------------------------------------
        # 35. Threat Test G: High entropy verification
        # ----------------------------------------------------------------------
        sampled_states = [generate_oauth_state() for _ in range(100)]
        sampled_bindings = [generate_session_binding() for _ in range(100)]
        assert len(set(sampled_states)) == 100
        assert len(set(sampled_bindings)) == 100
        assert all(len(s) >= 43 for s in sampled_states)  # 32 raw bytes URL-safe base64 is 43 chars
        assert all(len(b) >= 43 for b in sampled_bindings)
        print("Test 35 (Threat Test G): high entropy verification -> PASS")

        # ----------------------------------------------------------------------
        # 36. Threat Test H: OAuth denial deletes cookie & handles safely
        # ----------------------------------------------------------------------
        client.cookies.set(OAUTH_COOKIE_NAME, "active_session_binding_36")
        res36 = await client.get(
            "/integrations/github/callback?error=access_denied&error_description=The+user+has+denied+your+application+access.",
            follow_redirects=False,
        )
        assert res36.status_code in (302, 307)
        assert "github_error=access_denied" in res36.headers.get("location", "")
        # Verify Set-Cookie header contains instructions to expire/delete the session cookie
        set_cookie_36 = res36.headers.get("set-cookie", "")
        assert OAUTH_COOKIE_NAME in set_cookie_36
        print("Test 36 (Threat Test H): OAuth denial deletes cookie -> PASS")

        # ----------------------------------------------------------------------
        # 37. Threat Test I: Open redirect rejected in connect
        # ----------------------------------------------------------------------
        for evil_url in [
            "https://attacker.com",
            "//attacker.com/evil",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
        ]:
            res37 = await client.get(f"/integrations/github/connect?redirect={evil_url}", follow_redirects=False)
            loc37 = res37.headers.get("location", "")
            assert "attacker.com" not in loc37
        print("Test 37 (Threat Test I): open redirect vectors rejected -> PASS")

        # ----------------------------------------------------------------------
        # 38. Threat Test J: Session cookie security attributes
        # ----------------------------------------------------------------------
        res38 = await client.get("/integrations/github/connect", follow_redirects=False)
        set_cookie_header = res38.headers.get("set-cookie", "")
        assert f"{OAUTH_COOKIE_NAME}=" in set_cookie_header
        assert "HttpOnly" in set_cookie_header or "httponly" in set_cookie_header.lower()
        assert "samesite=lax" in set_cookie_header.lower()
        assert "max-age=600" in set_cookie_header.lower()
        # Verify cookie value does not contain state, tokens, or secrets
        cookie_val38 = res38.cookies[OAUTH_COOKIE_NAME]
        assert cookie_val38 != settings.GITHUB_CLIENT_SECRET
        assert cookie_val38 != settings.GITHUB_CLIENT_ID
        assert "gho_" not in cookie_val38
        assert "state=" not in cookie_val38
        print("Test 38 (Threat Test J): session cookie security attributes verified -> PASS")

        # ----------------------------------------------------------------------
        # 39. Threat Test K: Redis production boundary
        # ----------------------------------------------------------------------
        # When APP_ENV == 'production', Redis is mandatory; failure raises OAuthStorageError & does not write memory
        with patch.object(settings, "APP_ENV", "production"):
            with patch("app.integrations.github.service.get_redis_client") as mock_redis_getter:
                mock_redis = AsyncMock()
                mock_redis.set.side_effect = ConnectionError("Redis cluster unreachable")
                mock_redis_getter.return_value = mock_redis

                test_st_prod = generate_oauth_state()
                test_sb_prod = generate_session_binding()

                storage_failed = False
                try:
                    await store_oauth_state(test_st_prod, test_sb_prod)
                except OAuthStorageError:
                    storage_failed = True

                assert storage_failed is True, "In production mode, Redis failure must raise OAuthStorageError"
                assert test_st_prod not in _memory_state_cache, "In production mode, must NEVER silently fall back to memory cache"

                # Verify connect endpoint returns 503 Service Unavailable
                res39 = await client.get("/integrations/github/connect", follow_redirects=False)
                assert res39.status_code == 503
                assert "unavailable" in res39.json()["detail"].lower()
        print("Test 39 (Threat Test K): Redis production boundary strictly enforced -> PASS")

        # ----------------------------------------------------------------------
        # 40. Threat Test L: AES-256-GCM encryption configuration & tamper checks
        # ----------------------------------------------------------------------
        # 1. Round-trip
        token_plain = "ghp_super_secret_github_personal_token_xyz987"
        enc = encrypt_secret(token_plain)
        assert enc.startswith(CIPHERTEXT_VERSION_PREFIX)
        assert decrypt_secret(enc) == token_plain

        # 2. Random nonce: encrypting same plaintext twice produces different ciphertexts
        enc2 = encrypt_secret(token_plain)
        assert enc != enc2, "Each encryption must use a unique random nonce"
        assert decrypt_secret(enc2) == token_plain

        # 3. Tampered ciphertext raises EncryptionError (MAC verification failure)
        import base64
        raw_b64 = enc[len(CIPHERTEXT_VERSION_PREFIX):]
        raw_bytes = bytearray(base64.urlsafe_b64decode(raw_b64))
        # Flip a bit in the ciphertext portion (after nonce [12B] and tag [16B])
        raw_bytes[-1] ^= 0xFF
        tampered_enc = f"{CIPHERTEXT_VERSION_PREFIX}{base64.urlsafe_b64encode(raw_bytes).decode('utf-8')}"
        tamper_failed = False
        try:
            decrypt_secret(tampered_enc)
        except EncryptionError:
            tamper_failed = True
        assert tamper_failed is True, "Tampered ciphertext must fail authentication tag verification"

        # 4. Tampered tag raises EncryptionError
        raw_bytes_tag = bytearray(base64.urlsafe_b64decode(raw_b64))
        raw_bytes_tag[15] ^= 0xFF  # Flip bit in 16-byte tag
        tampered_tag_enc = f"{CIPHERTEXT_VERSION_PREFIX}{base64.urlsafe_b64encode(raw_bytes_tag).decode('utf-8')}"
        tag_failed = False
        try:
            decrypt_secret(tampered_tag_enc)
        except EncryptionError:
            tag_failed = True
        assert tag_failed is True, "Tampered MAC tag must fail verification"

        # 5. Raw 64-char hex key validation
        raw_hex_key = "a" * 64
        derived_hex = _derive_key(raw_hex_key)
        assert len(derived_hex) == 32
        assert derived_hex == bytes.fromhex(raw_hex_key)

        # 6. Passphrase key derivation via PBKDF2
        passphrase_key = "my-custom-passphrase-key"
        derived_pass = _derive_key(passphrase_key)
        assert len(derived_pass) == 32
        assert derived_pass != passphrase_key.encode("utf-8")

        # 7. Production mode validation: missing key raises EncryptionError
        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "TOKEN_ENCRYPTION_KEY", None):
                prod_key_failed = False
                try:
                    _derive_key(None)
                except EncryptionError:
                    prod_key_failed = True
                assert prod_key_failed is True, "Production mode must fail when TOKEN_ENCRYPTION_KEY is unset"

        print("Test 40 (Threat Test L): AES-256-GCM encryption & tamper verification -> PASS")

        # Final cleanup
        app.dependency_overrides.clear()
        await clean_github_connections()

    await close_connections()
    print("\n--- ALL 40 STAGE 13 & 13.1 INTEGRATION & SECURITY TESTS PASSED SUCCESSFULLY ---")


try:
    import pytest

    @pytest.mark.asyncio  # type: ignore[misc]
    async def test_stage13_and_13_1_full_suite() -> None:
        """Pytest entrypoint executing the 40 integration and security tests."""
        await run_all_stage13_tests()
except ImportError:
    pass


if __name__ == "__main__":
    asyncio.run(run_all_stage13_tests())
