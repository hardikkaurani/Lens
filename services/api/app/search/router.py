"""FastAPI router endpoints for hybrid search."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.search.schemas import SearchResponse
from app.search.service import search_service

router = APIRouter(tags=["Search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Hybrid search over captured content",
    description="Search captures combining PostgreSQL full-text search and pgvector semantic retrieval.",
)
async def search_captures(
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
        description="Maximum number of capture results to return.",
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
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Execute hybrid search across all captured items."""
    # Reject empty or whitespace-only queries explicitly
    sanitized = q.strip()
    if not sanitized:
        raise HTTPException(
            status_code=422,
            detail="Search query cannot be empty or whitespace-only.",
        )

    return await search_service.search(
        query=sanitized,
        session=db,
        limit=limit,
        lexical_weight=w_lex,
        semantic_weight=w_sem,
    )
