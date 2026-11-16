"""Fixed-window rate limiting (used for login and registration).

Redis is the production backend so limits hold across API processes. The in-memory backend
exists for single-process development and unit tests.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Protocol

from redis.asyncio import Redis


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record one attempt. Returns ``False`` once the limit is exceeded."""
        ...


class MemoryRateLimiter:
    """Sliding-window limiter (no burst at window boundaries). Single process only."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        q.append(now)
        return len(q) <= limit


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = int(time.time() // window_seconds)
        rkey = f"akshara:rl:{key}:{window}"
        pipe = self._redis.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, window_seconds + 1)
        count, _ = await pipe.execute()
        return int(count) <= limit
