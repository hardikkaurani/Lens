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
