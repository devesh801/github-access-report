"""High-performance batched GraphQL data collector for GitHub organizations."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from app.core.exceptions import GitHubNotFoundError
from app.models.schemas import AffiliationFilter
from app.services.github_client import GitHubClient

logger = logging.getLogger(__name__)

ORG_REPOSITORIES_QUERY = """
query OrgReposWithCollaborators($org: String!, $cursor: String, $affiliation: CollaboratorAffiliation) {
  organization(login: $org) {
    login
    name
    repositories(first: 50, after: $cursor, orderBy: {field: NAME, direction: ASC}) {
      pageInfo {
        hasNextPage
        endCursor
      }
      totalCount
      nodes {
        id
        name
        nameWithOwner
        isPrivate
        description
        url
        collaborators(first: 100, affiliation: $affiliation) {
          pageInfo {
            hasNextPage
            endCursor
          }
          totalCount
          edges {
            permission
            permissionSources {
              role
              source {
                ... on Team {
                  name
                  combinedSlug
                }
              }
            }
            node {
              login
              name
              avatarUrl
              url
            }
          }
        }
      }
    }
  }
}
"""

REPO_COLLABORATORS_PAGINATION_QUERY = """
query RepoCollaboratorsPagination($owner: String!, $name: String!, $cursor: String!, $affiliation: CollaboratorAffiliation) {
  repository(owner: $owner, name: $name) {
    collaborators(first: 100, after: $cursor, affiliation: $affiliation) {
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        permission
        permissionSources {
          role
          source {
            ... on Team {
              name
              combinedSlug
            }
          }
        }
        node {
          login
          name
          avatarUrl
          url
        }
      }
    }
  }
}
"""


class GraphQLCollector:
    """Collects repositories and collaborator permissions using GitHub GraphQL API."""

    def __init__(self, client: GitHubClient):
        self.client = client

    async def collect_organization_data(
        self,
        org_name: str,
        affiliation: AffiliationFilter = AffiliationFilter.ALL,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all repositories and their collaborator edges for an organization.
        Returns a list of raw repository objects with complete collaborator lists.
        """
        affiliation_param = affiliation.value if affiliation != AffiliationFilter.ALL else None
        repositories: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        has_next_repo_page = True

        logger.info("Starting GraphQL collection for organization '%s' (affiliation: %s)", org_name, affiliation.value)

        # 1. Page through organization repositories
        while has_next_repo_page:
            variables: Dict[str, Any] = {"org": org_name, "cursor": cursor}
            if affiliation_param:
                variables["affiliation"] = affiliation_param

            data = await self.client.execute_graphql(ORG_REPOSITORIES_QUERY, variables)
            org_data = data.get("organization")

            if not org_data:
                raise GitHubNotFoundError(f"Organization '{org_name}' not found or accessible.")

            repos_page = org_data.get("repositories", {})
            nodes = repos_page.get("nodes", [])

            for repo_node in nodes:
                if repo_node is not None:
                    repositories.append(repo_node)

            page_info = repos_page.get("pageInfo", {})
            has_next_repo_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        logger.info("Found %d repositories in organization '%s'. Checking for deep collaborator pagination...", len(repositories), org_name)

        # 2. Concurrently fetch remaining collaborator pages for any repos with >100 collaborators
        deep_pagination_tasks = []
        for repo in repositories:
            collabs = repo.get("collaborators", {})
            page_info = collabs.get("pageInfo", {})
            if page_info.get("hasNextPage", False):
                deep_pagination_tasks.append(
                    self._fetch_all_remaining_collaborators(
                        owner=org_name,
                        repo_name=repo["name"],
                        initial_cursor=page_info.get("endCursor"),
                        affiliation=affiliation_param,
                        target_edges_list=collabs.setdefault("edges", []),
                    )
                )

        if deep_pagination_tasks:
            logger.info("Fetching remaining collaborators for %d large repositories concurrently...", len(deep_pagination_tasks))
            await asyncio.gather(*deep_pagination_tasks)

        logger.info("Completed GraphQL data collection for '%s' (%d total repositories)", org_name, len(repositories))
        return repositories

    async def _fetch_all_remaining_collaborators(
        self,
        owner: str,
        repo_name: str,
        initial_cursor: str,
        affiliation: Optional[str],
        target_edges_list: List[Dict[str, Any]],
    ) -> None:
        """Paginate through remaining collaborators of a single repository."""
        cursor: Optional[str] = initial_cursor
        has_next = True

        while has_next and cursor:
            vars_dict: Dict[str, Any] = {
                "owner": owner,
                "name": repo_name,
                "cursor": cursor,
            }
            if affiliation:
                vars_dict["affiliation"] = affiliation

            data = await self.client.execute_graphql(REPO_COLLABORATORS_PAGINATION_QUERY, vars_dict)
            repo_data = data.get("repository")
            if not repo_data:
                break

            collabs = repo_data.get("collaborators", {})
            edges = collabs.get("edges", [])
            for edge in edges:
                if edge:
                    target_edges_list.append(edge)

            page_info = collabs.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
