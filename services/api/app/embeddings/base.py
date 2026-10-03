"""Core embedding provider interface, exception hierarchy, and vector validation."""

import math
from typing import Protocol, runtime_checkable


class EmbeddingError(Exception):
    """Base exception for all embedding-related errors."""


class EmbeddingDimensionError(EmbeddingError):
    """Raised when an embedding vector does not match the expected dimension."""


class EmbeddingProviderError(EmbeddingError):
    """Raised when the embedding provider fails, returns an invalid response, or is misconfigured."""


class EmbeddingTimeoutError(EmbeddingError):
    """Raised when an embedding provider request times out."""


def validate_embedding_vector(vector: list[float], expected_dim: int = 1536) -> list[float]:
    """Validate that vector contains exactly expected_dim finite floating-point values.

    Rejects:
    - Non-list/tuple input
    - Incorrect dimension (not equal to expected_dim)
    - NaN or infinite values
    - Non-numeric elements
    """
    if not isinstance(vector, (list, tuple)):
        raise EmbeddingDimensionError(
            f"Embedding vector must be a list or tuple of floats, got {type(vector).__name__}"
        )

    if len(vector) != expected_dim:
        raise EmbeddingDimensionError(
            f"Expected embedding vector of dimension {expected_dim}, got {len(vector)}"
        )

    validated: list[float] = []
    for idx, val in enumerate(vector):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise EmbeddingProviderError(
                f"Embedding element at index {idx} is not numeric: {type(val).__name__}"
            )
        f_val = float(val)
        if math.isnan(f_val):
            raise EmbeddingProviderError(f"Embedding element at index {idx} is NaN")
        if math.isinf(f_val):
            raise EmbeddingProviderError(f"Embedding element at index {idx} is Infinite")
        validated.append(f_val)

    return validated


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Async interface protocol for text embedding providers."""

    @property
    def dimension(self) -> int:
        """Expected vector dimension produced by this provider."""
        ...

    @property
    def model_name(self) -> str:
        """Underlying model identifier."""
        ...

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string into a 1536-dimensional float vector.

        Must return a validated vector of exactly self.dimension elements.
        """
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a sequence of text strings into float vectors.

        Must preserve input ordering and return exactly one vector per input text.
        """
        ...
