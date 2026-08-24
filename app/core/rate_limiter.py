"""Rate limit monitoring and backoff management."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStatus:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: Optional[int] = None
    resource: Optional[str] = None
    last_updated: float = 0.0

    @property
    def seconds_until_reset(self) -> float:
        if self.reset_at is None:
            return 0.0
        return max(0.0, self.reset_at - time.time())

    @property
    def is_exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "seconds_until_reset": round(self.seconds_until_reset, 1),
            "resource": self.resource,
        }


class GitHubRateLimitTracker:
    """Thread-safe rate limit state tracker and exponential backoff utility."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._status = RateLimitStatus()

    async def update_from_headers(self, headers: Any) -> None:
        """Parse standard GitHub rate limit headers."""
        async with self._lock:
            try:
                limit_hdr = headers.get("x-ratelimit-limit")
                remaining_hdr = headers.get("x-ratelimit-remaining")
                reset_hdr = headers.get("x-ratelimit-reset")
                resource_hdr = headers.get("x-ratelimit-resource")

                if limit_hdr is not None:
                    self._status.limit = int(limit_hdr)
                if remaining_hdr is not None:
                    self._status.remaining = int(remaining_hdr)
                if reset_hdr is not None:
                    self._status.reset_at = int(reset_hdr)
                if resource_hdr is not None:
                    self._status.resource = resource_hdr

                self._status.last_updated = time.time()

                if self._status.remaining is not None and self._status.remaining < 20:
                    logger.warning(
                        "GitHub rate limit is low! Remaining: %s, resets in %ss",
                        self._status.remaining,
                        round(self._status.seconds_until_reset, 1),
                    )
            except (ValueError, TypeError) as e:
                logger.debug("Failed to parse rate limit headers: %s", e)

    async def get_status(self) -> RateLimitStatus:
        async with self._lock:
            return RateLimitStatus(
                limit=self._status.limit,
                remaining=self._status.remaining,
                reset_at=self._status.reset_at,
                resource=self._status.resource,
                last_updated=self._status.last_updated,
            )

    @staticmethod
    def calculate_backoff(
        attempt: int,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True,
        retry_after: Optional[int] = None,
    ) -> float:
        """Calculate delay in seconds for retry with exponential backoff and jitter."""
        if retry_after is not None and retry_after > 0:
            return float(retry_after)

        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        if jitter:
            delay += random.uniform(0.1, 0.5 * delay)
        return min(max_delay, delay)
