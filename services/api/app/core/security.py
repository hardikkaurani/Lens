"""Core cryptographic security services for authentication and multi-tenancy.

Provides:
1. Argon2id password hashing and verification (OWASP recommended standard).
2. Stateless JWT access token generation and validation (HS256).
3. Secure random generation and constant-time comparisons.
"""

from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Any, Optional
import uuid

import argon2
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
import jwt

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Fallback development secret key (at least 256 bits / 32 bytes)
_DEV_JWT_SECRET = "lens-development-jwt-secret-key-32-bytes-minimum-security-entropy-v1"

# OWASP Recommended Argon2id parameters
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# Constant-time dummy hash used to eliminate timing side-channels during login
DUMMY_PASSWORD_HASH = _password_hasher.hash("lens-timing-defense-dummy-password")


class SecurityConfigurationError(Exception):
    """Raised when critical security settings are missing or misconfigured in production."""
    pass


class TokenSecurityError(Exception):
    """Raised when token validation or claims verification fails."""
    pass


def get_jwt_secret() -> str:
    """Retrieve and validate the JWT secret key.

    In production (APP_ENV == 'production'), JWT_SECRET must be explicitly configured
    and at least 32 characters long.
    """
    settings = get_settings()
    is_production = settings.APP_ENV == "production"
    env_secret = settings.JWT_SECRET

    if env_secret and env_secret.strip():
        secret = env_secret.strip()
        if len(secret) < 32:
            raise SecurityConfigurationError("JWT_SECRET must be at least 32 characters long for cryptographic security.")
        return secret

    if is_production:
        raise SecurityConfigurationError("JWT_SECRET must be configured in production environment.")

    return _DEV_JWT_SECRET


def hash_password(plain_password: str) -> str:
    """Hash a plain text password using Argon2id."""
    if not plain_password:
        raise ValueError("Password cannot be empty.")
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against an Argon2id hash in constant time."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(
    subject: str | uuid.UUID,
    email: str,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    """Generate a signed stateless JWT access token.

    Encodes claims:
    - sub: Subject UUID string
    - email: User's email
    - iat: Issued-at timestamp (UTC)
    - exp: Expiration timestamp (UTC)
    - type: "access"
    """
    settings = get_settings()
    secret = get_jwt_secret()
    algorithm = settings.JWT_ALGORITHM or "HS256"

    now_utc = datetime.now(timezone.utc)
    if expires_delta:
        expire_utc = now_utc + expires_delta
    else:
        expire_utc = now_utc + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "email": email,
        "iat": int(now_utc.timestamp()),
        "exp": int(expire_utc.timestamp()),
        "type": "access",
    }

    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and cryptographically verify a JWT access token.

    Validates signature, expiration, and ensures type == "access".
    Raises TokenSecurityError on any validation failure.
    """
    settings = get_settings()
    secret = get_jwt_secret()
    algorithm = settings.JWT_ALGORITHM or "HS256"

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={
                "require": ["sub", "exp", "iat", "type"],
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenSecurityError("Token has expired.") from e
    except jwt.InvalidTokenError as e:
        raise TokenSecurityError(f"Invalid token: {e}") from e

    token_type = payload.get("type")
    if token_type != "access":
        raise TokenSecurityError(f"Invalid token type: expected 'access', got '{token_type}'")

    return payload


def create_oauth_ticket(subject: str | uuid.UUID, expires_seconds: int = 60) -> str:
    """Generate a short-lived (default 60s), purpose-scoped OAuth connect ticket.

    Used exclusively for top-level browser navigation handoff so long-lived access JWTs
    are never leaked into URL query strings, server logs, or Referer headers.
    """
    settings = get_settings()
    secret = get_jwt_secret()
    algorithm = settings.JWT_ALGORITHM or "HS256"

    now_utc = datetime.now(timezone.utc)
    expire_utc = now_utc + timedelta(seconds=expires_seconds)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now_utc.timestamp()),
        "exp": int(expire_utc.timestamp()),
        "type": "oauth_connect",
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def validate_oauth_ticket(ticket: str) -> uuid.UUID:
    """Decode and verify a purpose-scoped OAuth connect ticket.

    Enforces strict signature verification, expiration, and ensures type == 'oauth_connect'.
    """
    settings = get_settings()
    secret = get_jwt_secret()
    algorithm = settings.JWT_ALGORITHM or "HS256"

    try:
        payload = jwt.decode(
            ticket,
            secret,
            algorithms=[algorithm],
            options={
                "require": ["sub", "exp", "iat", "type"],
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenSecurityError("OAuth connect ticket has expired.") from e
    except jwt.InvalidTokenError as e:
        raise TokenSecurityError(f"Invalid OAuth connect ticket: {e}") from e

    token_type = payload.get("type")
    if token_type != "oauth_connect":
        raise TokenSecurityError(
            f"Invalid ticket type: expected 'oauth_connect', got '{token_type}'. Reusable access tokens cannot be passed in URLs."
        )

    try:
        return uuid.UUID(payload["sub"])
    except (ValueError, TypeError) as e:
        raise TokenSecurityError("Malformed subject in OAuth connect ticket.") from e

