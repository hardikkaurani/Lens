"""Deterministic fake/test embedding provider for integration tests and local development."""

import hashlib
import math
import re

from app.embeddings.base import EmbeddingProvider, validate_embedding_vector


class DeterministicTestEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider for tests and reproducible local execution.

    Generates reproducible 1536-dimensional L2-normalized float vectors using SHA-256
    token hashing. Completely avoids external API calls and random numbers:
    - Same input text always produces the exact same vector.
    - Semantically related texts sharing vocabulary have higher cosine similarity.
    - Unrelated texts produce distinct vectors with near-orthogonal orientation.
    - Every generated vector strictly conforms to the 1536-dimension float contract.
    """

    def __init__(
        self,
        dimension: int = 1536,
        model_name: str = "test-embedding-3-small",
    ) -> None:
        self._dimension = dimension
        self._model_name = model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def _generate_vector(self, text: str) -> list[float]:
        """Generate a deterministic unit vector for a given text string."""
        vec = [0.0] * self._dimension
        normalized = text.lower().strip()
        if not normalized:
            # Fallback normalized unit vector along index 0 for blank input
            vec[0] = 1.0
            return validate_embedding_vector(vec, self._dimension)

        # 1. Global text signature: spread hash entropy across all dimensions
        hash_bytes = hashlib.sha256(normalized.encode("utf-8")).digest()
        for i in range(self._dimension):
            byte_val = hash_bytes[i % len(hash_bytes)]
            vec[i] = ((byte_val ^ (i & 0xFF)) - 128) / 128.0 * 0.05

        # 2. Word-level token hashing: shared words activate shared dimensions
        words = re.findall(r"\w+", normalized)
        for word in words:
            w_hash = hashlib.sha256(word.encode("utf-8")).digest()
            for k in range(8):
                idx = int.from_bytes(w_hash[k * 2 : k * 2 + 2], "big") % self._dimension
                vec[idx] += 1.0

        # 3. L2 normalize vector to unit length
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0

        return validate_embedding_vector(vec, self._dimension)

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self._generate_vector(text)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings, preserving ordering."""
        return [self._generate_vector(t) for t in texts]
