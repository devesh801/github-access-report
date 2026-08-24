"""Unit tests for GitHubRateLimitTracker."""

import pytest
import time
from app.core.rate_limiter import GitHubRateLimitTracker


@pytest.mark.asyncio
async def test_update_from_headers():
    tracker = GitHubRateLimitTracker()
    now_ts = int(time.time()) + 3600

    headers = {
        "x-ratelimit-limit": "5000",
        "x-ratelimit-remaining": "4850",
        "x-ratelimit-reset": str(now_ts),
        "x-ratelimit-resource": "graphql",
    }

    await tracker.update_from_headers(headers)
    status = await tracker.get_status()

    assert status.limit == 5000
    assert status.remaining == 4850
    assert status.reset_at == now_ts
    assert status.resource == "graphql"
    assert not status.is_exhausted
    assert status.seconds_until_reset > 0


def test_calculate_backoff():
    # Attempt 1
    delay1 = GitHubRateLimitTracker.calculate_backoff(attempt=1, base_delay=1.0, jitter=False)
    assert delay1 == 1.0

    # Attempt 2
    delay2 = GitHubRateLimitTracker.calculate_backoff(attempt=2, base_delay=1.0, jitter=False)
    assert delay2 == 2.0

    # Attempt 3
    delay3 = GitHubRateLimitTracker.calculate_backoff(attempt=3, base_delay=1.0, jitter=False)
    assert delay3 == 4.0

    # Override by retry_after
    retry_delay = GitHubRateLimitTracker.calculate_backoff(attempt=1, retry_after=15)
    assert retry_delay == 15.0
