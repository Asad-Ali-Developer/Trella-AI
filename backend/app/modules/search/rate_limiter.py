"""Redis-backed rate limiter for POST /api/v1/search (per user and per workspace)."""

from __future__ import annotations

import math
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
