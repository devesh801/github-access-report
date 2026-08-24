"""Domain-specific exceptions for GitHub Access Report Service."""

from typing import Optional


class GitHubAccessError(Exception):
    """Base exception for all GitHub Access Report errors."""

    def __init__(self, message: str, status_code: int = 500, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class GitHubAuthError(GitHubAccessError):
    """Raised when authentication with GitHub fails or credentials are missing."""

    def __init__(self, message: str = "Invalid or missing GitHub authentication credentials", details: Optional[dict] = None):
        super().__init__(message=message, status_code=401, details=details)


class GitHubPermissionError(GitHubAccessError):
    """Raised when the authenticated token lacks permission to access the organization or repositories."""

    def __init__(self, message: str = "Insufficient permissions to access the requested resource", details: Optional[dict] = None):
        super().__init__(message=message, status_code=403, details=details)


class GitHubRateLimitExceededError(GitHubAccessError):
    """Raised when GitHub rate limit is exceeded."""

    def __init__(
        self,
        message: str = "GitHub API rate limit exceeded",
        retry_after: Optional[int] = None,
        reset_at: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        det = details or {}
        if retry_after is not None:
            det["retry_after"] = retry_after
        if reset_at is not None:
            det["reset_at"] = reset_at
        super().__init__(message=message, status_code=429, details=det)
        self.retry_after = retry_after
        self.reset_at = reset_at


class GitHubNotFoundError(GitHubAccessError):
    """Raised when the requested organization or repository does not exist."""

    def __init__(self, message: str = "GitHub organization or resource not found", details: Optional[dict] = None):
        super().__init__(message=message, status_code=404, details=details)


class GitHubAPIError(GitHubAccessError):
    """Raised when an unexpected error occurs communicating with GitHub API."""

    def __init__(self, message: str, status_code: int = 502, details: Optional[dict] = None):
        super().__init__(message=message, status_code=status_code, details=details)
