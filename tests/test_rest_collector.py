"""Unit tests for the REST API collector."""

import pytest
import respx
import httpx
from app.config import Settings
from app.models.schemas import AffiliationFilter
from app.services.github_client import GitHubClient
from app.services.rest_collector import RestCollector


@pytest.mark.asyncio
@respx.mock
async def test_rest_collector_success():
    settings = Settings(GITHUB_TOKEN="dummy_token")
    client = GitHubClient(token="dummy_token", settings=settings)

    # 1. Mock /orgs/{org}/repos
    repos_payload = [
        {
            "name": "repo-a",
            "full_name": "acme/repo-a",
            "private": True,
            "description": "Repo A description",
            "html_url": "https://github.com/acme/repo-a",
        },
        {
            "name": "repo-b",
            "full_name": "acme/repo-b",
            "private": False,
            "description": "Repo B description",
            "html_url": "https://github.com/acme/repo-b",
        },
    ]

    respx.get("https://api.github.com/orgs/acme/repos").mock(
        return_value=httpx.Response(200, json=repos_payload)
    )

    # 2. Mock /repos/acme/repo-a/collaborators
    repo_a_collabs = [
        {
            "login": "alice",
            "name": "Alice Smith",
            "avatar_url": "https://avatars.github.com/u/1",
            "html_url": "https://github.com/alice",
            "permissions": {"admin": True, "maintain": False, "push": True, "triage": True, "pull": True},
        }
    ]
    respx.get("https://api.github.com/repos/acme/repo-a/collaborators").mock(
        return_value=httpx.Response(200, json=repo_a_collabs)
    )

    # 3. Mock /repos/acme/repo-b/collaborators
    repo_b_collabs = [
        {
            "login": "bob",
            "name": "Bob Jones",
            "avatar_url": "https://avatars.github.com/u/2",
            "html_url": "https://github.com/bob",
            "permissions": {"admin": False, "maintain": False, "push": True, "triage": True, "pull": True},
        }
    ]
    respx.get("https://api.github.com/repos/acme/repo-b/collaborators").mock(
        return_value=httpx.Response(200, json=repo_b_collabs)
    )

    collector = RestCollector(client)
    data = await collector.collect_organization_data("acme", affiliation=AffiliationFilter.ALL)

    assert len(data) == 2
    assert data[0]["name"] == "repo-a"
    assert data[0]["isPrivate"] is True
    assert data[0]["collaborators"]["edges"][0]["permission"] == "ADMIN"
    assert data[0]["collaborators"]["edges"][0]["node"]["login"] == "alice"

    assert data[1]["name"] == "repo-b"
    assert data[1]["isPrivate"] is False
    assert data[1]["collaborators"]["edges"][0]["permission"] == "WRITE"
    assert data[1]["collaborators"]["edges"][0]["node"]["login"] == "bob"
