"""Pytest fixtures and mock data for test suites."""

import pytest
from typing import Dict, Any, List
from app.config import Settings
from app.core.cache import TTLCache
from app.core.rate_limiter import GitHubRateLimitTracker


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        GITHUB_TOKEN="ghp_mock_test_token_12345",
        GITHUB_API_URL="https://api.github.com",
        GITHUB_GRAPHQL_URL="https://api.github.com/graphql",
        MAX_CONCURRENT_REQUESTS=5,
        CACHE_ENABLED=True,
        CACHE_TTL_SECONDS=60,
    )


@pytest.fixture
def mock_cache() -> TTLCache:
    return TTLCache(default_ttl=60, max_entries=50)


@pytest.fixture
def mock_rate_limiter() -> GitHubRateLimitTracker:
    return GitHubRateLimitTracker()


@pytest.fixture
def sample_graphql_repos_data() -> List[Dict[str, Any]]:
    """Sample repository list with multiple users and permission tiers."""
    return [
        {
            "name": "core-backend",
            "nameWithOwner": "acme-corp/core-backend",
            "isPrivate": True,
            "description": "Core backend services",
            "url": "https://github.com/acme-corp/core-backend",
            "collaborators": {
                "totalCount": 3,
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {
                        "permission": "ADMIN",
                        "permissionSources": [{"role": "ADMIN", "source": {"Organization": {"name": "acme-corp"}}}],
                        "node": {
                            "login": "alice",
                            "name": "Alice Smith",
                            "avatarUrl": "https://avatars.github.com/u/1",
                            "url": "https://github.com/alice",
                        },
                    },
                    {
                        "permission": "WRITE",
                        "permissionSources": [{"role": "WRITE", "source": {"Team": {"name": "Backend Team", "combinedSlug": "acme-corp/backend"}}}],
                        "node": {
                            "login": "bob",
                            "name": "Bob Jones",
                            "avatarUrl": "https://avatars.github.com/u/2",
                            "url": "https://github.com/bob",
                        },
                    },
                    {
                        "permission": "READ",
                        "permissionSources": [],
                        "node": {
                            "login": "charlie",
                            "name": "Charlie Brown",
                            "avatarUrl": "https://avatars.github.com/u/3",
                            "url": "https://github.com/charlie",
                        },
                    },
                ],
            },
        },
        {
            "name": "frontend-app",
            "nameWithOwner": "acme-corp/frontend-app",
            "isPrivate": False,
            "description": "Web frontend client",
            "url": "https://github.com/acme-corp/frontend-app",
            "collaborators": {
                "totalCount": 2,
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {
                        "permission": "MAINTAIN",
                        "permissionSources": [],
                        "node": {
                            "login": "bob",
                            "name": "Bob Jones",
                            "avatarUrl": "https://avatars.github.com/u/2",
                            "url": "https://github.com/bob",
                        },
                    },
                    {
                        "permission": "TRIAGE",
                        "permissionSources": [],
                        "node": {
                            "login": "david",
                            "name": "David Miller",
                            "avatarUrl": "https://avatars.github.com/u/4",
                            "url": "https://github.com/david",
                        },
                    },
                ],
            },
        },
    ]
