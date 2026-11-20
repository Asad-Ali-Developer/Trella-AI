"""Tests verifying that increment_workspace_data_version is called exactly once after commit

Covered paths:
1. TrelloConnectionService.disconnect
2. GithubConnectionService.disconnect
3. TrelloConnectionService.save_board_selections (bump on excluded changes, no-op otherwise)
4. GithubConnectionService.save_repository_selections / save_repositories (bump on included/client_id changes, no-op otherwise)
5. TrelloConnectionService._clear_workspace_trello_data_if_unlinked (standalone bump vs disconnect no-double-bump)
6. Transaction commit order verification (commit must precede increment)
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.github.models import GithubRepository
from app.modules.github.schemas import (
    GithubRepositorySelection,
    GithubRepositorySelectionRequest,
)
from app.modules.github.service import GithubConnectionService
from app.modules.trello.models import (
    TrelloClientRecord,
    TrelloMember,
    TrelloSource,
)
from app.modules.trello.schemas import (
    TrelloBoardSelection,
    TrelloBoardSelectionRequest,
)
from app.modules.trello.service import TrelloConnectionService
from app.modules.workspaces.models import Workspace


async def _setup_user_and_workspace(
    async_client: AsyncClient,
    db_session: AsyncSession,
    prefix: str = "bump",
) -> tuple[User, Workspace]:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    signup = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Bump Tester", "password": "Password123!"},
    )
    assert signup.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    async_client.headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token") or ""

    ws_resp = await async_client.post("/api/v1/workspaces", json={"name": f"WS {prefix}"})
    assert ws_resp.status_code == 201
    ws_id = uuid.UUID(ws_resp.json()["id"])

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    ws = (await db_session.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
    return user, ws


class _DummyTrelloClient:
    def __init__(self, boards: list[dict[str, Any]]) -> None:
        self.boards = boards

    async def __aenter__(self) -> _DummyTrelloClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def list_boards(self) -> list[dict[str, Any]]:
        return self.boards


@pytest.mark.asyncio
async def test_trello_disconnect_bumps_counter_exactly_once(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="trello_disc")
    await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"enc-{ws.id}",
        external_account_id=f"ext-{ws.id}",
        external_username=f"user-{ws.id}",
    )
    await db_session.commit()

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.modules.trello.service.increment_workspace_data_version",
        bump_mock,
    )

    service = TrelloConnectionService(db_session, ws.id, user.id)
    status = await service.disconnect()
    assert not status.connected

    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_once_with(ws.id)


@pytest.mark.asyncio
async def test_github_disconnect_bumps_counter_exactly_once(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="gh_disc")
    await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws.id}",
        external_account_id=f"ext-gh-{ws.id}",
        external_username=f"gh-{ws.id}",
    )
    await db_session.commit()

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.modules.github.service.increment_workspace_data_version",
        bump_mock,
    )

    service = GithubConnectionService(db_session, ws.id, user.id)
    status = await service.disconnect()
    assert not status.connected

    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_once_with(ws.id)


@pytest.mark.asyncio
async def test_trello_save_board_selections_bumps_only_on_change(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="trello_sel")
    ws_id = ws.id
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws_id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"enc-{ws_id}",
        external_account_id=f"ext-{ws_id}",
        external_username=f"user-{ws_id}",
    )
    source = TrelloSource(
        workspace_id=ws_id,
        connection_id=conn.id,
        trello_board_id="board-alpha",
        name="Board Alpha",
        url="https://trello.com/b/alpha",
        excluded=True,
    )
    db_session.add(source)
    await db_session.commit()

    remote_boards = [
        {"id": "board-alpha", "name": "Board Alpha", "url": "https://trello.com/b/alpha"}
    ]
    service = TrelloConnectionService(db_session, ws_id, user.id)

    async def _fake_open_client(account: Any) -> _DummyTrelloClient:
        return _DummyTrelloClient(remote_boards)

    monkeypatch.setattr(service, "_open_client", _fake_open_client)

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.modules.trello.service.increment_workspace_data_version",
        bump_mock,
    )

    # 1. No change: board-alpha remains excluded=True
    req_no_change = TrelloBoardSelectionRequest(
        boards=[TrelloBoardSelection(id="board-alpha", excluded=True)]
    )
    await service.save_board_selections(req_no_change)
    assert bump_mock.await_count == 0

    # 2. Change: board-alpha toggled to excluded=False
    req_change = TrelloBoardSelectionRequest(
        boards=[TrelloBoardSelection(id="board-alpha", excluded=False)]
    )
    await service.save_board_selections(req_change)
    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_with(ws_id)

    # 3. Repeat identical request (excluded=False) -> no change -> no new bump
    await service.save_board_selections(req_change)
    assert bump_mock.await_count == 1


@pytest.mark.asyncio
async def test_github_save_repository_selections_bumps_on_included_or_client_change(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="gh_sel")
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws.id}",
        external_account_id=f"ext-gh-{ws.id}",
        external_username=f"gh-{ws.id}",
    )
    repo = GithubRepository(
        workspace_id=ws.id,
        connection_id=conn.id,
        github_repo_id="repo-100",
        full_name="org/repo-100",
        description=None,
        url="https://github.com/org/repo-100",
        default_branch="main",
        private=False,
        included=False,
        client_id=None,
    )
    client_rec = TrelloClientRecord(
        workspace_id=ws.id,
        name="Client Orion",
    )
    db_session.add_all([repo, client_rec])
    await db_session.commit()

    service = GithubConnectionService(db_session, ws.id, user.id)
    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.modules.github.service.increment_workspace_data_version",
        bump_mock,
    )

    # 1. No change: included=False, client_id=None
    no_change_req = GithubRepositorySelectionRequest(
        repositories=[
            GithubRepositorySelection(id="repo-100", included=False, client_id=None)
        ]
    )
    await service.save_repository_selections(no_change_req)
    assert bump_mock.await_count == 0

    # 2. Included changed: included=True, client_id=None
    include_req = GithubRepositorySelectionRequest(
        repositories=[
            GithubRepositorySelection(id="repo-100", included=True, client_id=None)
        ]
    )
    await service.save_repository_selections(include_req)
    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_with(ws.id)

    # 3. No change: repeat included=True, client_id=None
    await service.save_repository_selections(include_req)
    assert bump_mock.await_count == 1

    # 4. Client changed: included=True, client_id=client_rec.id
    client_req = GithubRepositorySelectionRequest(
        repositories=[
            GithubRepositorySelection(id="repo-100", included=True, client_id=client_rec.id)
        ]
    )
    await service.save_repository_selections(client_req)
    assert bump_mock.await_count == 2

    # 5. No change: repeat included=True, client_id=client_rec.id
    await service.save_repository_selections(client_req)
    assert bump_mock.await_count == 2


@pytest.mark.asyncio
async def test_clear_workspace_trello_data_if_unlinked_bumps_standalone_and_disconnect_does_not_double_bump(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="unlinked")
    await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"enc-{ws.id}",
        external_account_id=f"ext-{ws.id}",
        external_username=f"user-{ws.id}",
    )
    orphan_client = TrelloClientRecord(workspace_id=ws.id, name="Orphan Client")
    trello_member = TrelloMember(
        workspace_id=ws.id,
        trello_member_id="mem-1",
        username="mem1",
        full_name="Member One",
    )
    db_session.add_all([orphan_client, trello_member])
    await db_session.commit()

    service = TrelloConnectionService(db_session, ws.id, user.id)

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.modules.trello.service.increment_workspace_data_version",
        bump_mock,
    )

    # Call _clear_workspace_trello_data_if_unlinked directly -> bumps once
    await service._clear_workspace_trello_data_if_unlinked()
    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_once_with(ws.id)

    # Reset mock and call disconnect() -> must bump exactly once (not twice)
    bump_mock.reset_mock()
    await service.disconnect()
    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_once_with(ws.id)


@pytest.mark.asyncio
async def test_bump_happens_only_after_commit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="order")
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws.id}",
        external_account_id=f"ext-gh-{ws.id}",
        external_username=f"gh-{ws.id}",
    )
    repo = GithubRepository(
        workspace_id=ws.id,
        connection_id=conn.id,
        github_repo_id="repo-order",
        full_name="org/repo-order",
        description=None,
        url="https://github.com/org/repo-order",
        default_branch="main",
        private=False,
        included=False,
    )
    db_session.add(repo)
    await db_session.commit()

    call_sequence: list[str] = []

    orig_commit = db_session.commit

    async def _logged_commit() -> None:
        call_sequence.append("commit")
        await orig_commit()

    async def _logged_bump(workspace_id: uuid.UUID) -> int:
        call_sequence.append("bump")
        return 1

    monkeypatch.setattr(db_session, "commit", _logged_commit)
    monkeypatch.setattr(
        "app.modules.github.service.increment_workspace_data_version",
        _logged_bump,
    )

    service = GithubConnectionService(db_session, ws.id, user.id)
    await service.save_repository_selections(
        GithubRepositorySelectionRequest(
            repositories=[GithubRepositorySelection(id="repo-order", included=True)]
        )
    )

    # Must observe commit before bump
    assert call_sequence == ["commit", "bump"]

    # Also test disconnect sequence
    call_sequence.clear()
    await service.disconnect()
    assert call_sequence == ["commit", "bump"]
