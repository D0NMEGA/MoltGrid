"""
MoltGrid Response Cache -- thread-safe TTL cache for endpoint responses.

Reduces database load on high-traffic public endpoints by caching responses
in memory with configurable time-to-live per key.
"""

import time
import threading
import functools
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("moltgrid.cache")


class TTLCache:
    """Thread-safe in-memory cache with per-key TTL expiration."""

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Return cached value if present and not expired, else None."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a value with TTL in seconds."""
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl_seconds)

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        """Return the number of entries (including possibly expired)."""
        with self._lock:
            return len(self._store)

    def cleanup(self) -> int:
        """Remove expired entries and return count removed."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, (_, exp) in self._store.items() if now > exp
            ]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed


# Global cache instance shared across all endpoints
response_cache = TTLCache()


def cached_response(ttl_seconds: float, key_func: Optional[Callable] = None):
    """Decorator for FastAPI endpoint functions that caches JSON-serializable responses.

    Args:
        ttl_seconds: How long to cache the response.
        key_func: Optional callable(request) -> str to generate cache key.
                  If None, uses the endpoint function name as key.

    Works with both sync and async endpoint functions.
    """

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_key = key_func(*args, **kwargs) if key_func else func.__name__
            cached = response_cache.get(cache_key)
            if cached is not None:
                return cached
            result = await func(*args, **kwargs)
            response_cache.set(cache_key, result, ttl_seconds)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = key_func(*args, **kwargs) if key_func else func.__name__
            cached = response_cache.get(cache_key)
            if cached is not None:
                return cached
            result = func(*args, **kwargs)
            response_cache.set(cache_key, result, ttl_seconds)
            return result

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
