import hashlib
import uuid

import pytest
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
