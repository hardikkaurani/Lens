from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.captures.router import router as captures_router
from app.core.config import get_settings
from app.db.session import close_connections
from app.health.router import router as health_router
from app.integrations.github.router import router as github_router
from app.search.router import router as search_router

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

# Secure CORS configuration: Restrict to explicit origins when credentials are supported
cors_origins = list(settings.CORS_ORIGINS)
if settings.FRONTEND_URL and settings.FRONTEND_URL not in cors_origins:
    cors_origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(captures_router)
app.include_router(search_router)
app.include_router(github_router)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint verifying API service availability."""
    return {"name": "LENS API", "status": "running", "environment": settings.APP_ENV}
