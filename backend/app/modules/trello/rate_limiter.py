import asyncio
import hashlib
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from app.core.config import settings

_INCREMENT_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('PTTL', KEYS[1])}
"""


class TrelloRateLimiter:
    """Enforces Trello's documented key, token, and member-route limits in Redis."""

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis or Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._owns_redis = redis is None

    async def close(self) -> None:
        if self._owns_redis:
            await self.redis.aclose()

    async def acquire(self, api_key: str, token: str, path: str) -> None:
        """Wait for available rate-limit capacity; Redis errors are surfaced to callers."""
        limits = [
            (f"trello:rate:key:{self._digest(api_key)}", 300, 10_000),
            (f"trello:rate:token:{self._digest(token)}", 100, 10_000),
        ]
        segments = path.strip("/").split("/")
        if segments[0] in {"membersSearch", "search"} or (
            segments[0] == "members" and len(segments) == 2
        ):
            limits.append((f"trello:rate:members:{self._digest(token)}", 100, 900_000))

        while True:
            waits: list[int] = []
            for key, threshold, window_ms in limits:
                response = self.redis.eval(_INCREMENT_WITH_TTL, 1, key, str(window_ms))
                result = await cast(Awaitable[list[int]], response)
                count, remaining_ms = int(result[0]), int(result[1])
                if count > threshold:
                    waits.append(max(remaining_ms, 1))
            if not waits:
                return
            await asyncio.sleep(max(waits) / 1000)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()


trello_rate_limiter = TrelloRateLimiter()
