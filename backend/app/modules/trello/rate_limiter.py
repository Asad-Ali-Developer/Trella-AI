import asyncio
import hashlib
import weakref
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.modules.trello.rate_limiter")

_INCREMENT_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('PTTL', KEYS[1])}
"""

_LOOP_POOLS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[str, ConnectionPool]] = (
    weakref.WeakKeyDictionary()
)
_LOOP_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Redis] = (
    weakref.WeakKeyDictionary()
)
_REGISTERED_LOOPS: weakref.WeakSet[asyncio.AbstractEventLoop] = weakref.WeakSet()


def _register_loop_cleanup(loop: asyncio.AbstractEventLoop) -> None:
    if loop in _REGISTERED_LOOPS:
        return
    _REGISTERED_LOOPS.add(loop)
    orig_shutdown_asyncgens = loop.shutdown_asyncgens
    orig_close = loop.close

    async def _shutdown_asyncgens() -> None:
        client = _LOOP_CLIENTS.pop(loop, None)
        pool_entry = _LOOP_POOLS.pop(loop, None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        if pool_entry is not None:
            _, pool = pool_entry
            try:
                await pool.aclose()
            except Exception:
                try:
                    await pool.disconnect()
                except Exception:
                    pass
        await orig_shutdown_asyncgens()

    def _close() -> None:
        _LOOP_CLIENTS.pop(loop, None)
        _LOOP_POOLS.pop(loop, None)
        _REGISTERED_LOOPS.discard(loop)
        orig_close()

    loop.shutdown_asyncgens = _shutdown_asyncgens  # type: ignore[method-assign]
    loop.close = _close  # type: ignore[method-assign]


def _get_loop_pool() -> ConnectionPool:
    loop = asyncio.get_running_loop()
    _register_loop_cleanup(loop)
    url = settings.REDIS_URL
    cached = _LOOP_POOLS.get(loop)
    if cached is not None and cached[0] == url:
        return cached[1]
    pool = ConnectionPool.from_url(url, decode_responses=True)
    _LOOP_POOLS[loop] = (url, pool)
    _LOOP_CLIENTS.pop(loop, None)
    return pool


def _get_loop_redis() -> Redis:
    loop = asyncio.get_running_loop()
    pool = _get_loop_pool()
    client = _LOOP_CLIENTS.get(loop)
    if client is not None and client.connection_pool is pool:
        return client
    client = Redis(connection_pool=pool)
    _LOOP_CLIENTS[loop] = client
    return client


class RedisRateLimiter:
    """Enforces Trello's documented key, token, and member-route limits in Redis."""

    def __init__(
        self,
        redis: Redis | None = None,
        connection_pool: ConnectionPool | None = None,
    ) -> None:
        self._custom_redis = redis
        self._custom_pool = connection_pool

    def _get_redis(self) -> Redis:
        if self._custom_redis is not None:
            return self._custom_redis
        if self._custom_pool is not None:
            return Redis(connection_pool=self._custom_pool)
        return _get_loop_redis()

    @property
    def connection_pool(self) -> ConnectionPool:
        if self._custom_pool is not None:
            return self._custom_pool
        if self._custom_redis is not None and self._custom_redis.connection_pool is not None:
            return self._custom_redis.connection_pool
        return _get_loop_pool()

    @property
    def redis(self) -> Redis:
        return self._get_redis()

    async def close(self) -> None:
        if self._custom_redis is not None:
            await self._custom_redis.aclose()
            return
        if self._custom_pool is not None:
            await self._custom_pool.aclose()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        client = _LOOP_CLIENTS.pop(loop, None)
        pool_entry = _LOOP_POOLS.pop(loop, None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        if pool_entry is not None:
            _, pool = pool_entry
            try:
                await pool.aclose()
            except Exception:
                await pool.disconnect()

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
                redis_client = self.redis
                for key, threshold, window_ms in limits:
                    response = redis_client.eval(_INCREMENT_WITH_TTL, 1, key, str(window_ms))
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


TrelloRateLimiter = RedisRateLimiter
trello_rate_limiter = TrelloRateLimiter()
