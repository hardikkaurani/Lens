"""Authentication dependencies and token enforcement for FastAPI routes."""

import logging
from typing import Optional
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenSecurityError, decode_access_token
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)

# HTTP Bearer scheme with automatic error suppression so we can raise standardized 401s
http_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    session: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that enforces valid JWT Bearer authentication.

    Extracts token from Authorization header, validates claims, and returns the active User.
    Raises HTTP 401 Unauthorized with WWW-Authenticate header on any failure.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except TokenSecurityError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {e}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from e

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject claim.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    try:
        user_id = uuid.UUID(subject)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user ID in token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from e

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user

