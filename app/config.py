"""Application configuration and settings."""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service info
    APP_NAME: str = "GitHub Organization Access Report Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # GitHub API Configuration
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"

    # GitHub App Authentication (Optional Enterprise mode)
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_APP_PRIVATE_KEY: Optional[str] = None  # PEM string or path to .pem file
    GITHUB_APP_INSTALLATION_ID: Optional[str] = None

    # Performance & Concurrency Tuning
    MAX_CONCURRENT_REQUESTS: int = 10
    REQUEST_TIMEOUT_SECONDS: float = 30.0
    MAX_RETRIES: int = 3
    BACKOFF_FACTOR: float = 1.5

    # Caching
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 300  # 5 minutes
    CACHE_MAX_ENTRIES: int = 100

    # Collector strategy: 'graphql' (fast, batched) or 'rest' (standard REST API)
    DEFAULT_COLLECTOR: str = "graphql"


@lru_cache()
def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    return Settings()
