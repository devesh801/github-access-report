"""Unit tests for GitHubClient error handling, retries, and rate limits."""

import pytest
import respx
import httpx
from app.config import Settings
from app.core.exceptions import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitExceededError,
    GitHubAPIError,
)
from app.services.github_client import GitHubClient


@pytest.mark.asyncio
@respx.mock
async def test_github_client_auth_error():
    settings = Settings(GITHUB_TOKEN="invalid_token")
    client = GitHubClient(token="invalid_token", settings=settings)

    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    with pytest.raises(GitHubAuthError):
        await client.get_rest("user")


@pytest.mark.asyncio
@respx.mock
async def test_github_client_forbidden_error():
    settings = Settings(GITHUB_TOKEN="token_lacks_scope")
    client = GitHubClient(token="token_lacks_scope", settings=settings)

    respx.get("https://api.github.com/orgs/secret-org/repos").mock(
        return_value=httpx.Response(403, json={"message": "Resource not accessible by integration"})
    )

    with pytest.raises(GitHubPermissionError):
        await client.get_rest("orgs/secret-org/repos")


@pytest.mark.asyncio
@respx.mock
async def test_github_client_not_found_error():
    settings = Settings(GITHUB_TOKEN="valid_token")
    client = GitHubClient(token="valid_token", settings=settings)

    respx.get("https://api.github.com/orgs/missing-org/repos").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    with pytest.raises(GitHubNotFoundError):
        await client.get_rest("orgs/missing-org/repos")


@pytest.mark.asyncio
@respx.mock
async def test_github_client_retry_and_rate_limit_exceeded():
    settings = Settings(GITHUB_TOKEN="valid_token", MAX_RETRIES=2, BACKOFF_FACTOR=0.01)
    client = GitHubClient(token="valid_token", settings=settings)

    # All attempts return 429
    respx.get("https://api.github.com/orgs/busy-org/repos").mock(
        return_value=httpx.Response(429, headers={"retry-after": "1"}, json={"message": "rate limited"})
    )

    with pytest.raises(GitHubRateLimitExceededError):
        await client.get_rest("orgs/busy-org/repos")


@pytest.mark.asyncio
@respx.mock
async def test_github_client_graphql_errors():
    settings = Settings(GITHUB_TOKEN="valid_token")
    client = GitHubClient(token="valid_token", settings=settings)

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "Something went wrong", "type": "INTERNAL_ERROR"}]})
    )

    with pytest.raises(GitHubAPIError):
        await client.execute_graphql("query { viewer { login } }")
