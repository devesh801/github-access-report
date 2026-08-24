"""Asynchronous HTTP client for GitHub REST and GraphQL APIs."""

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple
import httpx

from app.config import Settings, get_settings
from app.core.exceptions import (
    GitHubAccessError,
    GitHubAuthError,
    GitHubPermissionError,
    GitHubRateLimitExceededError,
    GitHubNotFoundError,
    GitHubAPIError,
)
from app.core.rate_limiter import GitHubRateLimitTracker

logger = logging.getLogger(__name__)


class GitHubClient:
    """Resilient async client for GitHub APIs with rate limiting and exponential backoff."""

    def __init__(
        self,
        token: str,
        settings: Optional[Settings] = None,
        rate_limiter: Optional[GitHubRateLimitTracker] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.token = token
        self.settings = settings or get_settings()
        self.rate_limiter = rate_limiter or GitHubRateLimitTracker()
        self._custom_client = http_client
        self._client: Optional[httpx.AsyncClient] = http_client
        self._semaphore = asyncio.Semaphore(self.settings.MAX_CONCURRENT_REQUESTS)

    async def __aenter__(self) -> "GitHubClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.REQUEST_TIMEOUT_SECONDS),
                limits=httpx.Limits(
                    max_connections=self.settings.MAX_CONCURRENT_REQUESTS * 2,
                    max_keepalive_connections=self.settings.MAX_CONCURRENT_REQUESTS,
                ),
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client and self._custom_client is None:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"github-access-report/{self.settings.APP_VERSION}",
        }

    async def request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Execute an HTTP request with concurrency control, rate limit tracking, and retries."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.REQUEST_TIMEOUT_SECONDS)
            )

        headers = self._get_headers()
        max_retries = self.settings.MAX_RETRIES

        for attempt in range(1, max_retries + 1):
            async with self._semaphore:
                try:
                    resp = await self._client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        json=json_data,
                    )
                except httpx.RequestError as exc:
                    if attempt == max_retries:
                        raise GitHubAPIError(f"Network error connecting to GitHub: {exc}")
                    delay = self.rate_limiter.calculate_backoff(attempt, self.settings.BACKOFF_FACTOR)
                    logger.warning("Request failed (%s). Retrying in %.2fs (attempt %d/%d)...", exc, delay, attempt, max_retries)
                    await asyncio.sleep(delay)
                    continue

            # Update rate limit tracker from response headers
            await self.rate_limiter.update_from_headers(resp.headers)

            # Success
            if resp.is_success:
                return resp

            # Handle rate limiting / secondary rate limits (429 or 403 with specific message)
            if resp.status_code == 429 or (
                resp.status_code == 403
                and any(msg in resp.text.lower() for msg in ["rate limit", "secondary rate limit", "abuse detection"])
            ):
                retry_after = resp.headers.get("retry-after")
                retry_after_sec = int(retry_after) if retry_after and retry_after.isdigit() else None
                reset_hdr = resp.headers.get("x-ratelimit-reset")
                reset_at = int(reset_hdr) if reset_hdr and reset_hdr.isdigit() else None

                if attempt < max_retries:
                    delay = self.rate_limiter.calculate_backoff(
                        attempt,
                        self.settings.BACKOFF_FACTOR,
                        retry_after=retry_after_sec,
                    )
                    logger.warning(
                        "Rate limit hit (%d). Backing off for %.2fs before retry %d/%d...",
                        resp.status_code,
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise GitHubRateLimitExceededError(
                        message="GitHub API rate limit exceeded and max retries reached.",
                        retry_after=retry_after_sec,
                        reset_at=reset_at,
                        details={"status_code": resp.status_code, "body": resp.text},
                    )

            # Authentication / authorization errors
            if resp.status_code == 401:
                raise GitHubAuthError(
                    "Invalid or expired GitHub authentication token.",
                    details={"body": resp.text},
                )
            if resp.status_code == 403:
                raise GitHubPermissionError(
                    "Access forbidden: token lacks permission for this organization/resource or SAML SSO enforcement is active.",
                    details={"body": resp.text},
                )
            if resp.status_code == 404:
                raise GitHubNotFoundError(
                    "Organization, repository, or resource not found on GitHub.",
                    details={"url": url, "body": resp.text},
                )

            # Server errors on GitHub side (5xx)
            if resp.status_code in (500, 502, 503, 504):
                if attempt < max_retries:
                    delay = self.rate_limiter.calculate_backoff(attempt, self.settings.BACKOFF_FACTOR)
                    logger.warning("GitHub returned %d. Retrying in %.2fs...", resp.status_code, delay)
                    await asyncio.sleep(delay)
                    continue
                raise GitHubAPIError(
                    f"GitHub server error: HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    details={"body": resp.text},
                )

            # Other unexpected errors
            raise GitHubAPIError(
                f"GitHub API returned error: HTTP {resp.status_code}",
                status_code=resp.status_code,
                details={"body": resp.text},
            )

        raise GitHubAPIError("Request failed after exhausting retries.")

    async def get_rest(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Call a GitHub REST API endpoint and return JSON."""
        url = endpoint if endpoint.startswith("http") else f"{self.settings.GITHUB_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        resp = await self.request("GET", url, params=params)
        return resp.json()

    async def execute_graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a GitHub GraphQL query with error handling."""
        payload = {"query": query, "variables": variables or {}}
        resp = await self.request("POST", self.settings.GITHUB_GRAPHQL_URL, json_data=payload)
        data = resp.json()

        if "errors" in data and data["errors"]:
            errors = data["errors"]
            error_msgs = [e.get("message", "Unknown error") for e in errors]
            error_types = [e.get("type", "") for e in errors]

            if any("NOT_FOUND" in t or "Could not resolve to an Organization" in m for t, m in zip(error_types, error_msgs)):
                raise GitHubNotFoundError(f"Organization not found: {'; '.join(error_msgs)}")
            if any("FORBIDDEN" in t or "Resource not accessible" in m for t, m in zip(error_types, error_msgs)):
                raise GitHubPermissionError(f"Access forbidden: {'; '.join(error_msgs)}")
            if any("RATE_LIMITED" in t for t in error_types):
                raise GitHubRateLimitExceededError(f"GraphQL rate limit reached: {'; '.join(error_msgs)}")

            raise GitHubAPIError(f"GraphQL execution errors: {'; '.join(error_msgs)}", details={"errors": errors})

        return data.get("data", {})
