"""Tests for POST /api/v1/search, result caching, query-embedding caching, rate limiting, and workspace isolation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.main import app
from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.context.indexer import increment_workspace_data_version
from app.modules.context.models import EMBEDDING_DIMENSIONS, ContextChunkRecord
from app.modules.search.cache import (
    get_cached_query_embedding,
    query_embed_cache_key,
    set_cached_query_embedding,
)
from app.modules.search.router import get_redis
from app.modules.trello.models import TrelloCard, TrelloSource
from app.modules.workspaces.models import Workspace


class FakeRedis:
    """In-memory Redis mock supporting basic string commands and Lua rate limiting."""

    def __init__(self, store: dict[str, Any] | None = None) -> None:
        self.store: dict[str, Any] = store if store is not None else {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def incr(self, key: str) -> int:
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return val

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> list[int]:
        key = str(keys_and_args[0])
        window_ms = int(keys_and_args[1]) if len(keys_and_args) > 1 else 60000
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return [val, window_ms]


async def _create_test_user(async_client: AsyncClient, prefix: str = "search") -> tuple[str, User]:
    email = f"{prefix}_{uuid4().hex[:8]}@example.com"
    response = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Search Tester", "password": "Password123!"},
    )
    assert response.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    async_client.headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token") or ""
    return email, response.json()


async def _setup_workspace_with_card(
    async_client: AsyncClient,
    db_session: AsyncSession,
    *,
    user_email: str,
    ws_name: str,
    card_name: str,
    card_text: str,
    board_excluded: bool = False,
    embedding: list[float] | None = None,
) -> tuple[Workspace, TrelloSource, TrelloCard, ContextChunkRecord]:
    user = (await db_session.execute(select(User).where(User.email == user_email))).scalar_one()

    ws_resp = await async_client.post("/api/v1/workspaces", json={"name": ws_name})
    assert ws_resp.status_code == 201
    workspace_id = UUID(ws_resp.json()["id"])
    workspace = (
        await db_session.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one()

    connection = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"encrypted-{workspace.id}",
        external_account_id=f"account-{workspace.id}",
        external_username=f"user-{workspace.id}",
    )
    conn_id = connection.id

    board_ext_id = f"board_{uuid4().hex[:8]}"
    source = TrelloSource(
        workspace_id=workspace.id,
        connection_id=conn_id,
        trello_board_id=board_ext_id,
        name=f"{ws_name} Board",
        url=f"https://trello.com/b/{board_ext_id}",
        excluded=board_excluded,
        sync_status="completed",
    )
    db_session.add(source)
    await db_session.flush()

    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        trello_card_id=f"card_{uuid4().hex[:8]}",
        name=card_name,
        description=f"Description of {card_name}",
        list_id="list-1",
        list_name="Active",
        labels=[],
        member_ids=[],
        closed=False,
        url=f"https://trello.com/c/{board_ext_id}",
        content_hash=hashlib.sha256(card_name.encode()).hexdigest(),
    )
    db_session.add(card)
    await db_session.flush()

    chunk_vec = embedding if embedding is not None else [0.05] * EMBEDDING_DIMENSIONS
    chunk = ContextChunkRecord(
        workspace_id=workspace.id,
        source_id=source.id,
        card_id=card.id,
        source_type="trello",
        chunk_kind="card_body",
        ordinal=0,
        text=card_text,
        token_estimate=len(card_text.split()),
        embedding=chunk_vec,
        embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        chunker_version=1,
        content_hash=hashlib.sha256(card_text.encode()).hexdigest(),
        occurred_at=datetime.now(),
    )
    db_session.add(chunk)
    await db_session.commit()

    return workspace, source, card, chunk


@pytest.mark.asyncio
async def test_search_cache_hit_skips_gemini_and_db(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache hit returns the same shape as a miss while skipping Gemini embedding and DB retrieval."""
    email, _ = await _create_test_user(async_client, prefix="cache_hit")
    ws, _, card, chunk = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="Cache Hit WS",
        card_name="Billing Invoice Export",
        card_text="Export customer billing invoices as PDF and CSV monthly.",
    )

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr("app.modules.trello.rate_limiter._get_loop_redis", lambda: fake_redis)

    gemini_calls: list[str] = []

    async def fake_embed(self: Any, text: str, **kwargs: Any) -> list[float]:
        gemini_calls.append(text)
        return [0.05] * EMBEDDING_DIMENSIONS

    from app.modules.context.gemini import GeminiContextClient

    monkeypatch.setattr(GeminiContextClient, "embed", fake_embed)

    from app.modules.context.retriever import HybridRetriever

    retriever_search_calls: list[str] = []
    orig_search = HybridRetriever.search

    async def spy_retriever_search(self: Any, *args: Any, **kwargs: Any) -> Any:
        retriever_search_calls.append(kwargs.get("query", ""))
        return await orig_search(self, *args, **kwargs)

    monkeypatch.setattr(HybridRetriever, "search", spy_retriever_search)

    headers = {"X-Workspace-Id": str(ws.id)}
    payload = {"query": "Billing Invoice", "limit": 10}

    # 1. Cold search (Cache Miss)
    resp1 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["cached"] is False
    assert len(data1["results"]) >= 1
    assert data1["results"][0]["chunk_id"] == str(chunk.id)
    assert data1["results"][0]["parent_type"] == "card"
    assert data1["results"][0]["parent_id"] == str(card.id)
    assert "signal_ranks" in data1["results"][0]
    assert "timings_ms" in data1
    assert data1["timings_ms"]["total"] > 0

    assert len(gemini_calls) == 1
    assert len(retriever_search_calls) == 1

    # 2. Warm search (Cache Hit)
    gemini_calls.clear()
    retriever_search_calls.clear()

    resp2 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["cached"] is True
    assert data2["results"] == data1["results"]
    assert data2["timings_ms"]["embed"] == 0.0
    assert data2["timings_ms"]["vector"] == 0.0
    assert data2["timings_ms"]["keyword"] == 0.0
    assert data2["timings_ms"]["fuse"] == 0.0
    assert data2["timings_ms"]["rerank"] == 0.0

    # Gemini and retrieval query must be skipped on cache hit
    assert gemini_calls == []
    assert retriever_search_calls == []
    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
async def test_search_data_version_bump_invalidates_result_cache(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incrementing the workspace data_version counter immediately invalidates the result cache."""
    email, _ = await _create_test_user(async_client, prefix="dv_bump")
    ws, _, card, chunk = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="DV Bump WS",
        card_name="Quarterly Roadmap",
        card_text="Roadmap Q1 objectives and deliverable milestones.",
    )

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr("app.modules.trello.rate_limiter._get_loop_redis", lambda: fake_redis)

    from app.modules.context.gemini import GeminiContextClient

    async def fake_embed(self: Any, text: str, **kwargs: Any) -> list[float]:
        return [0.05] * EMBEDDING_DIMENSIONS

    monkeypatch.setattr(GeminiContextClient, "embed", fake_embed)

    headers = {"X-Workspace-Id": str(ws.id)}
    payload = {"query": "Quarterly Roadmap", "limit": 5}

    # 1. First run -> cold
    resp1 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp1.status_code == 200
    assert resp1.json()["cached"] is False

    # 2. Second run -> warm
    resp2 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["cached"] is True

    # 3. Bump data_version in Redis
    new_version = await increment_workspace_data_version(ws.id, redis=fake_redis)  # type: ignore[arg-type]
    assert new_version is not None and new_version >= 1

    # 4. Third run -> must be a cache miss due to new data_version
    resp3 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp3.status_code == 200
    assert resp3.json()["cached"] is False

    # 5. Fourth run -> cached again at new data_version
    resp4 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp4.status_code == 200
    assert resp4.json()["cached"] is True

    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
async def test_search_cross_workspace_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same search query run in two distinct workspaces never shares or hits each other's cache entry."""
    email, _ = await _create_test_user(async_client, prefix="cross_ws")
    ws_a, _, _, chunk_a = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="Workspace Alpha",
        card_name="Security Compliance Alpha",
        card_text="Alpha workspace SOC2 compliance controls and audits.",
    )
    ws_b, _, _, chunk_b = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="Workspace Beta",
        card_name="Security Compliance Beta",
        card_text="Beta workspace GDPR and privacy regulation guidelines.",
    )

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr("app.modules.trello.rate_limiter._get_loop_redis", lambda: fake_redis)

    from app.modules.context.gemini import GeminiContextClient

    async def fake_embed(self: Any, text: str, **kwargs: Any) -> list[float]:
        return [0.05] * EMBEDDING_DIMENSIONS

    monkeypatch.setattr(GeminiContextClient, "embed", fake_embed)

    query = "Security Compliance"

    # Search in Workspace A
    resp_a = await async_client.post(
        "/api/v1/search",
        json={"query": query},
        headers={"X-Workspace-Id": str(ws_a.id)},
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["cached"] is False
    results_a = resp_a.json()["results"]
    assert len(results_a) == 1
    assert results_a[0]["chunk_id"] == str(chunk_a.id)

    # Search the same query in Workspace B -> must NOT hit A's cache and must NOT return A's chunks
    resp_b = await async_client.post(
        "/api/v1/search",
        json={"query": query},
        headers={"X-Workspace-Id": str(ws_b.id)},
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["cached"] is False
    results_b = resp_b.json()["results"]
    assert len(results_b) == 1
    assert results_b[0]["chunk_id"] == str(chunk_b.id)

    # Verify keys in Redis start with respective workspace IDs
    keys = list(fake_redis.store.keys())
    assert any(k.startswith(f"ws:{ws_a.id}:") for k in keys)
    assert any(k.startswith(f"ws:{ws_b.id}:") for k in keys)

    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
async def test_search_redis_down_search_still_works(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Redis is completely unreachable, rate limiting and caching fail soft and search returns 200."""
    email, _ = await _create_test_user(async_client, prefix="redis_down")
    ws, _, card, chunk = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="Redis Down WS",
        card_name="System Architecture",
        card_text="High availability distributed microservices architecture.",
    )

    class BrokenRedis:
        async def get(self, *args: Any, **kwargs: Any) -> Any:
            raise RedisError("Connection refused")

        async def set(self, *args: Any, **kwargs: Any) -> Any:
            raise RedisError("Connection refused")

        async def incr(self, *args: Any, **kwargs: Any) -> Any:
            raise RedisError("Connection refused")

        async def eval(self, *args: Any, **kwargs: Any) -> Any:
            raise RedisError("Connection refused")

    broken_redis = BrokenRedis()
    app.dependency_overrides[get_redis] = lambda: broken_redis
    monkeypatch.setattr("app.modules.trello.rate_limiter._get_loop_redis", lambda: broken_redis)

    from app.modules.context.gemini import GeminiContextClient

    async def fake_embed(self: Any, text: str, **kwargs: Any) -> list[float]:
        return [0.05] * EMBEDDING_DIMENSIONS

    monkeypatch.setattr(GeminiContextClient, "embed", fake_embed)

    resp = await async_client.post(
        "/api/v1/search",
        json={"query": "microservices architecture"},
        headers={"X-Workspace-Id": str(ws.id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False
    assert len(data["results"]) >= 1
    assert data["results"][0]["chunk_id"] == str(chunk.id)

    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
async def test_search_rate_limit_returns_429(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exceeding the search rate limit returns HTTP 429 with a Retry-After header."""
    email, _ = await _create_test_user(async_client, prefix="rate_limit")
    ws, _, _, _ = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="Rate Limit WS",
        card_name="Rate Limit Card",
        card_text="Testing user and workspace search rate limit enforcement.",
    )

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr("app.modules.trello.rate_limiter._get_loop_redis", lambda: fake_redis)

    from app.modules.context.gemini import GeminiContextClient

    async def fake_embed(self: Any, text: str, **kwargs: Any) -> list[float]:
        return [0.05] * EMBEDDING_DIMENSIONS

    monkeypatch.setattr(GeminiContextClient, "embed", fake_embed)

    # Set temporary tight rate limit of 2 requests per minute
    monkeypatch.setattr(settings, "SEARCH_RATE_LIMIT_USER", 2)
    monkeypatch.setattr(settings, "SEARCH_RATE_LIMIT_WORKSPACE", 5)

    headers = {"X-Workspace-Id": str(ws.id)}
    payload = {"query": "Rate Limit"}

    resp1 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp1.status_code == 200

    resp2 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp2.status_code == 200

    # 3rd request breaches user limit of 2
    resp3 = await async_client.post("/api/v1/search", json=payload, headers=headers)
    assert resp3.status_code == 429
    assert "Retry-After" in resp3.headers
    retry_after = int(resp3.headers["Retry-After"])
    assert retry_after >= 1

    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
async def test_search_excluded_sources_never_appear(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chunks residing in excluded sources/boards are filtered out server-side and never returned."""
    email, _ = await _create_test_user(async_client, prefix="excluded")
    # Included source card
    ws, src_included, _, chunk_included = await _setup_workspace_with_card(
        async_client,
        db_session,
        user_email=email,
        ws_name="Exclusion WS",
        card_name="Secret Protocol Active",
        card_text="Active confidential project details for production release.",
        board_excluded=False,
    )

    (await db_session.execute(select(User).where(User.email == email))).scalar_one()

    # Create an excluded source on the same workspace
    src_excluded = TrelloSource(
        workspace_id=ws.id,
        connection_id=src_included.connection_id,
        trello_board_id=f"board_ex_{uuid4().hex[:8]}",
        name="Archive Board Excluded",
        url="https://trello.com/b/archive",
        excluded=True,  # Excluded board
        sync_status="completed",
    )
    db_session.add(src_excluded)
    await db_session.flush()

    card_excluded = TrelloCard(
        workspace_id=ws.id,
        source_id=src_excluded.id,
        trello_card_id=f"card_ex_{uuid4().hex[:8]}",
        name="Secret Protocol Archived",
        description="Archived secret project information that must not be searchable.",
        list_id="list-archived",
        list_name="Archived",
        labels=[],
        member_ids=[],
        closed=False,
        url="https://trello.com/c/archive",
        content_hash=hashlib.sha256(b"archived").hexdigest(),
    )
    db_session.add(card_excluded)
    await db_session.flush()

    chunk_excluded = ContextChunkRecord(
        workspace_id=ws.id,
        source_id=src_excluded.id,
        card_id=card_excluded.id,
        source_type="trello",
        chunk_kind="card_body",
        ordinal=0,
        text="Archived confidential project details for production release.",
        token_estimate=10,
        embedding=[0.05] * EMBEDDING_DIMENSIONS,
        embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        chunker_version=1,
        content_hash=hashlib.sha256(b"archived_text").hexdigest(),
        occurred_at=datetime.now(),
    )
    db_session.add(chunk_excluded)
    await db_session.commit()

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr("app.modules.trello.rate_limiter._get_loop_redis", lambda: fake_redis)

    from app.modules.context.gemini import GeminiContextClient

    async def fake_embed(self: Any, text: str, **kwargs: Any) -> list[float]:
        return [0.05] * EMBEDDING_DIMENSIONS

    monkeypatch.setattr(GeminiContextClient, "embed", fake_embed)

    resp = await async_client.post(
        "/api/v1/search",
        json={"query": "confidential project details production release"},
        headers={"X-Workspace-Id": str(ws.id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["chunk_id"] for r in data["results"]]

    # Only included chunk appears; excluded chunk NEVER appears
    assert str(chunk_included.id) in result_ids
    assert str(chunk_excluded.id) not in result_ids

    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
async def test_query_embed_cache_compact_storage_and_normalization() -> None:
    """Query embedding cache normalizes query (strip, collapse whitespace, lowercase) and packs vector compactly."""
    fake_redis = FakeRedis()
    test_vec = [0.12345, -0.67891, 0.0, 1.0] * (EMBEDDING_DIMENSIONS // 4)

    # 1. Normalization check: queries differing only in whitespace and case must yield identical key
    q1 = "   Machine   Learning   Algorithms  \n\t "
    q2 = "machine learning algorithms"
    k1 = query_embed_cache_key(q1, "gemini-embedding-001", EMBEDDING_DIMENSIONS)
    k2 = query_embed_cache_key(q2, "gemini-embedding-001", EMBEDDING_DIMENSIONS)
    assert k1 == k2

    # 2. Set and get roundtrip
    saved = await set_cached_query_embedding(
        q1,
        "gemini-embedding-001",
        test_vec,
        dim=EMBEDDING_DIMENSIONS,
        redis=fake_redis,  # type: ignore[arg-type]
    )
    assert saved is True

    cached_val = await fake_redis.get(k1)
    assert isinstance(cached_val, str)
    # Stored compactly as base64 string, not large JSON array
    assert not cached_val.startswith("[")

    retrieved = await get_cached_query_embedding(
        q2,
        "gemini-embedding-001",
        dim=EMBEDDING_DIMENSIONS,
        redis=fake_redis,  # type: ignore[arg-type]
    )
    assert retrieved is not None
    assert len(retrieved) == EMBEDDING_DIMENSIONS
    assert pytest.approx(retrieved[:4], rel=1e-4) == [0.12345, -0.67891, 0.0, 1.0]
