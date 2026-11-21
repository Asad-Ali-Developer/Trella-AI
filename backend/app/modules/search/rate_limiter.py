"""Redis-backed rate limiter for POST /api/v1/search and POST /api/v1/ask."""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.trello.rate_limiter import _INCREMENT_WITH_TTL, _get_loop_redis

logger = get_logger("app.modules.search.rate_limiter")

WINDOW_MS = 60_000  # 1 minute window


class InProcessRateLimiter:
    """In-memory sliding-window fallback limiter when Redis is unavailable.

    Maintains per-key monotonic timestamps within a sliding window.
    Fail-closed strategy: Protects against unmetered LLM token consumption
    even when Redis is down or disconnected.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = {}

    def check_and_record(self, key: str, threshold: int) -> int | None:
        """Check if request exceeds limit.

        Returns None if allowed (and records the timestamp),
        or wait_seconds if rate limit is exceeded.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds
        timestamps = self._history.get(key, [])
        valid = [t for t in timestamps if t > cutoff]
        if len(valid) >= threshold:
            self._history[key] = valid
            earliest = valid[0]
            wait_sec = max(1, math.ceil(earliest + self.window_seconds - now))
            return wait_sec
        valid.append(now)
        self._history[key] = valid
        return None

    def reset(self) -> None:
        """Reset in-memory history (useful in tests)."""
        self._history.clear()


_in_process_ask_limiter = InProcessRateLimiter(window_seconds=60.0)


async def check_search_rate_limits(
    user_id: UUID,
    workspace_id: UUID,
    *,
    redis: Redis | None = None,
) -> None:
    """Enforce per-user and per-workspace rate limits on /search using Redis.

    Raises HTTP 429 with Retry-After header on limit breach. Fails soft if Redis is down.
    """
    client = redis if redis is not None else _get_loop_redis()
    limits = [
        (f"rate:search:user:{user_id}", settings.SEARCH_RATE_LIMIT_USER),
        (f"rate:search:ws:{workspace_id}", settings.SEARCH_RATE_LIMIT_WORKSPACE),
    ]

    max_retry_after = 0
    exceeded = False

    try:
        for key, threshold in limits:
            resp = client.eval(_INCREMENT_WITH_TTL, 1, key, str(WINDOW_MS))
            result = await cast(Awaitable[list[int]], resp)
            count, pttl = int(result[0]), int(result[1])
            if count > threshold:
                exceeded = True
                wait_sec = max(1, math.ceil(max(pttl, 1) / 1000.0))
                if wait_sec > max_retry_after:
                    max_retry_after = wait_sec
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning(
            "search_rate_limiter_unavailable",
            user_id=str(user_id),
            workspace_id=str(workspace_id),
            error_type=type(exc).__name__,
        )
        return

    if exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for search.",
            headers={"Retry-After": str(max_retry_after)},
        )


async def check_ask_rate_limits(
    user_id: UUID,
    workspace_id: UUID,
    *,
    redis: Redis | None = None,
) -> None:
    """Enforce per-user and per-workspace rate limits on /ask.

    Limits are separate and stricter than /search:
    - ASK_RATE_LIMIT_USER: max requests per minute per user.
    - ASK_RATE_LIMIT_WORKSPACE: max requests per minute per workspace.

    Fail-closed policy:
    LLM generation incurs significant latency and upstream token costs.
    If Redis is unavailable, an in-process sliding-window fallback limiter
    strictly enforces the same thresholds locally rather than failing open.

    Raises HTTP 429 with Retry-After header on limit breach.
    """
    limits = [
        (f"rate:ask:user:{user_id}", settings.ASK_RATE_LIMIT_USER),
        (f"rate:ask:ws:{workspace_id}", settings.ASK_RATE_LIMIT_WORKSPACE),
    ]

    max_retry_after = 0
    exceeded = False
    use_fallback = False

    try:
        client = redis if redis is not None else _get_loop_redis()
        for key, threshold in limits:
            resp = client.eval(_INCREMENT_WITH_TTL, 1, key, str(WINDOW_MS))
            result = await cast(Awaitable[list[int]], resp)
            count, pttl = int(result[0]), int(result[1])
            if count > threshold:
                exceeded = True
                wait_sec = max(1, math.ceil(max(pttl, 1) / 1000.0))
                if wait_sec > max_retry_after:
                    max_retry_after = wait_sec
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning(
            "ask_redis_rate_limiter_unavailable_using_fallback",
            user_id=str(user_id),
            workspace_id=str(workspace_id),
            error_type=type(exc).__name__,
        )
        use_fallback = True

    if use_fallback:
        for key, threshold in limits:
            fallback_wait = _in_process_ask_limiter.check_and_record(key, threshold)
            if fallback_wait is not None:
                exceeded = True
                if fallback_wait > max_retry_after:
                    max_retry_after = fallback_wait

    if exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for ask.",
            headers={"Retry-After": str(max_retry_after)},
        )

