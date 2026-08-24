"""Integration tests for FastAPI endpoints."""

import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings, Settings
from app.api.dependencies import get_cache
from app.core.cache import TTLCache


@pytest.fixture
def client():
    shared_test_cache = TTLCache(default_ttl=60, max_entries=50)
    app.dependency_overrides[get_cache] = lambda: shared_test_cache
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "github_reachable" in data


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "GitHub Organization Access Report Service"
    assert "/docs" in data["docs"]


@respx.mock
def test_get_access_report_success(client, sample_graphql_repos_data):
    mock_graphql_resp = {
        "data": {
            "repositoryOwner": {
                "login": "acme-corp",
                "repositories": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "totalCount": len(sample_graphql_repos_data),
                    "nodes": sample_graphql_repos_data,
                },
            }
        }
    }

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=mock_graphql_resp)
    )

    headers = {"Authorization": "Bearer test_token_xyz"}
    response = client.get("/api/v1/orgs/acme-corp/access-report", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["organization"] == "acme-corp"
    assert data["cached"] is False
    assert len(data["users"]) == 4

    summary = data["summary"]
    assert summary["total_repositories"] == 2
    assert summary["total_users"] == 4
    assert summary["permission_distribution"]["ADMIN"] == 1


@respx.mock
def test_get_access_report_cached(client, sample_graphql_repos_data):
    mock_graphql_resp = {
        "data": {
            "repositoryOwner": {
                "login": "acme-corp",
                "repositories": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "totalCount": len(sample_graphql_repos_data),
                    "nodes": sample_graphql_repos_data,
                },
            }
        }
    }

    route = respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=mock_graphql_resp)
    )

    headers = {"Authorization": "Bearer test_token_xyz"}

    # First request -> fetched from GitHub API
    resp1 = client.get("/api/v1/orgs/acme-corp/access-report", headers=headers)
    assert resp1.status_code == 200
    assert resp1.json()["cached"] is False
    assert route.call_count == 1

    # Second request -> served from cache without calling GitHub API again
    resp2 = client.get("/api/v1/orgs/acme-corp/access-report", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["cached"] is True
    assert route.call_count == 1

    # Third request with refresh=true -> bypasses cache and calls GitHub API
    resp3 = client.get("/api/v1/orgs/acme-corp/access-report?refresh=true", headers=headers)
    assert resp3.status_code == 200
    assert resp3.json()["cached"] is False
    assert route.call_count == 2


@respx.mock
def test_get_access_report_filter_min_permission(client, sample_graphql_repos_data):
    mock_graphql_resp = {
        "data": {
            "repositoryOwner": {
                "login": "acme-corp",
                "repositories": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "totalCount": len(sample_graphql_repos_data),
                    "nodes": sample_graphql_repos_data,
                },
            }
        }
    }

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=mock_graphql_resp)
    )

    headers = {"Authorization": "Bearer test_token_xyz"}
    response = client.get(
        "/api/v1/orgs/acme-corp/access-report?min_permission=WRITE",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["users"]) == 2
    logins = [u["login"] for u in data["users"]]
    assert "alice" in logins
    assert "bob" in logins


@respx.mock
def test_unauthorized_error_when_no_credentials(client):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, GITHUB_TOKEN=None, GITHUB_APP_ID=None)

    response = client.get("/api/v1/orgs/acme-corp/access-report")
    assert response.status_code == 401
    data = response.json()
    assert data["error"] == "UNAUTHORIZED"
    assert "credentials" in data["message"].lower()


@respx.mock
def test_not_found_error(client):
    mock_err_resp = {
        "errors": [
            {
                "type": "NOT_FOUND",
                "message": "Could not resolve to a User or Organization with the login of 'non-existent-org'.",
            }
        ]
    }

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=mock_err_resp)
    )

    headers = {"Authorization": "Bearer test_token"}
    response = client.get("/api/v1/orgs/non-existent-org/access-report", headers=headers)
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "NOT_FOUND"


@respx.mock
def test_list_organization_users(client, sample_graphql_repos_data):
    mock_graphql_resp = {
        "data": {
            "repositoryOwner": {
                "login": "acme-corp",
                "repositories": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "totalCount": len(sample_graphql_repos_data),
                    "nodes": sample_graphql_repos_data,
                },
            }
        }
    }

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=mock_graphql_resp)
    )

    headers = {"Authorization": "Bearer test_token"}
    response = client.get("/api/v1/orgs/acme-corp/users", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["organization"] == "acme-corp"
    assert data["total_users"] == 4
    logins = [u["login"] for u in data["users"]]
    assert "alice" in logins
    assert "bob" in logins


@respx.mock
def test_list_organization_repos(client, sample_graphql_repos_data):
    mock_graphql_resp = {
        "data": {
            "repositoryOwner": {
                "login": "acme-corp",
                "repositories": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "totalCount": len(sample_graphql_repos_data),
                    "nodes": sample_graphql_repos_data,
                },
            }
        }
    }

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=mock_graphql_resp)
    )

    headers = {"Authorization": "Bearer test_token"}
    response = client.get("/api/v1/orgs/acme-corp/repos", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["organization"] == "acme-corp"
    assert data["total_repositories"] == 2
    repo_names = [r["name"] for r in data["repositories"]]
    assert "core-backend" in repo_names
    assert "frontend-app" in repo_names


def test_clear_cache_endpoint(client):
    response = client.post("/api/v1/cache/clear")
    assert response.status_code == 200
    assert "cleared" in response.json()["message"].lower()
