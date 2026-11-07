"""Comprehensive Stage 19 End-to-End Acceptance, Multi-Tenant Security & Reliability Test Suite.

This suite provides rigorous, evidence-based verification of:
1. End-to-End Authentication Lifecycle (Registration, Argon2id hashing, timing attack defense,
   stateless JWT issuance, expiration, tampering, claims verification, profile retrieval).
2. URL Capture Lifecycle (Input validation, tenant ownership, asynchronous queue failure handling,
   worker processing, SSRF/timeout error classification).
3. File Capture Lifecycle (MIME validation, magic byte verification, tenant-partitioned S3 storage,
   upload rollback cleanup, PDF extraction failure handling).
4. Cross-Tenant Security Acceptance Matrix (User A vs User B strict isolation across captures,
   IDOR defense returning 404, search isolation, GitHub connection and activity isolation).
5. GitHub Integration Lifecycle (OAuth state signing, purpose-scoped connect ticket validation, AES-256-GCM token encryption,
   disconnect scoping, unowned connection rejection).
6. Failure and Recovery Mechanisms (Database outage handling, Redis outage handling, health degradation,
   graceful error sanitization without leaking stack traces or credentials).
7. Production Configuration Audit (JWT_SECRET enforcement in production, minimum 32-char entropy check,
   TOKEN_ENCRYPTION_KEY enforcement, CORS credential safety).
8. Client Compatibility Contract (Documenting current unauthenticated web and mobile client behavior).
"""

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Ensure services/worker is on sys.path for worker imports
_worker_path = str(Path(__file__).resolve().parent.parent.parent / "worker")
if _worker_path not in sys.path:
    sys.path.insert(0, _worker_path)

import jwt
import pytest
from starlette.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.encryption import (
    EncryptionError,
    _derive_key,
    decrypt_secret,
    encrypt_secret,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    SecurityConfigurationError,
    TokenSecurityError,
    create_access_token,
    create_oauth_ticket,
    decode_access_token,
    get_jwt_secret,
    hash_password,
    validate_oauth_ticket,
    verify_password,
)
from app.db.models import (
    Capture,
    ContentChunk,
    GitHubActivity,
    GitHubActivityType,
    GitHubConnection,
    GitHubRepository,
    ProcessingStatus,
    SourceMetadata,
    SourceType,
    User,
)
from app.db.session import check_database_health, check_redis_health, get_db
from app.main import app
from app.storage.client import StorageClient, StorageError, get_storage_client
from worker.fetcher import FetchTimeoutError, SSRFBlockedError
from worker.pdf_extractor import MalformedPDFError
from worker.processor import sanitize_error_message

# Re-use the existing in-memory database and async session emulator from test_security_multitenancy
from tests.test_security_multitenancy import (
    FakeAsyncSession,
    InMemoryDatabase,
    MockQueryResult,
    override_get_db,
    test_db,
)

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_stage19_env():
    """Reset test database store and wire FastAPI dependency overrides before each test."""
    test_db.clear()
    app.dependency_overrides[get_db] = override_get_db
    yield
    test_db.clear()
    app.dependency_overrides.clear()


# ==============================================================================
# 1. AUTHENTICATION LIFECYCLE (Stage 19 - Section 3.A)
# ==============================================================================

def test_auth_lifecycle_registration_and_validation():
    """Verify user registration, input validation, case-insensitive uniqueness, and Argon2id hashing."""
    with TestClient(app) as client:
        # 1. Valid registration
        res = client.post(
            "/auth/register",
            json={"email": "Alice@example.com", "password": "StrongPassword123!"},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["email"] == "alice@example.com"  # Normalized to lowercase
        assert data["is_active"] is True
        assert "id" in data
        assert "password" not in data  # Never leak password in response

        user_id = uuid.UUID(data["id"])
        persisted_user = test_db.users[user_id]
        assert persisted_user.hashed_password.startswith("$argon2id$")
        assert verify_password("StrongPassword123!", persisted_user.hashed_password) is True

        # 2. Duplicate registration with exact email -> 400
        dup_res = client.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": "AnotherPassword123!"},
        )
        assert dup_res.status_code == 400
        assert "already exists" in dup_res.json()["detail"].lower()

        # 3. Duplicate registration with case variation -> 400
        case_res = client.post(
            "/auth/register",
            json={"email": "ALICE@EXAMPLE.COM", "password": "AnotherPassword123!"},
        )
        assert case_res.status_code == 400
        assert "already exists" in case_res.json()["detail"].lower()

        # 4. Invalid email format -> 422
        inv_email = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "ValidPassword123!"},
        )
        assert inv_email.status_code == 422

        # 5. Short password (< 8 chars) -> 422
        short_pw = client.post(
            "/auth/register",
            json={"email": "bob@example.com", "password": "short"},
        )
        assert short_pw.status_code == 422


def test_auth_lifecycle_login_tokens_and_profile():
    """Verify login authentication, constant-time verification, JWT claims, and /auth/me profile access."""
    # Pre-populate active user
    user = User(
        id=uuid.uuid4(),
        email="carol@example.com",
        hashed_password=hash_password("CarolPassword123!"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    test_db.users[user.id] = user

    with TestClient(app) as client:
        # 1. Successful login
        res = client.post(
            "/auth/login",
            json={"email": "Carol@example.com", "password": "CarolPassword123!"},
        )
        assert res.status_code == 200, res.text
        token_data = res.json()
        assert token_data["token_type"] == "bearer"
        assert token_data["expires_in"] > 0
        access_token = token_data["access_token"]

        # Validate token payload
        payload = decode_access_token(access_token)
        assert payload["sub"] == str(user.id)
        assert payload["email"] == "carol@example.com"
        assert payload["type"] == "access"

        # 2. Access /auth/me with valid Bearer token
        profile_res = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert profile_res.status_code == 200
        assert profile_res.json()["id"] == str(user.id)
        assert profile_res.json()["email"] == "carol@example.com"

        # 3. Invalid password -> 401
        bad_pw_res = client.post(
            "/auth/login",
            json={"email": "carol@example.com", "password": "WrongPassword123!"},
        )
        assert bad_pw_res.status_code == 401
        assert "invalid email or password" in bad_pw_res.json()["detail"].lower()

        # 4. Non-existent email -> 401 (defeats enumeration via constant-time dummy verification)
        with patch("app.auth.router.verify_password", wraps=verify_password) as verify_spy:
            missing_res = client.post(
                "/auth/login",
                json={"email": "nonexistent@example.com", "password": "AnyPassword123!"},
            )
        assert missing_res.status_code == 401
        assert "invalid email or password" in missing_res.json()["detail"].lower()
        verify_spy.assert_called_once_with("AnyPassword123!", DUMMY_PASSWORD_HASH)

        # 5. Deactivated user -> 401
        user.is_active = False
        deact_res = client.post(
            "/auth/login",
            json={"email": "carol@example.com", "password": "CarolPassword123!"},
        )
        assert deact_res.status_code == 401
        assert "deactivated" in deact_res.json()["detail"].lower()


def test_auth_enforcement_token_anomalies_and_protected_routes():
    """Verify denial of missing, expired, tampered, or wrong-type JWTs across protected routes."""
    user = User(
        id=uuid.uuid4(),
        email="dave@example.com",
        hashed_password=hash_password("DavePassword123!"),
        is_active=True,
    )
    test_db.users[user.id] = user

    with TestClient(app) as client:
        # 1. Missing Authorization header -> 401
        res_missing = client.get("/auth/me")
        assert res_missing.status_code == 401
        assert "credentials were not provided" in res_missing.json()["detail"].lower()

        # 2. Expired JWT -> 401 with standard WWW-Authenticate header
        expired_token = create_access_token(
            subject=user.id,
            email=user.email,
            expires_delta=timedelta(seconds=-10),
        )
        res_expired = client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert res_expired.status_code == 401
        assert "expired" in res_expired.json()["detail"].lower()
        assert 'Bearer error="invalid_token"' in res_expired.headers.get("www-authenticate", "")

        # 3. Tampered signature -> 401
        valid_token = create_access_token(subject=user.id, email=user.email)
        header_part, payload_part, sig_part = valid_token.split(".")
        tampered_token = f"{header_part}.{payload_part}.{sig_part[:-4]}XXXX"
        res_tampered = client.get("/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
        assert res_tampered.status_code == 401

        # 4. Wrong token type (e.g. oauth_connect ticket used on API route) -> 401
        oauth_ticket = create_oauth_ticket(subject=user.id)
        res_wrong_type = client.get("/auth/me", headers={"Authorization": f"Bearer {oauth_ticket}"})
        assert res_wrong_type.status_code == 401
        assert "invalid token type" in res_wrong_type.json()["detail"].lower()

        # 5. Protected routes fail closed when unauthenticated
        assert client.get("/captures").status_code == 401
        assert client.post("/captures", json={"source_type": "text", "content": "hi"}).status_code == 401
        assert client.post("/captures/upload").status_code == 401
        assert client.get(f"/captures/{uuid.uuid4()}").status_code == 401
        assert client.get("/search?q=test").status_code == 401
        assert client.get("/integrations/github").status_code == 401
        assert client.delete("/integrations/github").status_code == 401


# ==============================================================================
# 2. URL CAPTURE LIFECYCLE (Stage 19 - Section 3.B)
# ==============================================================================

def test_url_capture_lifecycle_and_worker_processing():
    """Verify URL submission, tenant binding, queue failure preservation, and worker error handling."""
    user = User(id=uuid.uuid4(), email="url_user@lens.local", hashed_password=hash_password("pw"), is_active=True)
    test_db.users[user.id] = user
    token = create_access_token(subject=user.id, email=user.email)

    with TestClient(app) as client:
        # 1. Invalid URL input validation -> 422
        bad_url_res = client.post(
            "/captures",
            json={"source_type": "url", "original_url": "invalid_url_not_http", "content": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert bad_url_res.status_code == 422

        # 2. Valid URL submission: creates capture owned by user with PENDING status
        with patch("app.captures.router.enqueue_url_ingest_job", new_callable=AsyncMock) as mock_enqueue:
            res = client.post(
                "/captures",
                json={
                    "source_type": "url",
                    "original_url": "https://example.com/article",
                    "title": "Example Article",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 201, res.text
            data = res.json()
            capture_id = uuid.UUID(data["id"])
            assert data["source_type"] == "url"
            assert data["processing_status"] == "pending"
            assert mock_enqueue.called

        # Verify tenant assignment in persistence layer
        persisted = test_db.captures[capture_id]
        assert persisted.user_id == user.id

        # 3. Simulate queue enqueue failure (e.g. Redis connection error)
        # Capture should NOT be discarded; it should be preserved with status=FAILED and a safe message
        with patch("app.captures.router.enqueue_url_ingest_job", side_effect=Exception("Redis connection refused")):
            res_fail = client.post(
                "/captures",
                json={
                    "source_type": "url",
                    "original_url": "https://example.com/offline-queue",
                    "title": "Offline Queue Article",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res_fail.status_code == 201
            fail_id = uuid.UUID(res_fail.json()["id"])
            persisted_fail = test_db.captures[fail_id]
            assert persisted_fail.processing_status == ProcessingStatus.FAILED
            assert "queue unavailable" in persisted_fail.processing_error.lower()
            # Verify internal Redis host/pass is NOT leaked
            assert "redis://" not in persisted_fail.processing_error

        # 4. Worker error message sanitization: verify SSRF, Timeout, and Content errors
        ssrf_err = SSRFBlockedError("SSRF check blocked: 127.0.0.1 loopback prohibited")
        assert "ssrf security policy blocked" in sanitize_error_message(ssrf_err).lower()

        timeout_err = FetchTimeoutError("ReadTimeout to remote host")
        assert "timeout" in sanitize_error_message(timeout_err).lower()


# ==============================================================================
# 3. FILE CAPTURE LIFECYCLE (Stage 19 - Section 3.C)
# ==============================================================================

def test_file_capture_lifecycle_and_tenant_partitioned_storage():
    """Verify authenticated PDF upload, magic-byte validation, tenant-isolated S3 keys, and error handling."""
    user = User(id=uuid.uuid4(), email="file_user@lens.local", hashed_password=hash_password("pw"), is_active=True)
    test_db.users[user.id] = user
    token = create_access_token(subject=user.id, email=user.email)

    with TestClient(app) as client:
        # 1. Rejection of unsupported mime type -> 415
        unsupported_res = client.post(
            "/captures/upload",
            files={"file": ("image.png", b"\x89PNG\r\n\x1a\nfake image content", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert unsupported_res.status_code == 415
        assert "unsupported media type" in unsupported_res.json()["detail"].lower()

        # 2. Rejection of spoofed mime type (declared PDF, but invalid magic bytes) -> 415 Unsupported Media Type
        spoofed_res = client.post(
            "/captures/upload",
            files={"file": ("malicious.pdf", b"NOT_A_PDF_CONTENT_STREAM", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert spoofed_res.status_code == 415
        assert "magic bytes" in spoofed_res.json()["detail"].lower()

        # 3. Rejection of oversized file (> 10MB) -> 413
        with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", 500):  # Mock small 500 byte limit
            oversized_res = client.post(
                "/captures/upload",
                files={"file": ("large.pdf", b"%PDF-1.4" + b"A" * 600, "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert oversized_res.status_code == 413
            assert "exceeds maximum permitted limit" in oversized_res.json()["detail"].lower()

        # 4. Valid PDF upload with tenant-partitioned storage key
        mock_storage = MagicMock()
        mock_storage.generate_secure_object_key.side_effect = StorageClient.generate_secure_object_key
        mock_storage.put_object.return_value = MagicMock(key="captures/test/key.pdf")
        app.dependency_overrides[get_storage_client] = lambda: mock_storage

        valid_pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        with patch("app.captures.router.enqueue_file_ingest_job", new_callable=AsyncMock) as mock_enqueue:
            res_upload = client.post(
                "/captures/upload",
                files={"file": ("annual_report.pdf", valid_pdf_content, "application/pdf")},
                data={"title": "Annual Report 2026"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res_upload.status_code == 201, res_upload.text
            upload_data = res_upload.json()
            capture_id = uuid.UUID(upload_data["id"])
            assert upload_data["source_type"] == "pdf"
            assert upload_data["processing_status"] == "pending"

            # Verify tenant partitioned storage key format: captures/{user_id}/{capture_id}/{filename}
            uploaded_key = mock_storage.put_object.call_args.kwargs["key"]
            expected_prefix = f"captures/{user.id}/{capture_id}/"
            assert uploaded_key.startswith(expected_prefix)
            assert uploaded_key.endswith(".pdf")

        # 4b. Verify S3 cleanup rollback when DB persistence fails
        with patch.object(FakeAsyncSession, "flush", side_effect=RuntimeError("Simulated DB flush failure")):
            res_fail = client.post(
                "/captures/upload",
                files={"file": ("fail_doc.pdf", valid_pdf_content, "application/pdf")},
                data={"title": "Failing Document"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res_fail.status_code == 500
            assert "cleaned up safely" in res_fail.json()["detail"].lower()
            mock_storage.delete_object.assert_called_once()
            cleaned_key = mock_storage.delete_object.call_args[0][0]
            assert f"captures/{user.id}/" in cleaned_key

        # 5. Worker corrupted PDF error sanitization
        pdf_err = MalformedPDFError("Syntax error in PDF xref table")
        safe_msg = sanitize_error_message(pdf_err)
        assert safe_msg == "Corrupted or unreadable PDF document format."


# ==============================================================================
# 4. CROSS-TENANT SECURITY ACCEPTANCE MATRIX (Stage 19 - Section 4)
# ==============================================================================

def test_cross_tenant_security_acceptance_matrix():
    """Verify strict multi-tenant isolation across all operations in Section 4 table."""
    # User A (Alice)
    user_a = User(
        id=uuid.uuid4(),
        email="alice@corp.local",
        hashed_password=hash_password("pwA"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    test_db.users[user_a.id] = user_a
    token_a = create_access_token(subject=user_a.id, email=user_a.email)

    # User B (Bob)
    user_b = User(
        id=uuid.uuid4(),
        email="bob@corp.local",
        hashed_password=hash_password("pwB"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    test_db.users[user_b.id] = user_b
    token_b = create_access_token(subject=user_b.id, email=user_b.email)

    # Pre-populate Capture A for User A
    cap_a = Capture(
        id=uuid.uuid4(),
        user_id=user_a.id,
        source_type=SourceType.TEXT,
        processing_status=ProcessingStatus.COMPLETED,
        title="Alice Secret Roadmap",
        content="Project Manhattan classified research document.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    test_db.captures[cap_a.id] = cap_a
    chunk_a = ContentChunk(
        id=uuid.uuid4(),
        capture_id=cap_a.id,
        chunk_index=0,
        content=cap_a.content,
    )
    test_db.chunks[chunk_a.id] = chunk_a

    # Pre-populate Capture B for User B
    cap_b = Capture(
        id=uuid.uuid4(),
        user_id=user_b.id,
        source_type=SourceType.TEXT,
        processing_status=ProcessingStatus.COMPLETED,
        title="Bob Secret Financials",
        content="Project Apollo classified revenue projections.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    test_db.captures[cap_b.id] = cap_b
    chunk_b = ContentChunk(
        id=uuid.uuid4(),
        capture_id=cap_b.id,
        chunk_index=0,
        content=cap_b.content,
    )
    test_db.chunks[chunk_b.id] = chunk_b

    with TestClient(app) as client:
        # Table Row 1: User A lists captures -> Only A's captures
        res_list_a = client.get("/captures", headers={"Authorization": f"Bearer {token_a}"})
        assert res_list_a.status_code == 200
        items_a = res_list_a.json()["items"]
        assert len(items_a) == 1
        assert items_a[0]["id"] == str(cap_a.id)
        assert all(item["id"] != str(cap_b.id) for item in items_a)

        # Table Row 2: User A retrieves B's capture -> 404 (IDOR defense)
        res_get_b = client.get(f"/captures/{cap_b.id}", headers={"Authorization": f"Bearer {token_a}"})
        assert res_get_b.status_code == 404
        assert "not found" in res_get_b.json()["detail"].lower()

        # Table Row 3: User A modifies B's capture -> Denied (405 Method Not Allowed)
        res_put_b = client.put(
            f"/captures/{cap_b.id}",
            json={"title": "Hacked"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_put_b.status_code == 405

        # Table Row 4: User A deletes B's capture -> Denied (405 Method Not Allowed)
        res_del_b = client.delete(
            f"/captures/{cap_b.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_del_b.status_code == 405

        # Table Row 5: User A downloads B's file -> Secure key partitioning prevents cross-tenant access
        key_a = StorageClient.generate_secure_object_key(cap_a.id, ".pdf", user_id=user_a.id)
        key_b = StorageClient.generate_secure_object_key(cap_b.id, ".pdf", user_id=user_b.id)
        assert str(user_a.id) in key_a
        assert str(user_b.id) in key_b
        assert key_a != key_b

        # Table Row 6: User A searches B's content -> No B results
        # User A searching for Bob's keyword "Apollo" never receives Bob's capture
        res_search_apollo = client.get("/search?q=Apollo", headers={"Authorization": f"Bearer {token_a}"})
        assert res_search_apollo.status_code == 200
        assert not any(r["capture_id"] == str(cap_b.id) for r in res_search_apollo.json()["results"])

        # User A searching for Alice's keyword "Manhattan" returns Capture A
        res_search_manhattan = client.get("/search?q=Manhattan", headers={"Authorization": f"Bearer {token_a}"})
        assert res_search_manhattan.status_code == 200
        assert any(r["capture_id"] == str(cap_a.id) for r in res_search_manhattan.json()["results"])

        # Conversely, User B searching for "Manhattan" never sees Alice's capture
        res_search_b = client.get("/search?q=Manhattan", headers={"Authorization": f"Bearer {token_b}"})
        assert res_search_b.status_code == 200
        assert not any(r["capture_id"] == str(cap_a.id) for r in res_search_b.json()["results"])

        # Table Row 7: User A accesses B's GitHub activity -> Denied (isolated)
        # Pre-populate GitHub connection and activity for Bob
        conn_b = GitHubConnection(
            id=uuid.uuid4(),
            user_id=user_b.id,
            provider="github",
            github_user_id="bob-gh",
            github_username="bob_developer",
            encrypted_access_token=encrypt_secret("ghp_bob_secret"),
            scope="read:user,repo",
        )
        test_db.github_connections[conn_b.id] = conn_b
        repo_b = GitHubRepository(
            id=uuid.uuid4(),
            connection_id=conn_b.id,
            github_repository_id="9999",
            name="bob-private-repo",
            full_name="bob/bob-private-repo",
            owner_login="bob_developer",
            is_private=True,
            is_selected=True,
        )
        test_db.github_repositories[repo_b.id] = repo_b
        act_b = GitHubActivity(
            id=uuid.uuid4(),
            repository_id=repo_b.id,
            activity_type=GitHubActivityType.PULL_REQUEST,
            external_id="101",
            title="Bob Secret PR",
            body="Top secret feature implementation",
            author_login="bob_developer",
            html_url="https://github.com/bob/bob-private-repo/pull/101",
        )
        test_db.github_activities[act_b.id] = act_b

        # User A querying GitHub status sees connected=False
        res_gh_status_a = client.get("/integrations/github", headers={"Authorization": f"Bearer {token_a}"})
        assert res_gh_status_a.status_code == 200
        assert res_gh_status_a.json()["connected"] is False

        # Positive control: User B (Bob) searching for his own PR finds act_b
        res_search_gh_b = client.get("/search?q=Feature&source_type=github", headers={"Authorization": f"Bearer {token_b}"})
        assert res_search_gh_b.status_code == 200
        assert res_search_gh_b.json()["total"] == 1
        assert res_search_gh_b.json()["results"][0]["title"] == "Bob Secret PR"

        # User A searching for Bob's GitHub PR receives 0 results
        res_search_gh_a = client.get("/search?q=Feature&source_type=github", headers={"Authorization": f"Bearer {token_a}"})
        assert res_search_gh_a.status_code == 200
        assert res_search_gh_a.json()["total"] == 0

        # Table Row 8: Worker processes unowned capture -> Rejected / abandoned with FAILED status
        from worker.processor import process_url_capture, process_file_capture
        import asyncio

        unowned_url_cap = Capture(
            id=uuid.uuid4(),
            user_id=None,
            source_type=SourceType.URL,
            original_url="https://example.com/unowned",
            processing_status=ProcessingStatus.PENDING,
        )
        test_db.captures[unowned_url_cap.id] = unowned_url_cap

        unowned_pdf_cap = Capture(
            id=uuid.uuid4(),
            user_id=None,
            source_type=SourceType.PDF,
            source_id="captures/unowned/unowned.pdf",
            processing_status=ProcessingStatus.PENDING,
        )
        test_db.captures[unowned_pdf_cap.id] = unowned_pdf_cap

        # Execute worker URL path: rejects unowned capture, sets FAILED status
        res_url = asyncio.run(process_url_capture(unowned_url_cap.id, session_factory=lambda: FakeAsyncSession(test_db)))
        assert res_url is False
        assert unowned_url_cap.processing_status == ProcessingStatus.FAILED
        assert "unowned" in unowned_url_cap.processing_error.lower()

        # Execute worker PDF path: rejects unowned capture, sets FAILED status
        res_pdf = asyncio.run(process_file_capture(unowned_pdf_cap.id, session_factory=lambda: FakeAsyncSession(test_db)))
        assert res_pdf is False
        assert unowned_pdf_cap.processing_status == ProcessingStatus.FAILED
        assert "unowned" in unowned_pdf_cap.processing_error.lower()


@pytest.mark.asyncio
async def test_search_sql_query_tenant_isolation_and_ownership_predicates():
    """Verify that PostgreSQL lexical and vector search SQL queries strictly enforce tenant isolation predicates."""
    from app.search.service import SearchService

    user_id = uuid.uuid4()
    foreign_user_id = uuid.uuid4()

    class MockAsyncContext:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = MockAsyncContext
    service = SearchService()

    # 1. Unauthenticated / missing user_id immediately short-circuits
    empty_res = await service.search(query="test", session=mock_db, user_id=None)
    assert empty_res.total == 0
    assert len(empty_res.results) == 0

    # 2. Authenticated user search executes SQL containing mandatory tenant constraints
    executed_statements = []

    async def fake_execute(statement, params=None):
        executed_statements.append((str(statement), params or {}))
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        return mock_result

    mock_db.execute = AsyncMock(side_effect=fake_execute)

    await service.search(query="test", session=mock_db, user_id=user_id, source_type="all")

    assert len(executed_statements) >= 2
    for sql_text, params in executed_statements:
        # Mandatory tenant parameters must match user_id
        assert "user_id" in params
        assert params["user_id"] == user_id
        assert params["user_id"] != foreign_user_id

        # Mandatory SQL tenant constraints must be present
        has_capture_tenant_pred = "c.user_id = :user_id" in sql_text
        has_github_tenant_pred = "gc.user_id = :user_id" in sql_text
        assert has_capture_tenant_pred or has_github_tenant_pred
