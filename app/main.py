"""Main entry point for the GitHub Organization Access Report Service."""

import logging
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.config import get_settings
from app.core.exceptions import (
    GitHubAccessError,
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitExceededError,
    GitHubAPIError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle resources (e.g. shared HTTP client)."""
    settings = get_settings()
    logger.info("Initializing %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.REQUEST_TIMEOUT_SECONDS),
        limits=httpx.Limits(
            max_connections=settings.MAX_CONCURRENT_REQUESTS * 2,
            max_keepalive_connections=settings.MAX_CONCURRENT_REQUESTS,
        ),
    )
    yield
    logger.info("Closing HTTP client connections...")
    await app.state.http_client.aclose()


def create_app() -> FastAPI:
    """Application factory for FastAPI service."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "A high-performance service for generating comprehensive user repository access "
            "reports for GitHub organizations at scale (100+ repositories, 1,000+ users)."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    @app.exception_handler(GitHubAuthError)
    async def auth_error_handler(request: Request, exc: GitHubAuthError):
        return JSONResponse(
            status_code=401,
            content={
                "error": "UNAUTHORIZED",
                "message": exc.message,
                "status_code": 401,
                "details": exc.details,
            },
        )

    @app.exception_handler(GitHubPermissionError)
    async def permission_error_handler(request: Request, exc: GitHubPermissionError):
        return JSONResponse(
            status_code=403,
            content={
                "error": "FORBIDDEN",
                "message": exc.message,
                "status_code": 403,
                "details": exc.details,
            },
        )

    @app.exception_handler(GitHubNotFoundError)
    async def not_found_error_handler(request: Request, exc: GitHubNotFoundError):
        return JSONResponse(
            status_code=404,
            content={
                "error": "NOT_FOUND",
                "message": exc.message,
                "status_code": 404,
                "details": exc.details,
            },
        )

    @app.exception_handler(GitHubRateLimitExceededError)
    async def rate_limit_error_handler(request: Request, exc: GitHubRateLimitExceededError):
        return JSONResponse(
            status_code=429,
            content={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": exc.message,
                "status_code": 429,
                "details": exc.details,
            },
        )

    @app.exception_handler(GitHubAPIError)
    async def api_error_handler(request: Request, exc: GitHubAPIError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "GITHUB_API_ERROR",
                "message": exc.message,
                "status_code": exc.status_code,
                "details": exc.details,
            },
        )

    @app.exception_handler(GitHubAccessError)
    async def generic_access_error_handler(request: Request, exc: GitHubAccessError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "GITHUB_ACCESS_ERROR",
                "message": exc.message,
                "status_code": exc.status_code,
                "details": exc.details,
            },
        )

    # Routes
    app.include_router(api_router, prefix="/api/v1")
    # Health alias at root
    app.include_router(api_router, prefix="")

    @app.get("/", tags=["System"])
    async def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
