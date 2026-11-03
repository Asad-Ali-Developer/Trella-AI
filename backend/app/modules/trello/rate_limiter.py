import asyncio
import hashlib
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.modules.trello.rate_limiter")

_INCREMENT_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('PTTL', KEYS[1])}
"""


class TrelloRateLimiter:
    """Enforces Trello's documented key, token, and member-route limits in Redis."""

    def __init__(self, redis: Redis | None = None) -> None:
        self._custom_redis = redis
        self._owns_redis = redis is None
        self._clients: dict[int, tuple[asyncio.AbstractEventLoop, Redis]] = {}

    def _get_redis(self) -> Redis:
        if self._custom_redis is not None:
            return self._custom_redis
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        loop_id = id(loop) if loop is not None else 0
        existing = self._clients.get(loop_id)
        if existing is not None:
            loop_ref, client = existing
            if not loop_ref.is_closed():
                return client

        self._clients = {
            lid: (l_ref, c)
            for lid, (l_ref, c) in self._clients.items()
            if not l_ref.is_closed()
        }

        client = cast(Redis, Redis.from_url(settings.REDIS_URL, decode_responses=True))
        if loop is not None:
            self._clients[loop_id] = (loop, client)
        return client

    @property
    def redis(self) -> Redis:
        return self._get_redis()

    async def close(self) -> None:
        if self._custom_redis is not None:
            await self._custom_redis.aclose()
            return
        for _, (loop_ref, client) in list(self._clients.items()):
            if not loop_ref.is_closed():
                try:
                    await client.aclose()
                except Exception:
                    pass
        self._clients.clear()

    async def acquire(self, api_key: str, token: str, path: str) -> None:
        """Wait for available rate-limit capacity; falls back to pass-through if Redis is unreachable."""
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
            try:
                for key, threshold, window_ms in limits:
                    response = self.redis.eval(_INCREMENT_WITH_TTL, 1, key, str(window_ms))
                    result = await cast(Awaitable[list[int]], response)
                    count, remaining_ms = int(result[0]), int(result[1])
                    if count > threshold:
                        waits.append(max(remaining_ms, 1))
            except (RedisError, OSError) as exc:
                logger.warning("trello_rate_limiter_redis_unavailable", error=str(exc))
                return
            if not waits:
                return
            await asyncio.sleep(max(waits) / 1000)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()


trello_rate_limiter = TrelloRateLimiter()
