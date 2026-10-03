"""Search service implementing PostgreSQL lexical search, pgvector vector search, and hybrid ranking."""

from dataclasses import dataclass
import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.embeddings.base import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingProvider,
    validate_embedding_vector,
)
from app.embeddings.factory import get_embedding_provider
from app.search.schemas import (
    SearchResponse,
    SearchResultCapture,
    SearchResultChunk,
)

logger = logging.getLogger(__name__)


@dataclass
class _CandidateChunk:
    chunk_id: uuid.UUID
    capture_id: uuid.UUID
    chunk_index: int
    content: str
    title: Optional[str]
    original_url: Optional[str]
    source_type: str
    raw_lexical_score: Optional[float] = None
    cosine_distance: Optional[float] = None
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    hybrid_score: float = 0.0


class SearchService:
    """Production-grade hybrid search service combining PostgreSQL lexical and pgvector semantic retrieval."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    async def search(
        self,
        query: str,
        session: AsyncSession,
        limit: Optional[int] = None,
        lexical_weight: Optional[float] = None,
        semantic_weight: Optional[float] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> SearchResponse:
        """Execute hybrid search combining full-text search and vector similarity."""
        sanitized_query = query.strip()
        if not sanitized_query:
            return SearchResponse(
                query=query,
                total=0,
                limit=limit or self.settings.SEARCH_DEFAULT_LIMIT,
                results=[],
            )

        effective_limit = limit if limit is not None else self.settings.SEARCH_DEFAULT_LIMIT
        effective_limit = max(1, min(effective_limit, self.settings.SEARCH_MAX_LIMIT))

        w_lex = (
            lexical_weight
            if lexical_weight is not None
            else self.settings.HYBRID_LEXICAL_WEIGHT
        )
        w_sem = (
            semantic_weight
            if semantic_weight is not None
            else self.settings.HYBRID_SEMANTIC_WEIGHT
        )

        # Normalize weights so they sum to 1.0 if both non-zero
        total_w = w_lex + w_sem
        if total_w > 0:
            w_lex = w_lex / total_w
            w_sem = w_sem / total_w
        else:
            w_lex, w_sem = 0.5, 0.5

        candidate_limit = max(effective_limit * 5, 50)
        candidates: dict[uuid.UUID, _CandidateChunk] = {}

        # ---------------------------------------------------------------------
        # 1. Lexical Search (PostgreSQL Full-Text Search with GIN Index)
        # ---------------------------------------------------------------------
        lexical_query_sql = text(
            """
            SELECT
                cc.id AS chunk_id,
                cc.capture_id,
                cc.chunk_index,
                cc.content,
                c.title,
                c.original_url,
                c.source_type,
                (
                    ts_rank_cd(cc.tsv, websearch_to_tsquery('english', :query))
                    + 0.5 * ts_rank_cd(c.tsv, websearch_to_tsquery('english', :query))
                ) AS raw_lex_score
            FROM content_chunks cc
            JOIN captures c ON cc.capture_id = c.id
            WHERE cc.tsv @@ websearch_to_tsquery('english', :query)
               OR c.tsv @@ websearch_to_tsquery('english', :query)
            ORDER BY raw_lex_score DESC, cc.capture_id ASC, cc.chunk_index ASC
            LIMIT :candidate_limit
            """
        )

        try:
            lex_results = await session.execute(
                lexical_query_sql,
                {"query": sanitized_query, "candidate_limit": candidate_limit},
            )
            for row in lex_results.mappings():
                chunk_id = row["chunk_id"]
                candidates[chunk_id] = _CandidateChunk(
                    chunk_id=chunk_id,
                    capture_id=row["capture_id"],
                    chunk_index=row["chunk_index"],
                    content=row["content"],
                    title=row["title"],
                    original_url=row["original_url"],
                    source_type=str(row["source_type"]),
                    raw_lexical_score=float(row["raw_lex_score"]),
                )
        except Exception as e:
            logger.warning("Lexical search query failed: %s", e)

        # ---------------------------------------------------------------------
        # 2. Semantic Search (pgvector Cosine Distance Search)
        # ---------------------------------------------------------------------
        degraded = False
        query_vector: Optional[list[float]] = None

        try:
            provider = embedding_provider or get_embedding_provider(settings=self.settings)
            raw_vector = await provider.embed_text(sanitized_query)
            query_vector = validate_embedding_vector(
                raw_vector, self.settings.EMBEDDING_DIMENSION
            )
        except (EmbeddingError, Exception) as embed_err:
            logger.warning(
                "Embedding provider unavailable during search query embedding; falling back to lexical-only search: %s",
                embed_err,
            )
            degraded = True

        if query_vector is not None and not degraded:
            vec_str = "[" + ",".join(str(v) for v in query_vector) + "]"
            max_dist = max(0.01, min(1.0, 1.0 - self.settings.VECTOR_SIMILARITY_THRESHOLD))
            vector_query_sql = text(
                """
                SELECT
                    cc.id AS chunk_id,
                    cc.capture_id,
                    cc.chunk_index,
                    cc.content,
                    c.title,
                    c.original_url,
                    c.source_type,
                    (cc.embedding <=> CAST(:query_vector AS vector)) AS cos_dist
                FROM content_chunks cc
                JOIN captures c ON cc.capture_id = c.id
                WHERE cc.embedding IS NOT NULL
                  AND (cc.embedding <=> CAST(:query_vector AS vector)) <= :max_dist
                ORDER BY cc.embedding <=> CAST(:query_vector AS vector) ASC, cc.capture_id ASC, cc.chunk_index ASC
                LIMIT :candidate_limit
                """
            )

            try:
                vec_results = await session.execute(
                    vector_query_sql,
                    {
                        "query_vector": vec_str,
                        "max_dist": max_dist,
                        "candidate_limit": candidate_limit,
                    },
                )
                for row in vec_results.mappings():
                    chunk_id = row["chunk_id"]
                    dist = float(row["cos_dist"])
                    if chunk_id in candidates:
                        candidates[chunk_id].cosine_distance = dist
                    else:
                        candidates[chunk_id] = _CandidateChunk(
                            chunk_id=chunk_id,
                            capture_id=row["capture_id"],
                            chunk_index=row["chunk_index"],
                            content=row["content"],
                            title=row["title"],
                            original_url=row["original_url"],
                            source_type=str(row["source_type"]),
                            cosine_distance=dist,
                        )
            except Exception as e:
                logger.warning("Vector search query execution failed: %s", e)
                degraded = True

        if not candidates:
            return SearchResponse(
                query=sanitized_query,
                total=0,
                limit=effective_limit,
                degraded=degraded,
                results=[],
            )

        # ---------------------------------------------------------------------
        # 3. Score Normalization & Deterministic Hybrid Ranking
        # ---------------------------------------------------------------------
        max_raw_lex = max(
            (c.raw_lexical_score for c in candidates.values() if c.raw_lexical_score is not None),
            default=0.0,
        )

        for candidate in candidates.values():
            # Normalized lexical score in range [0, 1]
            if candidate.raw_lexical_score is not None and max_raw_lex > 0:
                candidate.lexical_score = min(
                    1.0, max(0.0, candidate.raw_lexical_score / max_raw_lex)
                )
            else:
                candidate.lexical_score = 0.0

            # Normalized semantic score in range [0, 1] from cosine distance
            if candidate.cosine_distance is not None:
                # Cosine distance in [0, 2] -> similarity in [0, 1]
                candidate.semantic_score = min(
                    1.0, max(0.0, 1.0 - candidate.cosine_distance)
                )
            else:
                candidate.semantic_score = 0.0

            # Hybrid score
            if degraded:
                candidate.hybrid_score = candidate.lexical_score
            else:
                candidate.hybrid_score = round(
                    (w_lex * candidate.lexical_score) + (w_sem * candidate.semantic_score),
                    6,
                )

        # ---------------------------------------------------------------------
        # 4. Result Grouping: capture -> matching chunks
        # ---------------------------------------------------------------------
        # Group candidates by capture_id
        grouped: dict[uuid.UUID, list[_CandidateChunk]] = {}
        for candidate in candidates.values():
            grouped.setdefault(candidate.capture_id, []).append(candidate)

        capture_results: list[SearchResultCapture] = []

        for capture_id, chunk_list in grouped.items():
            # Sort chunks within this capture: highest hybrid score first, stable tie-break
            chunk_list.sort(
                key=lambda ch: (
                    -ch.hybrid_score,
                    -ch.lexical_score,
                    -ch.semantic_score,
                    ch.chunk_index,
                )
            )

            best_chunk = chunk_list[0]
            first_rep = chunk_list[0]

            out_chunks: list[SearchResultChunk] = []
            for ch in chunk_list:
                excerpt = ch.content[:250].rstrip()
                if len(ch.content) > 250:
                    excerpt += "..."

                out_chunks.append(
                    SearchResultChunk(
                        chunk_id=ch.chunk_id,
                        chunk_index=ch.chunk_index,
                        content_excerpt=excerpt,
                        score=ch.hybrid_score,
                        lexical_score=ch.lexical_score if ch.raw_lexical_score is not None else None,
                        semantic_score=ch.semantic_score if ch.cosine_distance is not None else None,
                    )
                )

            capture_results.append(
                SearchResultCapture(
                    capture_id=capture_id,
                    title=first_rep.title,
                    original_url=first_rep.original_url,
                    source_type=first_rep.source_type,
                    best_score=best_chunk.hybrid_score,
                    best_lexical_score=best_chunk.lexical_score if best_chunk.raw_lexical_score is not None else None,
                    best_semantic_score=best_chunk.semantic_score if best_chunk.cosine_distance is not None else None,
                    matching_chunks=out_chunks,
                )
            )

        # Deterministic sorting across captures: best score DESC, capture UUID ASC
        capture_results.sort(key=lambda cap: (-cap.best_score, str(cap.capture_id)))

        # Slice according to limit
        total_captures = len(capture_results)
        final_results = capture_results[:effective_limit]

        return SearchResponse(
            query=sanitized_query,
            total=total_captures,
            limit=effective_limit,
            degraded=degraded,
            results=final_results,
        )


search_service = SearchService()
