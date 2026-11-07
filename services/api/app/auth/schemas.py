"""Pydantic schemas for authentication and user accounts."""

from datetime import datetime
import re
from typing import Annotated
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Standard RFC 5322 compliant regex pattern for email validation without external libraries
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")


class UserRegisterRequest(BaseModel):
    """Payload for registering a new user account."""

    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Valid email address for the user account.",
        examples=["developer@example.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain text password (minimum 8 characters).",
        examples=["Str0ngPassw0rd!"],
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        trimmed = v.strip().lower()
        if not EMAIL_REGEX.match(trimmed):
            raise ValueError("Invalid email address format.")
        return trimmed


class UserLoginRequest(BaseModel):
    """Payload for authenticating with email and password."""

    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Registered user email address.",
        examples=["developer@example.com"],
    )
    password: str = Field(
        ...,
        description="User account password.",
        examples=["Str0ngPassw0rd!"],
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        trimmed = v.strip().lower()
        if not EMAIL_REGEX.match(trimmed):
            raise ValueError("Invalid email address format.")
        return trimmed


class TokenResponse(BaseModel):
    """Response containing signed JWT Bearer access token."""

    access_token: str = Field(
        ...,
        description="Stateless signed JWT access token.",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type discriminator.",
        examples=["bearer"],
    )
    expires_in: int = Field(
        ...,
        description="Token lifetime in seconds.",
        examples=[604800],
    )


class UserResponse(BaseModel):
    """Public representation of a User entity."""

    id: uuid.UUID = Field(
        ...,
        description="Unique user identifier.",
    )
    email: str = Field(
        ...,
        description="User email address.",
    )
    is_active: bool = Field(
        ...,
        description="Whether user account is active.",
    )
    created_at: datetime = Field(
        ...,
        description="Account registration timestamp (UTC).",
    )

    model_config = ConfigDict(from_attributes=True)
