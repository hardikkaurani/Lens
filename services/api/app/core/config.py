from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine project root directory (.env location)
_current_file = Path(__file__).resolve()
# Current file is services/api/app/core/config.py -> parents[3] is root (Lens/)
_root_dir = _current_file.parents[3]
_env_path = _root_dir / ".env"


class Settings(BaseSettings):
    """Core application settings loaded from environment or .env file."""

    # Application settings
    APP_ENV: str = "development"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # PostgreSQL + pgvector settings
    DATABASE_URL: str = (
        "postgresql+asyncpg://lens_user:lens_password@localhost:5432/lens"
    )

    # Redis settings
    REDIS_URL: str = "redis://localhost:6379/0"

    # Optional / Planned settings (loaded if present, but never required to start)
    JWT_SECRET: Optional[str] = None
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_WEBHOOK_SECRET: Optional[str] = None
    AI_PROVIDER: Optional[str] = None
    AI_API_KEY: Optional[str] = None
    S3_ENDPOINT: Optional[str] = None
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    S3_REGION: Optional[str] = None

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Ensure standard postgresql:// URLs use the asyncpg driver."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    model_config = SettingsConfigDict(
        env_file=(_env_path, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached singleton instance of application settings."""
    return Settings()
