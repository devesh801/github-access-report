"""Aggregates raw repository-collaborator data into user-centric access reports."""

from collections import defaultdict
from typing import Any, Dict, List, Optional
from app.models.schemas import (
    AffiliationFilter,
    OrganizationAccessReport,
    OrganizationSummary,
    PermissionLevel,
    RepositoryAccess,
    UserAccessReport,
)


class AccessReportAggregator:
    """Transforms repository collaborator records into aggregated user access reports."""

    @staticmethod
    def aggregate(
        organization: str,
        repositories_data: List[Dict[str, Any]],
        execution_time: float,
        collector_used: str = "graphql",
        cached: bool = False,
        min_permission: Optional[PermissionLevel] = None,
        target_user: Optional[str] = None,
        target_repo: Optional[str] = None,
        include_summary: bool = True,
    ) -> OrganizationAccessReport:
        """
        Invert repository -> collaborator data into a comprehensive User -> Repositories mapping.
        """
        users_map: Dict[str, Dict[str, Any]] = {}
        total_repos_count = len(repositories_data)
        private_repos_count = 0
        public_repos_count = 0

        target_user_lower = target_user.lower() if target_user else None
        target_repo_lower = target_repo.lower() if target_repo else None

        for repo in repositories_data:
            repo_name = repo.get("name", "")
            repo_full_name = repo.get("nameWithOwner", f"{organization}/{repo_name}")
            is_private = bool(repo.get("isPrivate", False))
            repo_url = repo.get("url")
            repo_desc = repo.get("description")

            if is_private:
                private_repos_count += 1
            else:
                public_repos_count += 1

            if target_repo_lower and repo_name.lower() != target_repo_lower and repo_full_name.lower() != target_repo_lower:
                continue

            collabs_data = repo.get("collaborators", {})
            edges = collabs_data.get("edges", [])

            for edge in edges:
                if not edge:
                    continue

                user_node = edge.get("node")
                if not user_node:
                    continue

                login = user_node.get("login")
                if not login:
                    continue

                if target_user_lower and login.lower() != target_user_lower:
                    continue

                raw_perm = edge.get("permission", "READ")
                perm_level = PermissionLevel.normalize(raw_perm)

                # Filter by minimum permission if requested
                if min_permission and perm_level < min_permission:
                    continue

                # Determine affiliation from permissionSources or default
                affiliation = "DIRECT"
                sources = edge.get("permissionSources", [])
                if sources:
                    source_types = []
                    for s in sources:
                        source_obj = s.get("source", {})
                        if "combinedSlug" in source_obj or "Team" in str(source_obj):
                            source_types.append("TEAM")
                        elif "Organization" in str(source_obj):
                            source_types.append("ORG_ADMIN")
                    if source_types:
                        affiliation = "/".join(set(source_types))

                repo_access = RepositoryAccess(
                    name=repo_name,
                    full_name=repo_full_name,
                    is_private=is_private,
                    permission=perm_level,
                    raw_permission=raw_perm,
                    affiliation=affiliation,
                    url=repo_url,
                    description=repo_desc,
                )

                if login not in users_map:
                    users_map[login] = {
                        "login": login,
                        "name": user_node.get("name"),
                        "avatar_url": user_node.get("avatarUrl"),
                        "html_url": user_node.get("url"),
                        "repositories": [],
                        "highest_rank": -1,
                        "highest_perm": PermissionLevel.NONE,
                    }

                user_entry = users_map[login]
                user_entry["repositories"].append(repo_access)

                # Track highest permission rank
                current_rank = PermissionLevel.rank(perm_level.value)
                if current_rank > user_entry["highest_rank"]:
                    user_entry["highest_rank"] = current_rank
                    user_entry["highest_perm"] = perm_level

        # Build list of UserAccessReport objects sorted by login
        user_reports: List[UserAccessReport] = []
        perm_distribution: Dict[str, int] = defaultdict(int)

        for login, data in sorted(users_map.items(), key=lambda item: item[0].lower()):
            # Sort repositories by name
            sorted_repos = sorted(data["repositories"], key=lambda r: r.name.lower())
            highest_p = data["highest_perm"] if data["highest_perm"] != PermissionLevel.NONE else PermissionLevel.READ

            perm_distribution[highest_p.value] += 1

            user_reports.append(
                UserAccessReport(
                    login=data["login"],
                    name=data["name"],
                    avatar_url=data["avatar_url"],
                    html_url=data["html_url"],
                    total_repositories_accessible=len(sorted_repos),
                    highest_permission=highest_p,
                    repositories=sorted_repos,
                )
            )

        summary = None
        if include_summary:
            # Ensure all standard permission levels exist in distribution dict
            for lvl in [PermissionLevel.ADMIN, PermissionLevel.MAINTAIN, PermissionLevel.WRITE, PermissionLevel.TRIAGE, PermissionLevel.READ]:
                if lvl.value not in perm_distribution:
                    perm_distribution[lvl.value] = 0

            summary = OrganizationSummary(
                total_repositories=total_repos_count,
                total_users=len(user_reports),
                private_repositories=private_repos_count,
                public_repositories=public_repos_count,
                permission_distribution=dict(perm_distribution),
            )

        return OrganizationAccessReport(
            organization=organization,
            cached=cached,
            execution_time_seconds=round(execution_time, 3),
            collector_used=collector_used,
            summary=summary,
            users=user_reports,
        )
