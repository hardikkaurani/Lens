"""FastAPI router endpoints for unified knowledge search."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.search.schemas import SearchResponse
from app.search.service import parse_source_filter, search_service

router = APIRouter(tags=["Search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Unified knowledge search across captures and GitHub activities",
    description="Unified search combining PostgreSQL full-text search, pgvector semantic retrieval, and GitHub activity metadata.",
)
async def search_knowledge(
    q: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Search query string.",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of search results to return.",
    ),
    w_lex: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional override for lexical scoring weight.",
    ),
    w_sem: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional override for semantic scoring weight.",
    ),
    source_type: Optional[str] = Query(
        default=None,
        description="Optional filter by source or activity category (e.g. 'all', 'captures', 'text', 'url', 'pdf', 'github', 'pull_request', 'issue', 'commit', 'review').",
    ),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Execute unified search across all captured items and ingested GitHub activities."""
    # Reject empty or whitespace-only queries explicitly
    sanitized = q.strip()
    if not sanitized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query cannot be empty or whitespace-only.",
        )

    # Validate source_type filter up front for truthful HTTP 422 feedback
    try:
        parse_source_filter(source_type)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        )

    return await search_service.search(
        query=sanitized,
        session=db,
        limit=limit,
        lexical_weight=w_lex,
        semantic_weight=w_sem,
        source_type=source_type,
    )
