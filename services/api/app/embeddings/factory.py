"""Factory for instantiating and caching configured embedding providers."""

import logging
from typing import Optional

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider, EmbeddingProviderError
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.test_provider import DeterministicTestEmbeddingProvider

logger = logging.getLogger(__name__)

# Global test override support for deterministic testing
_provider_override: Optional[EmbeddingProvider] = None


def set_embedding_provider_override(provider: Optional[EmbeddingProvider]) -> None:
    """Set a process-level embedding provider override (used in test suites)."""
    global _provider_override
    _provider_override = provider


def reset_embedding_provider_override() -> None:
    """Clear any active process-level embedding provider override."""
    global _provider_override
    _provider_override = None


def get_embedding_provider(
    provider_name: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> EmbeddingProvider:
    """Instantiate and return the configured embedding provider.

    Resolution order:
    1. Active test override set via set_embedding_provider_override()
    2. Explicit provider_name argument
    3. settings.EMBEDDING_PROVIDER ("openai", "test", "mock")

    Initialization is lazy: Missing API keys will not prevent application startup.
    """
    global _provider_override
    if _provider_override is not None:
        return _provider_override

    cfg = settings or get_settings()
    name = (provider_name or cfg.EMBEDDING_PROVIDER or "openai").lower().strip()

    if name in ("test", "mock", "fake"):
        return DeterministicTestEmbeddingProvider(
            dimension=cfg.EMBEDDING_DIMENSION,
            model_name=cfg.EMBEDDING_MODEL,
        )

    if name == "openai":
        api_key = cfg.OPENAI_API_KEY or cfg.AI_API_KEY
        if not api_key:
            if cfg.APP_ENV in ("development", "test"):
                logger.info(
                    "No OpenAI API key configured in %s environment; using DeterministicTestEmbeddingProvider",
                    cfg.APP_ENV,
                )
                return DeterministicTestEmbeddingProvider(
                    dimension=cfg.EMBEDDING_DIMENSION,
                    model_name=cfg.EMBEDDING_MODEL,
                )
            raise EmbeddingProviderError(
                "OpenAI embedding provider configured, but neither OPENAI_API_KEY nor AI_API_KEY is set."
            )

        return OpenAIEmbeddingProvider(
            api_key=api_key,
            base_url=cfg.OPENAI_BASE_URL,
            model_name=cfg.EMBEDDING_MODEL,
            dimension=cfg.EMBEDDING_DIMENSION,
            timeout=cfg.EMBEDDING_TIMEOUT,
            max_batch_size=cfg.EMBEDDING_BATCH_SIZE,
        )

    raise EmbeddingProviderError(f"Unsupported embedding provider: '{name}'")
