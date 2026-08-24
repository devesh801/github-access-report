"""REST API route handlers for GitHub Access Report."""

import logging
import time
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path

from app.api.dependencies import (
    get_auth_provider,
    get_cache,
    get_github_client,
    get_rate_limiter,
)
from app.config import Settings, get_settings
from app.core.auth import GitHubAuthProvider
from app.core.cache import TTLCache
from app.core.rate_limiter import GitHubRateLimitTracker
from app.models.schemas import (
    AffiliationFilter,
    HealthCheckResponse,
    OrganizationAccessReport,
    OrganizationRepositoriesResponse,
    OrganizationUsersResponse,
    OrganizationUserItem,
    PermissionLevel,
    RepositorySummary,
)
from app.services.github_client import GitHubClient
from app.services.graphql_collector import GraphQLCollector
from app.services.report_aggregator import AccessReportAggregator
from app.services.rest_collector import RestCollector

logger = logging.getLogger(__name__)

router = APIRouter()


async def generate_report(
    org: str,
    client: GitHubClient,
    cache: TTLCache,
    settings: Settings,
    min_permission: Optional[PermissionLevel] = None,
    user: Optional[str] = None,
    repository: Optional[str] = None,
    affiliation: AffiliationFilter = AffiliationFilter.ALL,
    include_summary: bool = True,
    refresh: bool = False,
    collector: Optional[str] = None,
) -> OrganizationAccessReport:
    """Internal business logic to generate or retrieve cached organization access report."""
    start_time = time.time()
    org_clean = org.strip()
    collector_type = (collector or settings.DEFAULT_COLLECTOR).lower()

    cache_key = f"raw_org:{org_clean}:{affiliation.value}:{collector_type}"
    raw_repo_data = None
    served_from_cache = False

    if settings.CACHE_ENABLED and not refresh:
        raw_repo_data = await cache.get(cache_key)
        if raw_repo_data is not None:
            served_from_cache = True
            logger.info("Serving access report data for '%s' from cache", org_clean)

    if raw_repo_data is None:
        logger.info("Fetching live data for organization '%s' using %s engine", org_clean, collector_type)
        if collector_type == "rest":
            rest_collector = RestCollector(client)
            raw_repo_data = await rest_collector.collect_organization_data(org_clean, affiliation=affiliation)
        else:
            graphql_collector = GraphQLCollector(client)
            raw_repo_data = await graphql_collector.collect_organization_data(org_clean, affiliation=affiliation)

        if settings.CACHE_ENABLED:
            await cache.set(cache_key, raw_repo_data)

    elapsed_time = time.time() - start_time

    return AccessReportAggregator.aggregate(
        organization=org_clean,
        repositories_data=raw_repo_data,
        execution_time=elapsed_time,
        collector_used=collector_type,
        cached=served_from_cache,
        min_permission=min_permission,
        target_user=user,
        target_repo=repository,
        include_summary=include_summary,
    )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health check & GitHub connectivity",
    tags=["System"],
)
async def health_check(
    settings: Settings = Depends(get_settings),
    auth_provider: GitHubAuthProvider = Depends(get_auth_provider),
    rate_limiter: GitHubRateLimitTracker = Depends(get_rate_limiter),
):
    """Check service operational status and inspect rate limit quotas."""
    auth_configured = bool(
        settings.GITHUB_TOKEN
        or (settings.GITHUB_APP_ID and settings.GITHUB_APP_INSTALLATION_ID and settings.GITHUB_APP_PRIVATE_KEY)
    )
    auth_type = "PAT" if settings.GITHUB_TOKEN else ("GitHub App" if auth_configured else None)

    rate_status = await rate_limiter.get_status()
    rate_limit_info = rate_status.to_dict() if rate_status.limit is not None else None

    return HealthCheckResponse(
        status="healthy",
        version=settings.APP_VERSION,
        auth_configured=auth_configured,
        auth_type=auth_type,
        github_reachable=True,
        rate_limit=rate_limit_info,
    )


@router.get(
    "/orgs/{org}/access-report",
    response_model=OrganizationAccessReport,
    summary="Generate organization user repository access report",
    tags=["Access Reports"],
)
async def get_organization_access_report(
    org: str = Path(..., description="GitHub organization login (e.g. 'github', 'kubernetes', 'acme')"),
    min_permission: Optional[PermissionLevel] = Query(None, description="Minimum permission level (READ, TRIAGE, WRITE, MAINTAIN, ADMIN)"),
    user: Optional[str] = Query(None, description="Filter report for a specific user login"),
    repository: Optional[str] = Query(None, description="Filter report to users with access to a specific repository"),
    affiliation: AffiliationFilter = Query(AffiliationFilter.ALL, description="Collaborator affiliation (ALL, DIRECT, OUTSIDE)"),
    include_summary: bool = Query(True, description="Include organization summary metrics in response"),
    refresh: bool = Query(False, description="Bypass cache and force fresh data collection"),
    collector: Optional[str] = Query(None, description="Data collector engine: 'graphql' (fast, default) or 'rest'"),
    cache: TTLCache = Depends(get_cache),
    client: GitHubClient = Depends(get_github_client),
    settings: Settings = Depends(get_settings),
):
    """
    Retrieve all repositories for the given GitHub organization, discover all collaborators,
    and generate an aggregated user-to-repositories access report.
    """
    return await generate_report(
        org=org,
        client=client,
        cache=cache,
        settings=settings,
        min_permission=min_permission,
        user=user,
        repository=repository,
        affiliation=affiliation,
        include_summary=include_summary,
        refresh=refresh,
        collector=collector,
    )


@router.get(
    "/orgs/{org}/users",
    response_model=OrganizationUsersResponse,
    summary="List all users with repository access in organization",
    tags=["Access Reports"],
)
async def list_organization_users(
    org: str = Path(..., description="GitHub organization name"),
    refresh: bool = Query(False, description="Bypass cache and force fresh data collection"),
    cache: TTLCache = Depends(get_cache),
    client: GitHubClient = Depends(get_github_client),
    settings: Settings = Depends(get_settings),
):
    """Return a simplified index of all users possessing access across organization repositories."""
    report = await generate_report(
        org=org,
        client=client,
        cache=cache,
        settings=settings,
        include_summary=False,
        refresh=refresh,
    )

    user_items = [
        OrganizationUserItem(
            login=u.login,
            name=u.name,
            avatar_url=u.avatar_url,
            repositories_count=u.total_repositories_accessible,
            highest_permission=u.highest_permission,
        )
        for u in report.users
    ]

    return OrganizationUsersResponse(
        organization=org,
        total_users=len(user_items),
        users=user_items,
    )


@router.get(
    "/orgs/{org}/repos",
    response_model=OrganizationRepositoriesResponse,
    summary="List all repositories in organization with collaborator counts",
    tags=["Access Reports"],
)
async def list_organization_repositories(
    org: str = Path(..., description="GitHub organization name"),
    refresh: bool = Query(False, description="Bypass cache and force fresh data collection"),
    cache: TTLCache = Depends(get_cache),
    client: GitHubClient = Depends(get_github_client),
    settings: Settings = Depends(get_settings),
):
    """Return an overview of repositories and collaborator counts in an organization."""
    collector = GraphQLCollector(client)
    cache_key = f"raw_org:{org}:ALL:graphql"

    raw_repo_data = None
    if settings.CACHE_ENABLED and not refresh:
        raw_repo_data = await cache.get(cache_key)

    if raw_repo_data is None:
        raw_repo_data = await collector.collect_organization_data(org, affiliation=AffiliationFilter.ALL)
        if settings.CACHE_ENABLED:
            await cache.set(cache_key, raw_repo_data)

    repo_summaries = []
    for r in raw_repo_data:
        collabs = r.get("collaborators", {})
        edges = collabs.get("edges", [])
        total_count = collabs.get("totalCount", len(edges))

        repo_summaries.append(
            RepositorySummary(
                name=r.get("name", ""),
                full_name=r.get("nameWithOwner", f"{org}/{r.get('name')}"),
                is_private=bool(r.get("isPrivate", False)),
                description=r.get("description"),
                collaborators_count=total_count,
                url=r.get("url"),
            )
        )

    return OrganizationRepositoriesResponse(
        organization=org,
        total_repositories=len(repo_summaries),
        repositories=sorted(repo_summaries, key=lambda x: x.name.lower()),
    )


@router.post(
    "/cache/clear",
    summary="Purge cached organization reports",
    tags=["System"],
)
async def clear_cache(cache: TTLCache = Depends(get_cache)):
    """Clear all entries in the server-side TTL cache."""
    await cache.clear()
    return {"message": "Cache successfully cleared."}
