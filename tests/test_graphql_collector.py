"""Tests for GraphQL collector pagination and batching."""

import pytest
import respx
import httpx
from app.config import Settings
from app.services.github_client import GitHubClient
from app.services.graphql_collector import GraphQLCollector


@pytest.mark.asyncio
@respx.mock
async def test_graphql_collector_pagination():
    settings = Settings(GITHUB_TOKEN="dummy_token")
    client = GitHubClient(token="dummy_token", settings=settings)

    # Page 1 response (2 repos, hasNextPage = True)
    page1_resp = {
        "data": {
            "organization": {
                "login": "test-org",
                "name": "Test Org",
                "repositories": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor_page1"},
                    "totalCount": 3,
                    "nodes": [
                        {
                            "name": "repo1",
                            "nameWithOwner": "test-org/repo1",
                            "isPrivate": False,
                            "collaborators": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "edges": [
                                    {"permission": "ADMIN", "node": {"login": "user1", "name": "User One"}}
                                ],
                            },
                        },
                        {
                            "name": "repo2",
                            "nameWithOwner": "test-org/repo2",
                            "isPrivate": True,
                            "collaborators": {
                                "pageInfo": {"hasNextPage": True, "endCursor": "collab_cursor1"},
                                "edges": [
                                    {"permission": "WRITE", "node": {"login": "user2", "name": "User Two"}}
                                ],
                            },
                        },
                    ],
                },
            }
        }
    }

    # Page 2 response (1 repo, hasNextPage = False)
    page2_resp = {
        "data": {
            "organization": {
                "login": "test-org",
                "name": "Test Org",
                "repositories": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "totalCount": 3,
                    "nodes": [
                        {
                            "name": "repo3",
                            "nameWithOwner": "test-org/repo3",
                            "isPrivate": False,
                            "collaborators": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "edges": [
                                    {"permission": "READ", "node": {"login": "user3", "name": "User Three"}}
                                ],
                            },
                        }
                    ],
                },
            }
        }
    }

    # Deep pagination response for repo2 collaborator page 2
    repo2_collab_resp = {
        "data": {
            "repository": {
                "collaborators": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [
                        {"permission": "MAINTAIN", "node": {"login": "user4", "name": "User Four"}}
                    ],
                }
            }
        }
    }

    route = respx.post("https://api.github.com/graphql").mock(
        side_effect=[
            httpx.Response(200, json=page1_resp),
            httpx.Response(200, json=page2_resp),
            httpx.Response(200, json=repo2_collab_resp),
        ]
    )

    collector = GraphQLCollector(client)
    repos = await collector.collect_organization_data("test-org")

    assert len(repos) == 3
    assert repos[0]["name"] == "repo1"
    assert repos[1]["name"] == "repo2"
    assert repos[2]["name"] == "repo3"

    # Verify repo2 has both initial user2 and deep-paginated user4
    repo2_collabs = repos[1]["collaborators"]["edges"]
    assert len(repo2_collabs) == 2
    logins = [c["node"]["login"] for c in repo2_collabs]
    assert "user2" in logins
    assert "user4" in logins
