"""Embeddings package exposing interface protocols, implementations, and factories."""

from app.embeddings.base import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingTimeoutError,
    validate_embedding_vector,
)
from app.embeddings.factory import (
    get_embedding_provider,
    reset_embedding_provider_override,
    set_embedding_provider_override,
)
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.test_provider import DeterministicTestEmbeddingProvider

__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingTimeoutError",
    "validate_embedding_vector",
    "get_embedding_provider",
    "set_embedding_provider_override",
    "reset_embedding_provider_override",
    "OpenAIEmbeddingProvider",
    "DeterministicTestEmbeddingProvider",
]
