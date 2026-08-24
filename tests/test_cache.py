"""Unit tests for TTLCache."""

import pytest
import asyncio
from app.core.cache import TTLCache


@pytest.mark.asyncio
async def test_ttl_cache_basic_get_set():
    cache = TTLCache(default_ttl=10, max_entries=5)
    await cache.set("k1", "v1")

    val = await cache.get("k1")
    assert val == "v1"

    missing = await cache.get("non_existent")
    assert missing is None


@pytest.mark.asyncio
async def test_ttl_cache_expiry():
    cache = TTLCache(default_ttl=1, max_entries=5)
    await cache.set("k_fast", "value_fast", ttl=0)
    await asyncio.sleep(0.01)

    val = await cache.get("k_fast")
    assert val is None


@pytest.mark.asyncio
async def test_ttl_cache_delete_and_clear():
    cache = TTLCache(default_ttl=10, max_entries=5)
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")

    assert await cache.size() == 2

    deleted = await cache.delete("k1")
    assert deleted is True
    assert await cache.get("k1") is None
    assert await cache.size() == 1

    await cache.clear()
    assert await cache.size() == 0
