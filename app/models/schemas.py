"""Pydantic schemas and enums for GitHub Access Report."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl


class PermissionLevel(str, Enum):
    """GitHub repository permission levels in descending order of privilege."""

    ADMIN = "ADMIN"
    MAINTAIN = "MAINTAIN"
    WRITE = "WRITE"
    TRIAGE = "TRIAGE"
    READ = "READ"
    NONE = "NONE"

    @classmethod
    def rank(cls, perm: str) -> int:
        """Numeric rank for sorting and comparison: Higher means more privilege."""
        ranks = {
            cls.ADMIN.value: 50,
            "ADMIN": 50,
            "ADMIN_ACCESS": 50,
            cls.MAINTAIN.value: 40,
            "MAINTAIN": 40,
            cls.WRITE.value: 30,
            "WRITE": 30,
            "PUSH": 30,
            cls.TRIAGE.value: 20,
            "TRIAGE": 20,
            cls.READ.value: 10,
            "READ": 10,
            "PULL": 10,
            cls.NONE.value: 0,
            "NONE": 0,
        }
        return ranks.get(perm.upper(), 0)

    @classmethod
    def normalize(cls, perm: Optional[str]) -> "PermissionLevel":
        """Normalize various GitHub API permission strings into PermissionLevel enum."""
        if not perm:
            return cls.NONE
        p = perm.upper()
        if p in ("ADMIN", "ADMIN_ACCESS"):
            return cls.ADMIN
        if p == "MAINTAIN":
            return cls.MAINTAIN
        if p in ("WRITE", "PUSH"):
            return cls.WRITE
        if p == "TRIAGE":
            return cls.TRIAGE
        if p in ("READ", "PULL"):
            return cls.READ
        return cls.NONE

    def __ge__(self, other: "PermissionLevel") -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank(self.value) >= self.rank(other.value)
        return False

    def __gt__(self, other: "PermissionLevel") -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank(self.value) > self.rank(other.value)
        return False

    def __le__(self, other: "PermissionLevel") -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank(self.value) <= self.rank(other.value)
        return False

    def __lt__(self, other: "PermissionLevel") -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank(self.value) < self.rank(other.value)
        return False


class AffiliationFilter(str, Enum):
    """Collaborator affiliation filter."""

    ALL = "ALL"
    DIRECT = "DIRECT"
    OUTSIDE = "OUTSIDE"


class RepositoryAccess(BaseModel):
    """Information regarding a user's access to a specific repository."""

    name: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full repository name in owner/repo format")
    is_private: bool = Field(..., description="Whether the repository is private")
    permission: PermissionLevel = Field(..., description="Normalized access level (ADMIN, MAINTAIN, WRITE, TRIAGE, READ)")
    raw_permission: Optional[str] = Field(None, description="Original permission string returned by GitHub")
    affiliation: Optional[str] = Field("DIRECT", description="Collaborator affiliation (DIRECT, OUTSIDE, TEAM, etc.)")
    url: Optional[str] = Field(None, description="GitHub repository HTML URL")
    description: Optional[str] = Field(None, description="Repository description")


class UserAccessReport(BaseModel):
    """Aggregated access report for an individual GitHub user."""

    login: str = Field(..., description="GitHub user handle")
    name: Optional[str] = Field(None, description="User's full display name if available")
    avatar_url: Optional[str] = Field(None, description="User avatar image URL")
    html_url: Optional[str] = Field(None, description="GitHub user profile URL")
    total_repositories_accessible: int = Field(..., description="Total repositories this user has access to")
    highest_permission: PermissionLevel = Field(..., description="Highest permission level across all accessible repositories")
    repositories: List[RepositoryAccess] = Field(default_factory=list, description="List of repositories accessible by this user")


class OrganizationSummary(BaseModel):
    """Aggregate summary statistics for the organization."""

    total_repositories: int = Field(..., description="Total repositories scanned in the organization")
    total_users: int = Field(..., description="Total unique users with repository access")
    private_repositories: int = Field(..., description="Count of private repositories")
    public_repositories: int = Field(..., description="Count of public repositories")
    permission_distribution: Dict[str, int] = Field(..., description="Count of users by their highest permission level")


class OrganizationAccessReport(BaseModel):
    """Complete access report mapping users to repositories for an organization."""

    organization: str = Field(..., description="GitHub organization name")
    generated_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of report generation (UTC)")
    cached: bool = Field(False, description="Whether this response was served from cache")
    execution_time_seconds: float = Field(..., description="Time taken to collect and generate the report")
    collector_used: str = Field("graphql", description="Collector engine used (graphql or rest)")
    summary: Optional[OrganizationSummary] = Field(None, description="Organization-level summary metrics")
    users: List[UserAccessReport] = Field(default_factory=list, description="User access list")


class RepositorySummary(BaseModel):
    """High-level repository metadata and collaborator count."""

    name: str
    full_name: str
    is_private: bool
    description: Optional[str] = None
    collaborators_count: int
    url: Optional[str] = None


class OrganizationRepositoriesResponse(BaseModel):
    """List of repositories in an organization."""

    organization: str
    total_repositories: int
    repositories: List[RepositorySummary]


class OrganizationUserItem(BaseModel):
    """Quick overview of a user in an organization."""

    login: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    repositories_count: int
    highest_permission: PermissionLevel


class OrganizationUsersResponse(BaseModel):
    """List of users found across organization repositories."""

    organization: str
    total_users: int
    users: List[OrganizationUserItem]


class HealthCheckResponse(BaseModel):
    """Service health and connectivity status."""

    status: str = Field("healthy", description="Service status: healthy, degraded, or unhealthy")
    version: str = Field(..., description="Application version")
    auth_configured: bool = Field(..., description="Whether a default auth credential is configured")
    auth_type: Optional[str] = Field(None, description="Configured auth mechanism (PAT, GitHub App, None)")
    github_reachable: bool = Field(..., description="Whether GitHub API is reachable")
    rate_limit: Optional[Dict[str, Any]] = Field(None, description="Current rate limit status")


class ErrorResponse(BaseModel):
    """Standardized API error response."""

    error: str = Field(..., description="Error category or type")
    message: str = Field(..., description="Human-readable error description")
    status_code: int = Field(..., description="HTTP status code")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional context or debugging details")
