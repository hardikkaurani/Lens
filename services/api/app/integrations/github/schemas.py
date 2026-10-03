from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GitHubConnectionStatus(BaseModel):
    """Safe public representation of a GitHub OAuth integration status."""

    connected: bool = Field(..., description="Whether a valid GitHub account connection exists.")
    github_username: Optional[str] = Field(default=None, description="Connected GitHub login/username.")
    github_user_id: Optional[str] = Field(default=None, description="Connected GitHub account identifier.")
    scope: Optional[str] = Field(default=None, description="Authorized OAuth scopes.")
    connected_at: Optional[datetime] = Field(default=None, description="Timestamp when connection was established.")
    last_verified_at: Optional[datetime] = Field(default=None, description="Timestamp when connection was last verified.")


class GitHubDisconnectResponse(BaseModel):
    """Response returned upon disconnecting GitHub."""

    status: str = Field(default="disconnected", description="Result status.")
    message: str = Field(default="GitHub connection disconnected successfully.")
