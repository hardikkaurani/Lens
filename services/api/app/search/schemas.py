"""Pydantic request and response schemas for search endpoints."""

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SearchResultChunk(BaseModel):
    """Individual matching content chunk with relevance scoring."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: uuid.UUID = Field(..., description="Unique UUID of the matching content chunk.")
    chunk_index: int = Field(..., description="Zero-based sequence index within the parent capture.")
    content_excerpt: str = Field(..., description="Human-readable text excerpt of the chunk.")
    score: float = Field(..., description="Final normalized hybrid relevance score in range [0, 1].")
    lexical_score: Optional[float] = Field(
        default=None,
        description="Normalized full-text search score in range [0, 1].",
    )
    semantic_score: Optional[float] = Field(
        default=None,
        description="Cosine similarity semantic score in range [0, 1].",
    )


class SearchResultCapture(BaseModel):
    """Grouped capture result aggregating matching content chunks."""

    model_config = ConfigDict(from_attributes=True)

    capture_id: uuid.UUID = Field(..., description="Unique UUID of the parent capture.")
    title: Optional[str] = Field(default=None, description="Title of the captured content.")
    original_url: Optional[str] = Field(default=None, description="Original source URL if applicable.")
    source_type: str = Field(..., description="Source type string (e.g. 'url', 'text').")
    best_score: float = Field(..., description="Highest chunk hybrid score for this capture.")
    best_lexical_score: Optional[float] = Field(
        default=None,
        description="Highest chunk lexical score for this capture.",
    )
    best_semantic_score: Optional[float] = Field(
        default=None,
        description="Highest chunk semantic score for this capture.",
    )
    matching_chunks: list[SearchResultChunk] = Field(
        default_factory=list,
        description="Ordered list of matching chunks for this capture.",
    )


class SearchResponse(BaseModel):
    """Top-level response envelope for GET /search."""

    model_config = ConfigDict(from_attributes=True)

    query: str = Field(..., description="The sanitized query string that was executed.")
    total: int = Field(..., description="Total number of distinct matching capture results.")
    limit: int = Field(..., description="Result limit applied to this search.")
    degraded: bool = Field(
        default=False,
        description="True if semantic search was unavailable and results are lexical-only.",
    )
    results: list[SearchResultCapture] = Field(
        default_factory=list,
        description="Ranked and grouped capture search results.",
    )
