"""Search service implementing PostgreSQL lexical search, pgvector vector search, and unified hybrid ranking across captures and GitHub activities."""

from dataclasses import dataclass
import logging
from typing import Optional
import uuid

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


SUPPORTED_SOURCE_FILTERS: set[str] = {
    "all",
    "captures",
    "capture",
    "text",
    "note",
    "notes",
    "url",
    "link",
    "links",
    "pdf",
    "pdfs",
    "file",
    "files",
    "image",
    "images",
    "github",
    "github_activities",
    "activities",
    "pull_request",
    "pull_requests",
    "pr",
    "prs",
    "issue",
    "issues",
    "commit",
    "commits",
    "review",
    "reviews",
}

ALL_CAPTURE_TYPES: tuple[str, ...] = ("url", "text", "pdf", "image", "file")
ALL_GITHUB_TYPES: tuple[str, ...] = ("pull_request", "issue", "commit", "review")


def parse_source_filter(
    raw_filter: Optional[str],
) -> tuple[Optional[str], tuple[str, ...], tuple[str, ...]]:
    """Validate and normalize the source_type filter into capture types and GitHub activity types.

    Returns:
        (canonical_filter_name, allowed_capture_types, allowed_github_types)
    """
    if raw_filter is None:
        return None, ALL_CAPTURE_TYPES, ALL_GITHUB_TYPES

    norm = raw_filter.strip().lower()
    if not norm or norm == "all":
        return None, ALL_CAPTURE_TYPES, ALL_GITHUB_TYPES

    if norm not in SUPPORTED_SOURCE_FILTERS:
        raise ValueError(
            f"Invalid source_type filter '{raw_filter}'. Supported filters: "
            "all, captures, text, url, pdf, file, image, github, pull_request, issue, commit, review."
        )

    if norm in ("captures", "capture"):
        return "captures", ALL_CAPTURE_TYPES, ()
    if norm in ("text", "note", "notes"):
        return "text", ("text",), ()
    if norm in ("url", "link", "links"):
        return "url", ("url",), ()
    if norm in ("pdf", "pdfs"):
        return "pdf", ("pdf",), ()
    if norm in ("image", "images"):
        return "image", ("image",), ()
    if norm in ("file", "files"):
        return "file", ("file", "pdf", "image"), ()
    if norm in ("github", "github_activities", "activities"):
        return "github", (), ALL_GITHUB_TYPES
    if norm in ("pull_request", "pull_requests", "pr", "prs"):
        return "pull_request", (), ("pull_request",)
    if norm in ("issue", "issues"):
        return "issue", (), ("issue",)
    if norm in ("commit", "commits"):
        return "commit", (), ("commit",)
    if norm in ("review", "reviews"):
        return "review", (), ("review",)

    return None, ALL_CAPTURE_TYPES, ALL_GITHUB_TYPES


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


@dataclass
class _CandidateGitHubActivity:
    activity_id: uuid.UUID
    repository_id: uuid.UUID
    repository_name: Optional[str]
    activity_type: str
    external_id: str
    title: Optional[str]
    body: Optional[str]
    html_url: Optional[str]
    author_login: Optional[str]
    state: Optional[str]
    raw_lexical_score: Optional[float] = None
    lexical_score: float = 0.0
    hybrid_score: float = 0.0


class SearchService:
    """Production-grade unified search service combining captures (lexical + pgvector semantic) and GitHub activities."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    async def search(
        self,
        query: str,
        session: AsyncSession,
        limit: Optional[int] = None,
        lexical_weight: Optional[float] = None,
        semantic_weight: Optional[float] = None,
        source_type: Optional[str] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> SearchResponse:
        """Execute unified search combining captures full-text/vector search and GitHub activity retrieval."""
        sanitized_query = query.strip()
        canonical_filter, capture_types, github_types = parse_source_filter(source_type)

        if not sanitized_query:
            return SearchResponse(
                query=query,
                total=0,
                limit=limit or self.settings.SEARCH_DEFAULT_LIMIT,
                source_filter=canonical_filter,
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
        capture_candidates: dict[uuid.UUID, _CandidateChunk] = {}
        github_candidates: dict[uuid.UUID, _CandidateGitHubActivity] = {}
        degraded = False

        # ---------------------------------------------------------------------
        # 1. Capture Lexical Search (PostgreSQL Full-Text Search with GIN Index)
        # ---------------------------------------------------------------------
        if capture_types:
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
                WHERE (cc.tsv @@ websearch_to_tsquery('english', :query)
                   OR c.tsv @@ websearch_to_tsquery('english', :query))
                  AND c.source_type::text = ANY(:capture_types)
                ORDER BY raw_lex_score DESC, cc.capture_id ASC, cc.chunk_index ASC
                LIMIT :candidate_limit
                """
            )

            try:
                lex_results = await session.execute(
                    lexical_query_sql,
                    {
                        "query": sanitized_query,
                        "capture_types": list(capture_types),
                        "candidate_limit": candidate_limit,
                    },
                )
                for row in lex_results.mappings():
                    chunk_id = row["chunk_id"]
                    capture_candidates[chunk_id] = _CandidateChunk(
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
                logger.warning("Capture lexical search query failed: %s", e)

        # ---------------------------------------------------------------------
        # 2. Capture Semantic Search (pgvector Cosine Distance Search)
        # ---------------------------------------------------------------------
        if capture_types:
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
                      AND c.source_type::text = ANY(:capture_types)
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
                            "capture_types": list(capture_types),
                            "candidate_limit": candidate_limit,
                        },
                    )
                    for row in vec_results.mappings():
                        chunk_id = row["chunk_id"]
                        dist = float(row["cos_dist"])
                        if chunk_id in capture_candidates:
                            capture_candidates[chunk_id].cosine_distance = dist
                        else:
                            capture_candidates[chunk_id] = _CandidateChunk(
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

        # ---------------------------------------------------------------------
        # 3. GitHub Activity Retrieval (PostgreSQL Full-Text Search with GIN Index)
        # ---------------------------------------------------------------------
        if github_types:
            exact_pattern = f"%{sanitized_query}%"
            github_query_sql = text(
                """
                SELECT
                    ga.id AS activity_id,
                    ga.repository_id,
                    ga.activity_type::text AS activity_type,
                    ga.external_id,
                    ga.title,
                    ga.body,
                    ga.html_url,
                    ga.author_login,
                    ga.state,
                    gr.full_name AS repository_name,
                    (
                        ts_rank_cd(ga.tsv, websearch_to_tsquery('english', :query))
                        + CASE WHEN ga.title ILIKE :exact_pattern THEN 0.5 ELSE 0.0 END
                        + CASE WHEN ga.external_id = :raw_query THEN 1.0 ELSE 0.0 END
                        + CASE WHEN ga.author_login ILIKE :exact_pattern THEN 0.25 ELSE 0.0 END
                        + CASE WHEN gr.full_name ILIKE :exact_pattern THEN 0.25 ELSE 0.0 END
                    ) AS raw_lex_score
                FROM github_activities ga
                JOIN github_repositories gr ON ga.repository_id = gr.id
                JOIN github_connections gc ON gr.connection_id = gc.id
                WHERE (
                    ga.tsv @@ websearch_to_tsquery('english', :query)
                    OR ga.external_id = :raw_query
                    OR ga.title ILIKE :exact_pattern
                    OR ga.author_login ILIKE :exact_pattern
                    OR gr.full_name ILIKE :exact_pattern
                )
                AND ga.activity_type::text = ANY(:github_types)
                ORDER BY raw_lex_score DESC, ga.source_created_at DESC NULLS LAST, ga.id ASC
                LIMIT :candidate_limit
                """
            )

            try:
                gh_results = await session.execute(
                    github_query_sql,
                    {
                        "query": sanitized_query,
                        "raw_query": sanitized_query,
                        "exact_pattern": exact_pattern,
                        "github_types": list(github_types),
                        "candidate_limit": candidate_limit,
                    },
                )
                for row in gh_results.mappings():
                    act_id = row["activity_id"]
                    github_candidates[act_id] = _CandidateGitHubActivity(
                        activity_id=act_id,
                        repository_id=row["repository_id"],
                        repository_name=row["repository_name"],
                        activity_type=str(row["activity_type"]),
                        external_id=row["external_id"],
                        title=row["title"],
                        body=row["body"],
                        html_url=row["html_url"],
                        author_login=row["author_login"],
                        state=row["state"],
                        raw_lexical_score=float(row["raw_lex_score"]),
                    )
            except Exception as e:
                logger.warning("GitHub activity search query failed: %s", e)
                # If both queries fail or github activities failed unexpectedly, record degraded status
                degraded = True

        if not capture_candidates and not github_candidates:
            return SearchResponse(
                query=sanitized_query,
                total=0,
                limit=effective_limit,
                degraded=degraded,
                source_filter=canonical_filter,
                results=[],
            )

        # ---------------------------------------------------------------------
        # 4. Calibrated Score Normalization & Unified Ranking
        # ---------------------------------------------------------------------
        # Calibrate lexical scores across captures and activities using the same shared scale
        all_raw_lex_scores = [
            c.raw_lexical_score
            for c in capture_candidates.values()
            if c.raw_lexical_score is not None
        ] + [
            g.raw_lexical_score
            for g in github_candidates.values()
            if g.raw_lexical_score is not None
        ]
        max_raw_lex = max(all_raw_lex_scores, default=0.0)

        for candidate in capture_candidates.values():
            if candidate.raw_lexical_score is not None and max_raw_lex > 0:
                candidate.lexical_score = min(
                    1.0, max(0.0, candidate.raw_lexical_score / max_raw_lex)
                )
            else:
                candidate.lexical_score = 0.0

            if candidate.cosine_distance is not None:
                candidate.semantic_score = min(
                    1.0, max(0.0, 1.0 - candidate.cosine_distance)
                )
            else:
                candidate.semantic_score = 0.0

            if degraded:
                candidate.hybrid_score = round(candidate.lexical_score, 6)
            else:
                candidate.hybrid_score = round(
                    (w_lex * candidate.lexical_score) + (w_sem * candidate.semantic_score),
                    6,
                )

        for g_cand in github_candidates.values():
            if g_cand.raw_lexical_score is not None and max_raw_lex > 0:
                g_cand.lexical_score = min(
                    1.0, max(0.0, g_cand.raw_lexical_score / max_raw_lex)
                )
            else:
                g_cand.lexical_score = 0.0

            # Grounded relevance: GitHub activity relevance is its normalized lexical score on the shared scale
            g_cand.hybrid_score = round(g_cand.lexical_score, 6)

        # ---------------------------------------------------------------------
        # 5. Assemble and Group Capture Results
        # ---------------------------------------------------------------------
        grouped: dict[uuid.UUID, list[_CandidateChunk]] = {}
        for candidate in capture_candidates.values():
            grouped.setdefault(candidate.capture_id, []).append(candidate)

        capture_results: list[SearchResultCapture] = []
        for capture_id, chunk_list in grouped.items():
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
                    result_kind="capture",
                )
            )

        # ---------------------------------------------------------------------
        # 6. Assemble GitHub Activity Results
        # ---------------------------------------------------------------------
        github_results: list[SearchResultCapture] = []
        for g_cand in github_candidates.values():
            if g_cand.title and g_cand.title.strip():
                display_title = g_cand.title.strip()
            elif g_cand.activity_type == "commit":
                display_title = f"Commit {g_cand.external_id[:7]}"
            else:
                label = g_cand.activity_type.replace("_", " ").title()
                display_title = f"{label} #{g_cand.external_id}"

            body_text = (g_cand.body or "").strip()
            if not body_text and g_cand.title:
                body_text = g_cand.title.strip()

            excerpt = body_text[:250].rstrip()
            if len(body_text) > 250:
                excerpt += "..."

            out_chunks: list[SearchResultChunk] = []
            if excerpt:
                out_chunks.append(
                    SearchResultChunk(
                        chunk_id=g_cand.activity_id,
                        chunk_index=0,
                        content_excerpt=excerpt,
                        score=g_cand.hybrid_score,
                        lexical_score=g_cand.lexical_score,
                        semantic_score=None,
                    )
                )

            github_results.append(
                SearchResultCapture(
                    capture_id=g_cand.activity_id,
                    title=display_title,
                    original_url=g_cand.html_url,
                    source_type=g_cand.activity_type,
                    best_score=g_cand.hybrid_score,
                    best_lexical_score=g_cand.lexical_score,
                    best_semantic_score=None,
                    matching_chunks=out_chunks,
                    result_kind="github_activity",
                    activity_type=g_cand.activity_type,
                    repository_name=g_cand.repository_name,
                    author_login=g_cand.author_login,
                    state=g_cand.state,
                    external_id=g_cand.external_id,
                )
            )

        # ---------------------------------------------------------------------
        # 7. Unified Deterministic Ranking & Bounded Selection
        # ---------------------------------------------------------------------
        all_results = capture_results + github_results
        all_results.sort(
            key=lambda item: (
                -item.best_score,
                -(item.best_lexical_score if item.best_lexical_score is not None else 0.0),
                item.source_type,
                str(item.capture_id),
            )
        )

        total_evaluated = len(all_results)
        final_results = all_results[:effective_limit]

        return SearchResponse(
            query=sanitized_query,
            total=total_evaluated,
            limit=effective_limit,
            degraded=degraded,
            source_filter=canonical_filter,
            results=final_results,
        )


search_service = SearchService()
