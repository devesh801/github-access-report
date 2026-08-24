"""FastAPI dependencies for authentication, caching, and GitHub services."""

from typing import Optional
import httpx
from fastapi import Header, Depends, Request

from app.config import Settings, get_settings
from app.core.auth import GitHubAuthProvider
from app.core.cache import TTLCache
from app.core.rate_limiter import GitHubRateLimitTracker
from app.services.github_client import GitHubClient

# Application-level singletons
_global_cache: Optional[TTLCache] = None
_global_rate_limiter = GitHubRateLimitTracker()


def get_cache(settings: Settings = Depends(get_settings)) -> TTLCache:
    """Return singleton cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = TTLCache(
            default_ttl=settings.CACHE_TTL_SECONDS,
            max_entries=settings.CACHE_MAX_ENTRIES,
        )
    return _global_cache


def get_rate_limiter() -> GitHubRateLimitTracker:
    """Return singleton rate limit tracker."""
    return _global_rate_limiter


def get_auth_provider(settings: Settings = Depends(get_settings)) -> GitHubAuthProvider:
    """Return auth provider initialized with current settings."""
    return GitHubAuthProvider(settings=settings)


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Retrieve shared httpx client from FastAPI app state."""
    return getattr(request.app.state, "http_client", None)


async def get_github_client(
    authorization: Optional[str] = Header(None, description="GitHub Bearer token or PAT"),
    x_github_token: Optional[str] = Header(None, description="Direct GitHub token header"),
    settings: Settings = Depends(get_settings),
    auth_provider: GitHubAuthProvider = Depends(get_auth_provider),
    rate_limiter: GitHubRateLimitTracker = Depends(get_rate_limiter),
    http_client: Optional[httpx.AsyncClient] = Depends(get_http_client),
) -> GitHubClient:
    """Resolve GitHub credentials and return configured GitHubClient."""
    override_token = x_github_token or authorization
    token, _ = await auth_provider.resolve_token(override_token, http_client=http_client)
    return GitHubClient(
        token=token,
        settings=settings,
        rate_limiter=rate_limiter,
        http_client=http_client,
    )
