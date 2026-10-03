"""OpenAI-compatible HTTP embedding provider using standard REST endpoints without vendor SDK coupling."""

import asyncio
import logging
from typing import Optional

import httpx

from app.embeddings.base import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingTimeoutError,
    validate_embedding_vector,
)

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding provider utilizing standard HTTP REST requests.

    Targets models such as text-embedding-3-small (1536 dimensions).
    Implements batching, request timeouts, bounded retries, and strict secret masking.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "text-embedding-3-small",
        dimension: int = 1536,
        timeout: float = 10.0,
        max_batch_size: int = 32,
        max_retries: int = 1,
    ) -> None:
        if not api_key or not api_key.strip():
            raise EmbeddingProviderError("Embedding provider requires a non-empty API key.")

        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._dimension = dimension
        self._timeout = timeout
        self._max_batch_size = max(1, max_batch_size)
        self._max_retries = max(0, min(max_retries, 3))

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def _post_batch_with_retry(
        self,
        client: httpx.AsyncClient,
        batch: list[str],
    ) -> list[list[float]]:
        """Post a single batch to the embedding API with bounded retry and strict error sanitization."""
        url = f"{self._base_url}/embeddings"
        payload = {
            "model": self._model_name,
            "input": batch,
            "dimensions": self._dimension,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception as json_err:
                        raise EmbeddingProviderError(
                            "Failed to parse embedding response JSON from provider."
                        ) from json_err

                    items = data.get("data")
                    if not isinstance(items, list):
                        raise EmbeddingProviderError(
                            "Embedding provider response missing 'data' list."
                        )

                    if len(items) != len(batch):
                        raise EmbeddingProviderError(
                            f"Embedding provider returned {len(items)} items for {len(batch)} inputs."
                        )

                    # Ensure responses are ordered by item index
                    try:
                        sorted_items = sorted(items, key=lambda it: it.get("index", 0))
                    except Exception as sort_err:
                        raise EmbeddingProviderError(
                            "Embedding response items missing valid 'index' attributes."
                        ) from sort_err

                    # Validate each vector
                    vectors: list[list[float]] = []
                    for item in sorted_items:
                        raw_vec = item.get("embedding")
                        validated = validate_embedding_vector(raw_vec, self._dimension)
                        vectors.append(validated)

                    return vectors

                # Handle HTTP errors safely without exposing secrets
                if response.status_code in (401, 403):
                    raise EmbeddingProviderError(
                        "Embedding provider authentication failed (HTTP 401/403)."
                    )
                if response.status_code == 429:
                    last_error = EmbeddingProviderError(
                        "Embedding provider rate limit exceeded (HTTP 429)."
                    )
                elif response.status_code >= 500:
                    last_error = EmbeddingProviderError(
                        f"Embedding provider internal server error (HTTP {response.status_code})."
                    )
                else:
                    raise EmbeddingProviderError(
                        f"Embedding provider returned HTTP {response.status_code}."
                    )

            except httpx.TimeoutException as exc:
                last_error = EmbeddingTimeoutError(
                    f"Embedding request timed out after {self._timeout:.1f} seconds."
                )
            except httpx.RequestError as exc:
                last_error = EmbeddingProviderError(
                    "Network error occurred while connecting to embedding provider."
                )
            except (EmbeddingDimensionError, EmbeddingProviderError):
                raise
            except Exception as exc:
                last_error = EmbeddingProviderError("Unexpected error during embedding request.")

            # Backoff before retry if attempts remain
            if attempt < self._max_retries:
                logger.warning(
                    "Embedding request failed on attempt %d/%d; retrying...",
                    attempt + 1,
                    self._max_retries + 1,
                )
                await asyncio.sleep(0.5 * (2**attempt))

        if last_error:
            raise last_error

        raise EmbeddingProviderError("Embedding request failed after retries.")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a sequence of text strings, splitting into bounded batches."""
        if not texts:
            return []

        all_vectors: list[list[float]] = []
        async with httpx.AsyncClient() as client:
            for i in range(0, len(texts), self._max_batch_size):
                batch = texts[i : i + self._max_batch_size]
                batch_vectors = await self._post_batch_with_retry(client, batch)
                all_vectors.extend(batch_vectors)

        return all_vectors

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        results = await self.embed_texts([text])
        if not results:
            raise EmbeddingProviderError("Embedding provider returned empty result for single input.")
        return results[0]
