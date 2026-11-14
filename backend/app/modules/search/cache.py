"""Query-embedding cache and search result cache backed by Redis."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.context.models import EMBEDDING_DIMENSIONS
from app.modules.search.schemas import SearchResultItem
from app.modules.trello.rate_limiter import _get_loop_redis

logger = get_logger("app.modules.search.cache")


def normalize_query(query: str) -> str:
    """Normalize query by stripping, collapsing whitespace, and lowercasing."""
    return " ".join(query.strip().split()).lower()


def query_embed_cache_key(
    query: str,
    embedding_model: str,
    dim: int = EMBEDDING_DIMENSIONS,
) -> str:
    """Return SHA256 key for query-embedding cache: sha256(normalized_query + embedding_model + dim)."""
    norm = normalize_query(query)
    raw = f"{norm}{embedding_model}{dim}".encode()
    return hashlib.sha256(raw).hexdigest()


def _get_redis_client(redis: Redis | None = None) -> Redis:
    if redis is not None:
        return redis
    return _get_loop_redis()


async def get_workspace_data_version(
    workspace_id: UUID,
    *,
    redis: Redis | None = None,
) -> int:
    """Read `ws:{workspace_id}:data_version` from Redis, defaulting to 0 if absent or on error."""
    key = f"ws:{workspace_id}:data_version"
    try:
        client = _get_redis_client(redis)
        val = await client.get(key)
        if val is None:
            return 0
        return int(val)
    except (RedisError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(
            "workspace_data_version_read_failed",
            workspace_id=str(workspace_id),
            error_type=type(exc).__name__,
        )
        return 0


def search_result_cache_key(
    *,
    workspace_id: UUID,
    data_version: int,
    query: str,
    client_id: UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
    active_source_ids: Sequence[UUID | str],
) -> str:
    """Return result cache key: ws:{workspace_id}:v{data_version}:sha256(query + filters + limit + active_source_ids)."""
    norm = normalize_query(query)
    c_id = str(client_id) if client_id else ""
    d_from = date_from.isoformat() if date_from else ""
    d_to = date_to.isoformat() if date_to else ""
    sorted_sources = ",".join(sorted(str(sid) for sid in active_source_ids))
    digest_payload = f"{norm}|{c_id}|{d_from}|{d_to}|{limit}|{sorted_sources}".encode()
    digest = hashlib.sha256(digest_payload).hexdigest()
    return f"ws:{workspace_id}:v{data_version}:{digest}"


async def get_cached_query_embedding(
    query: str,
    embedding_model: str,
    dim: int = EMBEDDING_DIMENSIONS,
    *,
    redis: Redis | None = None,
) -> list[float] | None:
    """Retrieve cached vector from Redis; fails soft without logging query text."""
    key = query_embed_cache_key(query, embedding_model, dim)
    try:
        client = _get_redis_client(redis)
        raw_val = await client.get(key)
        if raw_val is None:
            return None

        # Check for JSON array fallback
        if isinstance(raw_val, str) and raw_val.startswith("["):
            data = json.loads(raw_val)
            if isinstance(data, list):
                return [float(x) for x in data]
        elif isinstance(raw_val, bytes) and raw_val.startswith(b"["):
            data = json.loads(raw_val.decode("utf-8"))
            if isinstance(data, list):
                return [float(x) for x in data]

        # Decode compact base64-packed float32 struct
        bin_data = base64.b64decode(raw_val)
        floats = struct.unpack(f"{dim}f", bin_data)
        return [round(float(x), 5) for x in floats]
    except (RedisError, OSError, struct.error, ValueError, RuntimeError) as exc:
        logger.warning(
            "query_embed_cache_read_failed",
            embedding_model=embedding_model,
            dim=dim,
            error_type=type(exc).__name__,
        )
        return None


async def set_cached_query_embedding(
    query: str,
    embedding_model: str,
    vector: list[float],
    dim: int = EMBEDDING_DIMENSIONS,
    *,
    redis: Redis | None = None,
    ttl: int | None = None,
) -> bool:
    """Store vector compactly in Redis with 24h TTL; fails soft without logging query text."""
    key = query_embed_cache_key(query, embedding_model, dim)
    effective_ttl = ttl if ttl is not None else settings.QUERY_EMBED_CACHE_TTL
    try:
        client = _get_redis_client(redis)
        packed = struct.pack(f"{len(vector)}f", *vector)
        compact_val = base64.b64encode(packed).decode("ascii")
        await client.set(key, compact_val, ex=effective_ttl)
        return True
    except (RedisError, OSError, struct.error, RuntimeError) as exc:
        logger.warning(
            "query_embed_cache_write_failed",
            embedding_model=embedding_model,
            dim=dim,
            error_type=type(exc).__name__,
        )
        return False


async def get_cached_search_results(
    key: str,
    *,
    redis: Redis | None = None,
) -> list[SearchResultItem] | None:
    """Fetch cached search results from Redis; fails soft returning None."""
    try:
        client = _get_redis_client(redis)
        raw_val = await client.get(key)
        if raw_val is None:
            return None
        payload = json.loads(raw_val)
        if not isinstance(payload, list):
            return None
        return [SearchResultItem.model_validate(item) for item in payload]
    except (RedisError, OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        logger.warning(
            "search_result_cache_read_failed",
            error_type=type(exc).__name__,
        )
        return None


async def set_cached_search_results(
    key: str,
    results: list[SearchResultItem],
    *,
    redis: Redis | None = None,
    ttl: int | None = None,
) -> bool:
    """Store search results in Redis with TTL (default 10 min); fails soft."""
    effective_ttl = ttl if ttl is not None else settings.SEARCH_RESULT_CACHE_TTL
    try:
        client = _get_redis_client(redis)
        serialized = json.dumps([item.model_dump(mode="json") for item in results])
        await client.set(key, serialized, ex=effective_ttl)
        return True
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning(
            "search_result_cache_write_failed",
            error_type=type(exc).__name__,
        )
        return False
