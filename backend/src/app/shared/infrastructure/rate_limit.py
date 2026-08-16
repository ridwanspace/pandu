"""Redis-backed rate limiting (fixed window: INCR + EXPIRE) and its FastAPI
dependency. Every model-calling surface is rate limited (ADR / ai.md rule).

Fixed window over sliding window: one round trip, no ZSET growth, and the
worst-case burst (2x limit across a boundary) is acceptable for an API-key
gate. Redis keys hash the client key so raw API keys never land in Redis.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RedisRateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock

    async def check(self, key: str) -> RateLimitDecision:
        now = self._clock()
        window = int(now // self._window_seconds)
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        redis_key = f"ratelimit:{digest}:{window}"

        pipe = self._redis.pipeline(transaction=True)
        pipe.incr(redis_key)
        # Expire a little after the window closes so clock skew cannot drop a
        # live counter; NX keeps the TTL from being pushed forward on each hit.
        pipe.expire(redis_key, self._window_seconds + 1, nx=True)
        results = await pipe.execute()
        count = int(results[0])

        retry_after = self._window_seconds - int(now % self._window_seconds)
        return RateLimitDecision(
            allowed=count <= self._limit,
            remaining=max(self._limit - count, 0),
            retry_after_seconds=max(retry_after, 1),
        )


def build_rate_limit_dependency(
    limiter: RedisRateLimiter,
) -> Callable[[Request], Awaitable[None]]:
    """Return a FastAPI dependency enforcing the limit per API key (falling
    back to client address for unauthenticated setups). Raises 429 with a
    Retry-After header when exhausted."""

    async def enforce_rate_limit(request: Request) -> None:
        client_host = request.client.host if request.client else "anonymous"
        key = request.headers.get("X-API-Key") or client_host
        decision = await limiter.check(key)
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

    return enforce_rate_limit
