"""REST API data collector fallback with concurrent batch fetching."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from app.models.schemas import AffiliationFilter
from app.services.github_client import GitHubClient

logger = logging.getLogger(__name__)


class RestCollector:
    """Collects repositories and collaborator permissions using GitHub REST API v3."""

    def __init__(self, client: GitHubClient):
        self.client = client

    async def collect_organization_data(
        self,
        org_name: str,
        affiliation: AffiliationFilter = AffiliationFilter.ALL,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all repositories in the organization and their collaborators via REST API concurrently.
        """
        logger.info("Starting REST collection for organization '%s'", org_name)

        # 1. Fetch all repositories in organization (paginated)
        repositories = await self._fetch_all_org_repositories(org_name)
        logger.info("Retrieved %d repositories for '%s' via REST. Fetching collaborators concurrently...", len(repositories), org_name)

        # 2. Fetch collaborators for each repository concurrently
        affiliation_param = affiliation.value.lower() if affiliation != AffiliationFilter.ALL else "all"

        tasks = [
            self._fetch_repo_with_collaborators(org_name, repo, affiliation_param)
            for repo in repositories
        ]

        enriched_repos = await asyncio.gather(*tasks)
        logger.info("Completed REST data collection for '%s'", org_name)
        return enriched_repos

    async def _fetch_all_org_repositories(self, org_name: str) -> List[Dict[str, Any]]:
        """Fetch all repositories under an organization with REST pagination."""
        repos = []
        page = 1
        per_page = 100

        while True:
            endpoint = f"orgs/{org_name}/repos"
            params = {"type": "all", "per_page": per_page, "page": page}
            page_data = await self.client.get_rest(endpoint, params=params)

            if not isinstance(page_data, list) or not page_data:
                break

            repos.extend(page_data)
            if len(page_data) < per_page:
                break
            page += 1

        return repos

    async def _fetch_repo_with_collaborators(
        self,
        org_name: str,
        repo_data: Dict[str, Any],
        affiliation: str,
    ) -> Dict[str, Any]:
        """Fetch all collaborators for a single repository, handling multi-page lists."""
        repo_name = repo_data.get("name", "")
        collaborators = []
        page = 1
        per_page = 100

        while True:
            endpoint = f"repos/{org_name}/{repo_name}/collaborators"
            params = {"affiliation": affiliation, "per_page": per_page, "page": page}
            try:
                page_collabs = await self.client.get_rest(endpoint, params=params)
                if not isinstance(page_collabs, list) or not page_collabs:
                    break

                collaborators.extend(page_collabs)
                if len(page_collabs) < per_page:
                    break
                page += 1
            except Exception as e:
                # If we don't have access to list collaborators on a specific repo, log and continue
                logger.warning("Could not fetch collaborators for %s/%s: %s", org_name, repo_name, e)
                break

        # Convert REST collaborator objects to normalized edges structure
        edges = []
        for c in collaborators:
            perms = c.get("permissions", {})
            role = "READ"
            if perms.get("admin"):
                role = "ADMIN"
            elif perms.get("maintain"):
                role = "MAINTAIN"
            elif perms.get("push"):
                role = "WRITE"
            elif perms.get("triage"):
                role = "TRIAGE"
            elif perms.get("pull"):
                role = "READ"

            edges.append({
                "permission": role,
                "node": {
                    "login": c.get("login"),
                    "name": c.get("name"),
                    "avatarUrl": c.get("avatar_url"),
                    "url": c.get("html_url"),
                },
                "permissionSources": [],
            })

        return {
            "name": repo_name,
            "nameWithOwner": repo_data.get("full_name", f"{org_name}/{repo_name}"),
            "isPrivate": repo_data.get("private", False),
            "description": repo_data.get("description"),
            "url": repo_data.get("html_url"),
            "collaborators": {
                "totalCount": len(edges),
                "edges": edges,
            },
        }
