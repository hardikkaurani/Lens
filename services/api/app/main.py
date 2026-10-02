from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.captures.router import router as captures_router
from app.core.config import get_settings
from app.db.session import close_connections
from app.health.router import router as health_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle resources."""
    yield
    await close_connections()


app = FastAPI(
    title="LENS API",
    description="Core backend service for personal information capture and retrieval.",
    version="0.1.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(health_router)
app.include_router(captures_router)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint verifying API service availability."""
    return {"name": "LENS API", "status": "running", "environment": settings.APP_ENV}
