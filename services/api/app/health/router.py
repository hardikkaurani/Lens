from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.db.session import check_database_health, check_redis_health

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    api: str
    database: str
    redis: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check endpoint",
    description="Actively verifies reachability of API, PostgreSQL, and Redis dependencies.",
)
async def get_health(response: Response) -> HealthResponse:
    """Perform real connectivity checks on core infrastructure dependencies."""
    db_healthy = await check_database_health()
    redis_healthy = await check_redis_health()

    is_all_healthy = db_healthy and redis_healthy

    if not is_all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if is_all_healthy else "degraded",
        api="ok",
        database="ok" if db_healthy else "error",
        redis="ok" if redis_healthy else "error",
    )
