import hashlib
import uuid

import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.context.models import TrelloCardEmbedding
from app.modules.trello.models import TrelloCard, TrelloMember, TrelloSource
from app.modules.workspaces.models import Workspace


async def _create_user(async_client: AsyncClient) -> str:
    email = f"context_{uuid.uuid4().hex[:8]}@example.com"
    response = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Context Tester", "password": "Password123!"},
    )
    assert response.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    async_client.headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token", "")
    return email


async def _create_context_card(
    db_session: AsyncSession,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    *,
    name: str,
    board_id: str,
    excluded: bool = False,
) -> TrelloCard:
    source = TrelloSource(
        workspace_id=workspace_id,
        connection_id=connection_id,
        trello_board_id=board_id,
        name=f"{name} board",
        url=f"https://trello.com/b/{board_id}",
        excluded=excluded,
        sync_status="completed",
    )
    db_session.add(source)
    await db_session.flush()
    card = TrelloCard(
        workspace_id=workspace_id,
        source_id=source.id,
        trello_card_id=f"{board_id}-card",
        name=name,
        description=f"Description for {name}",
        list_id="list-1",
        list_name="In progress",
        labels=[],
        member_ids=[],
        closed=False,
        url=f"https://trello.com/c/{board_id}",
        content_hash=hashlib.sha256(name.encode()).hexdigest(),
    )
    db_session.add(card)
    await db_session.flush()
    return card


async def _create_connection(
    db_session: AsyncSession,
    user: User,
    workspace: Workspace,
) -> uuid.UUID:
    connection = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"encrypted-{workspace.id}",
        external_account_id=f"account-{workspace.id}",
        external_username=f"user-{workspace.id}",
    )
    return connection.id


@pytest.mark.asyncio
async def test_context_uses_only_included_sources_and_accounts_from_selected_workspace(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = await _create_user(async_client)
    first_workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "First context workspace"},
    )
    second_workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Second context workspace"},
    )
    first_workspace_id = uuid.UUID(first_workspace_response.json()["id"])
    second_workspace_id = uuid.UUID(second_workspace_response.json()["id"])
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    connections = ConnectionRepository(db_session)

    first_link = await connections.upsert_provider_connection(
        workspace_id=first_workspace_id,
        provider="trello",
        user_id=user.id,
        encrypted_token="encrypted-first-token",
        external_account_id="first-account",
        external_username="first-user",
    )
    first_account = await connections.get_provider_account(first_link)
    assert first_account is not None
    included_source = TrelloSource(
        workspace_id=first_workspace_id,
        connection_id=first_link.id,
        trello_board_id="included-board",
        name="Included board",
        url="https://trello.com/b/included",
        excluded=False,
        sync_status="completed",
    )
    excluded_source = TrelloSource(
        workspace_id=first_workspace_id,
        connection_id=first_link.id,
        trello_board_id="excluded-board",
        name="Excluded board",
        url="https://trello.com/b/excluded",
        excluded=True,
        sync_status="completed",
    )
    db_session.add_all([included_source, excluded_source])
    await db_session.flush()
    included_card = TrelloCard(
        workspace_id=first_workspace_id,
        source_id=included_source.id,
        trello_card_id="included-card",
        name="Included card",
        description="Workspace-specific project context. " * 40,
        list_id="list-1",
        list_name="In progress",
        labels=[],
        member_ids=[],
        closed=False,
        url="https://trello.com/c/included",
        content_hash="a" * 64,
    )
    excluded_card = TrelloCard(
        workspace_id=first_workspace_id,
        source_id=excluded_source.id,
        trello_card_id="excluded-card",
        name="Excluded card",
        description="Must not enter the context.",
        list_id="list-2",
        list_name="Done",
        labels=[],
        member_ids=[],
        closed=False,
        url="https://trello.com/c/excluded",
        content_hash="b" * 64,
    )
    db_session.add_all([included_card, excluded_card])

    second_link = await connections.upsert_provider_connection(
        workspace_id=second_workspace_id,
        provider="trello",
        user_id=user.id,
        encrypted_token="encrypted-second-token",
        external_account_id="second-account",
        external_username="second-user",
    )
    second_source = TrelloSource(
        workspace_id=second_workspace_id,
        connection_id=second_link.id,
        trello_board_id="second-board",
        name="Other workspace board",
        url="https://trello.com/b/other",
        excluded=False,
        sync_status="completed",
    )
    db_session.add(second_source)
    await db_session.flush()
    db_session.add(
        TrelloCard(
            workspace_id=second_workspace_id,
            source_id=second_source.id,
            trello_card_id="other-card",
            name="Other workspace card",
            description="Must not cross workspace boundaries.",
            list_id="list-other",
            list_name="Other list",
            labels=[],
            member_ids=[],
            closed=False,
            url="https://trello.com/c/other",
            content_hash="c" * 64,
        )
    )
    await db_session.commit()

    async_client.headers["X-Workspace-Id"] = str(first_workspace_id)
    response = await async_client.get("/api/v1/context?max_tokens=256")

    assert response.status_code == 200
    context = response.json()
    assert context["workspace_id"] == str(first_workspace_id)
    assert context["connected_accounts"] == [
        {
            "id": str(first_account.id),
            "provider": "trello",
            "account_name": "first-user",
        }
    ]
    assert [source["name"] for source in context["sources"]] == ["Included board"]
    context_items = [item for chunk in context["chunks"] for item in chunk["items"]]
    context_text = " ".join(f"{item['title'] or ''} {item['text']}" for item in context_items)
    assert "Included card" in context_text
    assert "Excluded card" not in context_text
    assert "Other workspace card" not in context_text
    assert all(chunk["estimated_tokens"] <= 256 for chunk in context["chunks"])
    assert len(context["chunks"]) > 1


@pytest.mark.asyncio
async def test_context_is_available_with_exactly_one_connected_account(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = await _create_user(async_client)
    workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Single account workspace"},
    )
    workspace_id = uuid.UUID(workspace_response.json()["id"])
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace_id,
        provider="trello",
        user_id=user.id,
        encrypted_token="encrypted-single-token",
        external_account_id="single-account",
        external_username="one-connected-account",
    )
    await db_session.commit()

    async_client.headers["X-Workspace-Id"] = str(workspace_id)
    response = await async_client.get("/api/v1/context")

    assert response.status_code == 200
    accounts = response.json()["connected_accounts"]
    assert len(accounts) == 1
    assert accounts[0]["provider"] == "trello"
    assert accounts[0]["account_name"] == "one-connected-account"
    assert response.json()["sources"] == []
    assert response.json()["chunks"] == []


@pytest.mark.asyncio
async def test_context_validates_token_budget_and_client_scope(
    async_client: AsyncClient,
) -> None:
    await _create_user(async_client)
    workspace = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Context validation workspace"},
    )
    workspace_id = workspace.json()["id"]
    async_client.headers["X-Workspace-Id"] = workspace_id

    too_small = await async_client.get("/api/v1/context?max_tokens=10")
    unknown_client = await async_client.get(
        f"/api/v1/context?client_id={uuid.uuid4()}",
    )

    assert too_small.status_code == 422
    assert unknown_client.status_code == 404


@pytest.mark.asyncio
async def test_member_classification_is_workspace_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _create_user(async_client)
    first_workspace = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Member classification workspace"},
    )
    second_workspace = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Other member workspace"},
    )
    first_workspace_id = uuid.UUID(first_workspace.json()["id"])
    second_workspace_id = uuid.UUID(second_workspace.json()["id"])
    member = TrelloMember(
        workspace_id=first_workspace_id,
        trello_member_id="member-123",
        username="client-user",
        full_name="Client User",
    )
    db_session.add(member)
    await db_session.commit()

    async_client.headers["X-Workspace-Id"] = str(second_workspace_id)
    wrong_workspace = await async_client.patch(
        f"/api/v1/context/members/{member.id}",
        json={"role_tag": "client"},
    )
    assert wrong_workspace.status_code == 404

    async_client.headers["X-Workspace-Id"] = str(first_workspace_id)
    classified = await async_client.patch(
        f"/api/v1/context/members/{member.id}",
        json={"role_tag": "client"},
    )

    assert classified.status_code == 200
    assert classified.json()["role_tag"] == "client"
    await db_session.refresh(member)
    assert member.role_tag == "client"


@pytest.mark.asyncio
async def test_card_summaries_are_cached_by_content_hash(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = await _create_user(async_client)
    workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Summary cache workspace"},
    )
    workspace_id = uuid.UUID(workspace_response.json()["id"])
    workspace = (
        await db_session.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one()
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    connection_id = await _create_connection(db_session, user, workspace)
    card = await _create_context_card(
        db_session,
        workspace_id,
        connection_id,
        name="Original card",
        board_id="summary-board",
    )
    await db_session.commit()
    async_client.headers["X-Workspace-Id"] = str(workspace_id)

    generated_texts: list[str] = []

    class StubGemini:
        instances = 0

        def __init__(self) -> None:
            StubGemini.instances += 1

        async def __aenter__(self) -> "StubGemini":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def summarize(self, source_text: str) -> tuple[str, int, int]:
            generated_texts.append(source_text)
            return "A faithful summary.", 12, 5

    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", StubGemini)

    first = await async_client.post("/api/v1/context/summaries", json={"max_cards": 10})

    class UnexpectedGemini:
        def __init__(self) -> None:
            raise AssertionError("cached summaries should not create a Gemini client")

    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", UnexpectedGemini)
    second = await async_client.post("/api/v1/context/summaries", json={"max_cards": 10})
    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", StubGemini)
    card.name = "Updated card"
    card.content_hash = hashlib.sha256(card.name.encode()).hexdigest()
    await db_session.commit()
    updated = await async_client.post("/api/v1/context/summaries", json={"max_cards": 10})

    assert first.status_code == second.status_code == updated.status_code == 200
    assert first.json()["generated"] == 1
    assert second.json()["cached"] == 1
    assert updated.json()["generated"] == 1
    assert len(generated_texts) == 2
    assert StubGemini.instances == 2


@pytest.mark.asyncio
async def test_semantic_search_is_limited_to_included_workspace_cards(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = await _create_user(async_client)
    first_workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Search workspace"},
    )
    second_workspace_response = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Other search workspace"},
    )
    first_workspace_id = uuid.UUID(first_workspace_response.json()["id"])
    second_workspace_id = uuid.UUID(second_workspace_response.json()["id"])
    first_workspace = (
        await db_session.execute(select(Workspace).where(Workspace.id == first_workspace_id))
    ).scalar_one()
    second_workspace = (
        await db_session.execute(select(Workspace).where(Workspace.id == second_workspace_id))
    ).scalar_one()
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    first_connection_id = await _create_connection(db_session, user, first_workspace)
    second_connection_id = await _create_connection(db_session, user, second_workspace)
    included_card = await _create_context_card(
        db_session,
        first_workspace_id,
        first_connection_id,
        name="Included workspace card",
        board_id="search-included",
    )
    excluded_card = await _create_context_card(
        db_session,
        first_workspace_id,
        first_connection_id,
        name="Excluded board card",
        board_id="search-excluded",
        excluded=True,
    )
    await _create_context_card(
        db_session,
        second_workspace_id,
        second_connection_id,
        name="Other workspace card",
        board_id="search-other",
    )
    db_session.add(
        TrelloCardEmbedding(
            workspace_id=first_workspace_id,
            card_id=excluded_card.id,
            content_hash=excluded_card.content_hash,
            model="gemini-embedding-001",
            embedding=[1.0] + [0.0] * 767,
        )
    )
    await db_session.commit()

    class UnexpectedGemini:
        def __init__(self) -> None:
            raise AssertionError("search without a valid index should not create a Gemini client")

    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", UnexpectedGemini)
    async_client.headers["X-Workspace-Id"] = str(first_workspace_id)
    not_indexed = await async_client.post(
        "/api/v1/context/search",
        json={"query": "find similar work"},
    )
    assert not_indexed.status_code == 409

    class StubGemini:
        async def __aenter__(self) -> "StubGemini":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def embed(self, text: str, *, query: bool = False) -> list[float]:
            return [1.0] + [0.0] * 767

    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", StubGemini)

    async_client.headers["X-Workspace-Id"] = str(first_workspace_id)
    first_index = await async_client.post("/api/v1/context/index", json={"max_cards": 10})
    async_client.headers["X-Workspace-Id"] = str(second_workspace_id)
    second_index = await async_client.post("/api/v1/context/index", json={"max_cards": 10})
    async_client.headers["X-Workspace-Id"] = str(first_workspace_id)
    search = await async_client.post(
        "/api/v1/context/search",
        json={"query": "find similar work"},
    )

    assert first_index.status_code == second_index.status_code == search.status_code == 200
    assert first_index.json()["indexed"] == second_index.json()["indexed"] == 1
    assert [item["card_id"] for item in search.json()["results"]] == [str(included_card.id)]


@pytest.mark.asyncio
@respx.mock
async def test_gemini_client_retries_429_honoring_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import (
        GEMINI_API_BASE,
        EmbeddingRateLimited,
        GeminiContextClient,
    )

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(settings, "GEMINI_MAX_ATTEMPTS", 3)

    recorded_sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        recorded_sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:embedContent"
    route = respx.post(url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1.75"}, json={"error": "rate limited"}),
            httpx.Response(200, json={"embedding": {"values": [0.25] + [0.0] * 767}}),
        ]
    )

    async with GeminiContextClient() as client:
        vector = await client.embed("retry after test")

    assert route.call_count == 2
    assert vector[0] == pytest.approx(0.25)
    assert recorded_sleeps == [pytest.approx(1.75)]

    route_exhausted = respx.post(url).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0.25"}, json={"error": "busy"})
    )
    async with GeminiContextClient() as client:
        with pytest.raises(EmbeddingRateLimited):
            await client.embed("exhaust retries")
    assert route_exhausted.call_count == 2 + 3


@pytest.mark.asyncio
@respx.mock
async def test_gemini_client_retries_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import (
        GEMINI_API_BASE,
        EmbeddingUnavailable,
        GeminiContextClient,
    )

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(settings, "GEMINI_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "GEMINI_RETRY_INITIAL_WAIT", 0.001)
    monkeypatch.setattr(settings, "GEMINI_RETRY_MAX_WAIT", 0.005)
    monkeypatch.setattr(settings, "GEMINI_RETRY_JITTER", 0.001)

    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:embedContent"
    route = respx.post(url).mock(
        side_effect=[
            httpx.Response(503, json={"error": "unavailable"}),
            httpx.Response(500, json={"error": "internal"}),
            httpx.Response(200, json={"embedding": {"values": [0.5] + [0.0] * 767}}),
        ]
    )

    async with GeminiContextClient() as client:
        vector = await client.embed("server error recovery")

    assert route.call_count == 3
    assert vector[0] == pytest.approx(0.5)

    respx.post(url).mock(return_value=httpx.Response(502, json={"error": "bad gateway"}))
    async with GeminiContextClient() as client:
        with pytest.raises(EmbeddingUnavailable):
            await client.embed("persistent 502")


@pytest.mark.asyncio
@respx.mock
async def test_gemini_embed_batch_preserves_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import GEMINI_API_BASE, GeminiContextClient

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:batchEmbedContents"

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests_list = payload["requests"]
        embeddings = []
        for idx, req in enumerate(requests_list):
            assert req["model"] == f"models/{settings.GEMINI_EMBEDDING_MODEL}"
            assert req["outputDimensionality"] == 768
            assert req["taskType"] == "RETRIEVAL_DOCUMENT"
            embeddings.append({"values": [float(idx + 1)] + [0.0] * 767})
        return httpx.Response(200, json={"embeddings": embeddings})

    route = respx.post(url).mock(side_effect=_handler)

    texts = ["alpha", "beta", "gamma", "delta"]
    async with GeminiContextClient() as client:
        vectors = await client.embed_batch(texts)

    assert route.call_count == 1
    sent_texts = [
        item["content"]["parts"][0]["text"]
        for item in json.loads(route.calls.last.request.content)["requests"]
    ]
    assert sent_texts == texts
    assert [vec[0] for vec in vectors] == [1.0, 2.0, 3.0, 4.0]


@pytest.mark.asyncio
@respx.mock
async def test_gemini_embed_batch_splits_into_api_sized_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import (
        GEMINI_API_BASE,
        MAX_EMBED_BATCH_SIZE,
        GeminiContextClient,
    )

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:batchEmbedContents"
    batch_sizes: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests_list = payload["requests"]
        batch_sizes.append(len(requests_list))
        embeddings = []
        for req in requests_list:
            text_val = req["content"]["parts"][0]["text"]
            idx = int(text_val.split("-")[1])
            embeddings.append({"values": [float(idx)] + [0.0] * 767})
        return httpx.Response(200, json={"embeddings": embeddings})

    route = respx.post(url).mock(side_effect=_handler)

    total_items = 250
    texts = [f"item-{i}" for i in range(total_items)]
    async with GeminiContextClient() as client:
        vectors = await client.embed_batch(texts)

    assert MAX_EMBED_BATCH_SIZE == 100
    assert route.call_count == 3
    assert batch_sizes == [100, 100, 50]
    assert len(vectors) == total_items
    assert [int(vec[0]) for vec in vectors] == list(range(total_items))


@pytest.mark.asyncio
@respx.mock
async def test_gemini_semaphore_limits_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import GEMINI_API_BASE, GeminiContextClient

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(settings, "GEMINI_MAX_CONCURRENCY", 2)

    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:embedContent"
    in_flight = 0
    max_in_flight = 0

    async def _slow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.03)
        in_flight -= 1
        return httpx.Response(200, json={"embedding": {"values": [1.0] + [0.0] * 767}})

    respx.post(url).mock(side_effect=_slow_handler)

    async with GeminiContextClient() as client:
        results = await asyncio.gather(*(client.embed(f"doc-{i}") for i in range(6)))

    assert len(results) == 6
    assert max_in_flight == 2


@pytest.mark.asyncio
@respx.mock
async def test_gemini_client_reuse_within_one_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import GEMINI_API_BASE, GeminiContextClient

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:embedContent"
    respx.post(url).mock(
        return_value=httpx.Response(200, json={"embedding": {"values": [1.0] + [0.0] * 767}})
    )

    async with GeminiContextClient() as first_client:
        http_client_1 = first_client.client
        await first_client.embed("first call")

    assert not http_client_1.is_closed

    async with GeminiContextClient() as second_client:
        http_client_2 = second_client.client
        await second_client.embed("second call")

    assert http_client_1 is http_client_2
    assert not http_client_2.is_closed


def test_gemini_client_consecutive_asyncio_run_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import httpx

    from app.core.config import settings
    from app.modules.context.gemini import GEMINI_API_BASE, GeminiContextClient

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    url = f"{GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:embedContent"

    seen_clients: list[httpx.AsyncClient] = []

    async def _run_once(text: str) -> list[float]:
        with respx.mock:
            respx.post(url).mock(
                return_value=httpx.Response(
                    200, json={"embedding": {"values": [0.75] + [0.0] * 767}}
                )
            )
            async with GeminiContextClient() as client:
                seen_clients.append(client.client)
                return await client.embed(text)

    vec1 = asyncio.run(_run_once("loop one"))
    assert seen_clients[0].is_closed

    vec2 = asyncio.run(_run_once("loop two"))
    assert seen_clients[1].is_closed
    assert seen_clients[0] is not seen_clients[1]
    assert vec1[0] == vec2[0] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_context_service_translates_gemini_typed_errors_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import HTTPException

    from app.modules.context.gemini import EmbeddingRateLimited, EmbeddingUnavailable
    from app.modules.context.service import WorkspaceContextService

    workspace = Workspace(id=uuid.uuid4(), name="Error translation workspace", slug="err-ws")
    card = TrelloCard(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        source_id=uuid.uuid4(),
        trello_card_id="err-card-1",
        name="Error card",
        description="Desc",
        list_id="list-1",
        list_name="Todo",
        labels=[],
        member_ids=[],
        closed=False,
        url="https://trello.com/c/err",
        content_hash="a" * 64,
    )

    mock_db = MagicMock(spec=AsyncSession)
    mock_db.scalar = AsyncMock(return_value=None)
    empty_exec = MagicMock()
    empty_exec.__iter__.return_value = iter([])
    mock_db.execute = AsyncMock(return_value=empty_exec)

    service = WorkspaceContextService(mock_db, workspace)
    monkeypatch.setattr(service, "_load_included_cards", AsyncMock(return_value=[card]))
    monkeypatch.setattr(service, "_load_comments", AsyncMock(return_value=[]))

    class RateLimitedGemini:
        async def __aenter__(self) -> "RateLimitedGemini":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def summarize(self, source_text: str) -> tuple[str, int, int]:
            raise EmbeddingRateLimited("Gemini request failed with status 429.")

        async def embed(self, text: str, *, query: bool = False) -> list[float]:
            raise EmbeddingUnavailable("Could not reach the configured Gemini service.")

    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", RateLimitedGemini)

    with pytest.raises(HTTPException) as summary_exc:
        await service.summarize_cards(client_id=None, max_cards=5)
    assert summary_exc.value.status_code == 503
    assert "429" in str(summary_exc.value.detail)

    with pytest.raises(HTTPException) as index_exc:
        await service.index_cards(client_id=None, max_cards=5)
    assert index_exc.value.status_code == 503
    assert "Could not reach" in str(index_exc.value.detail)
