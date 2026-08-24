"""In-memory TTL cache with thread-safe async access."""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    """In-memory key-value cache with time-to-live expiration."""

    def __init__(self, default_ttl: int = 300, max_entries: int = 100):
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._cache: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve item if present and not expired."""
        async with self._lock:
            if key not in self._cache:
                return None

            value, expires_at = self._cache[key]
            if time.time() >= expires_at:
                del self._cache[key]
                return None

            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store item with TTL in seconds."""
        async with self._lock:
            # Clean up expired items if at capacity
            if len(self._cache) >= self.max_entries:
                now = time.time()
                expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
                for k in expired:
                    del self._cache[k]

                # If still at capacity, evict the oldest expiring item
                if len(self._cache) >= self.max_entries:
                    oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                    del self._cache[oldest_key]

            effective_ttl = ttl if ttl is not None else self.default_ttl
            expires_at = time.time() + effective_ttl
            self._cache[key] = (value, expires_at)

    async def delete(self, key: str) -> bool:
        """Delete an item from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()

    async def size(self) -> int:
        """Return count of unexpired items."""
        async with self._lock:
            now = time.time()
            return sum(1 for _, exp in self._cache.values() if now < exp)
