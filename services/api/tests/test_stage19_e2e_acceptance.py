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
