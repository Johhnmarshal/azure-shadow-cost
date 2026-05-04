"""Tiny in-memory TTL cache.

Cost Management is throttled to ~5 requests / minute / subscription, and ARG
imposes its own quotas, so we cache aggressively. For a multi-instance App
Service (>1 worker) you'd want Redis instead — but for a PoC this is enough.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .config import settings


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_or_fetch(
        self,
        key: str,
        fetch: Callable[[], Awaitable[Any]],
        ttl_override: int | None = None,
    ) -> Any:
        ttl = ttl_override or settings().cache_ttl_seconds
        now = time.time()

        cached = self._store.get(key)
        if cached and (now - cached[0]) < ttl:
            return cached[1]

        # Per-key lock so we don't stampede the upstream API on cache miss.
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._store.get(key)
            if cached and (time.time() - cached[0]) < ttl:
                return cached[1]
            value = await fetch()
            self._store[key] = (time.time(), value)
            return value

    def invalidate(self, prefix: str = "") -> int:
        """Drop all keys starting with ``prefix``. Returns the number dropped."""
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)


cache = TTLCache()
