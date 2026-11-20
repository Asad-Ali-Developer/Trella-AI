"""Tests for data_version bumping on chunk client_id remapping paths and fail-soft behavior.

Paths covered:
1. Trello save_client_mappings:
   - Bumps data_version after commit when chunks.client_id actually changes
   - Does not bump on no-op remap (chunks.client_id does not change)
   - Avoids double bumps when bump=False (caller already bumps)
2. IndexingService.remap_repository_client:
   - Bumps data_version after commit when chunks.client_id actually changes
   - Does not bump on no-op remap (chunks.client_id does not change or 0 chunks)
   - Avoids double bumps when bump=False (caller already bumps)
3. increment_workspace_data_version fail-soft:
   - Catches Redis errors and never raises after commit
   - Logs a warning without content
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.context.indexer import (
    IndexingService,
    increment_workspace_data_version,
)
from app.modules.context.models import EMBEDDING_DIMENSIONS, ContextChunkRecord
from app.modules.github.models import GithubRepository
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientRecord,
    TrelloSource,
)
from app.modules.trello.router import save_client_mappings
from app.modules.trello.schemas import (
    TrelloClientMappingInput,
    TrelloClientMappingRequest,
)
from app.modules.trello.sync import replace_client_mappings
from app.modules.workspaces.models import Membership, Workspace


async def _setup_workspace_and_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    prefix: str = "remap",
) -> tuple[User, Workspace, Membership]:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    signup = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Remap Tester", "password": "Password123!"},
    )
    assert signup.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    async_client.headers["X-CSRF-Token"] = async_client.cookies.get("csrf_token") or ""

    ws_resp = await async_client.post("/api/v1/workspaces", json={"name": f"WS {prefix}"})
    assert ws_resp.status_code == 201
    ws_id = uuid.UUID(ws_resp.json()["id"])

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    ws = (await db_session.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
    membership = (
        await db_session.execute(
            select(Membership).where(
                Membership.workspace_id == ws_id,
                Membership.user_id == user.id,
            )
        )
    ).scalar_one()
    return user, ws, membership


def _create_test_chunk(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID | None = None,
    card_id: uuid.UUID | None = None,
    repository_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    source_type: str = "trello",
) -> ContextChunkRecord:
    text = f"Sample chunk for {source_type} {uuid.uuid4()}"
    return ContextChunkRecord(
        workspace_id=workspace_id,
        source_id=source_id if source_type == "trello" else None,
        card_id=card_id if source_type == "trello" else None,
        repository_id=repository_id,
        client_id=client_id,
        source_type=source_type,
        chunk_kind="card_body" if source_type == "trello" else "commit_group",
        group_key=f"group-{uuid.uuid4().hex[:8]}" if source_type == "github" else None,
        ordinal=0,
        text=text,
        token_estimate=len(text.split()),
        embedding=[0.05] * EMBEDDING_DIMENSIONS,
        embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        chunker_version=1,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        occurred_at=datetime.now(UTC),
    )


# -----------------------------------------------------------------------------
# 1. Trello Remap Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trello_remap_bumps_once_after_commit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, membership = await _setup_workspace_and_user(async_client, db_session, prefix="t_bump")
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
        trello_board_id="board-remap-1",
        name="Board Remap 1",
        url="https://trello.com/b/remap1",
        excluded=False,
    )
    db_session.add(source)
    await db_session.flush()

    card = TrelloCard(
        workspace_id=ws_id,
        source_id=source.id,
        trello_card_id="c-remap-1",
        name="Card 1",
        description="Desc",
        list_id="l1",
        list_name="Todo",
        labels=[],
        member_ids=[],
        closed=False,
        content_hash=hashlib.sha256(b"card").hexdigest(),
        client_id=None,
    )
    db_session.add(card)
    await db_session.flush()

    chunk = _create_test_chunk(
        workspace_id=ws_id,
        source_id=source.id,
        card_id=card.id,
        client_id=None,
    )
    db_session.add(chunk)
    await db_session.commit()

    call_sequence: list[str] = []
    orig_commit = db_session.commit

    async def _logged_commit() -> None:
        call_sequence.append("commit")
        await orig_commit()

    bump_mock = AsyncMock(side_effect=lambda w: call_sequence.append("bump") or 1)
    monkeypatch.setattr(db_session, "commit", _logged_commit)
    monkeypatch.setattr("app.modules.trello.router.increment_workspace_data_version", bump_mock)
    monkeypatch.setattr("app.modules.trello.sync.increment_workspace_data_version", bump_mock)

    req = TrelloClientMappingRequest(
        mappings=[
            TrelloClientMappingInput(
                board_id="board-remap-1",
                mapping_type="board",
                external_ref="board-remap-1",
                client_name="Client Alpha",
            )
        ]
    )

    resp = await save_client_mappings(
        payload=req,
        workspace_context=(ws, membership),
        db=db_session,
    )
    assert resp.saved == 1

    # Chunk client_id must be updated
    await db_session.refresh(chunk)
    assert chunk.client_id is not None

    # Bump occurred exactly once, strictly after commit
    assert call_sequence == ["commit", "bump"]
    assert bump_mock.await_count == 1
    bump_mock.assert_awaited_once_with(ws_id)


@pytest.mark.asyncio
async def test_trello_remap_noop_does_not_bump(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, membership = await _setup_workspace_and_user(async_client, db_session, prefix="t_noop")
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
        trello_board_id="board-noop",
        name="Board Noop",
        url="https://trello.com/b/noop",
        excluded=False,
    )
    client_rec = TrelloClientRecord(workspace_id=ws_id, name="Client Existing")
    db_session.add_all([source, client_rec])
    await db_session.flush()

    card = TrelloCard(
        workspace_id=ws_id,
        source_id=source.id,
        trello_card_id="c-noop-1",
        name="Card Noop",
        description="Desc",
        list_id="l1",
        list_name="Todo",
        labels=[],
        member_ids=[],
        closed=False,
        content_hash=hashlib.sha256(b"card").hexdigest(),
        client_id=client_rec.id,
    )
    db_session.add(card)
    await db_session.flush()

    # Chunk already has client_rec.id
    chunk = _create_test_chunk(
        workspace_id=ws_id,
        source_id=source.id,
        card_id=card.id,
        client_id=client_rec.id,
    )
    db_session.add(chunk)
    await db_session.commit()

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr("app.modules.trello.router.increment_workspace_data_version", bump_mock)
    monkeypatch.setattr("app.modules.trello.sync.increment_workspace_data_version", bump_mock)

    req = TrelloClientMappingRequest(
        mappings=[
            TrelloClientMappingInput(
                board_id="board-noop",
                mapping_type="board",
                external_ref="board-noop",
                client_name="Client Existing",
            )
        ]
    )

    # chunks.client_id does NOT change -> no bump
    resp = await save_client_mappings(
        payload=req,
        workspace_context=(ws, membership),
        db=db_session,
    )
    assert resp.saved == 1
    assert bump_mock.await_count == 0


@pytest.mark.asyncio
async def test_trello_remap_avoid_double_bump_when_caller_already_bumps(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, membership = await _setup_workspace_and_user(async_client, db_session, prefix="t_caller")
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
        trello_board_id="board-caller",
        name="Board Caller",
        url="https://trello.com/b/caller",
        excluded=False,
    )
    db_session.add(source)
    await db_session.flush()

    card = TrelloCard(
        workspace_id=ws_id,
        source_id=source.id,
        trello_card_id="c-caller-1",
        name="Card Caller",
        description="Desc",
        list_id="l1",
        list_name="Todo",
        labels=[],
        member_ids=[],
        closed=False,
        content_hash=hashlib.sha256(b"card").hexdigest(),
        client_id=None,
    )
    db_session.add(card)
    await db_session.flush()

    chunk = _create_test_chunk(
        workspace_id=ws_id,
        source_id=source.id,
        card_id=card.id,
        client_id=None,
    )
    db_session.add(chunk)
    await db_session.commit()

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr("app.modules.trello.router.increment_workspace_data_version", bump_mock)
    monkeypatch.setattr("app.modules.trello.sync.increment_workspace_data_version", bump_mock)

    req = TrelloClientMappingRequest(
        mappings=[
            TrelloClientMappingInput(
                board_id="board-caller",
                mapping_type="board",
                external_ref="board-caller",
                client_name="Client Gamma",
            )
        ]
    )

    # Calling with bump=False suppresses the bump (e.g. caller manages bump)
    resp = await save_client_mappings(
        payload=req,
        workspace_context=(ws, membership),
        db=db_session,
        bump=False,
    )
    assert resp.saved == 1
    assert bump_mock.await_count == 0

    # Direct call to replace_client_mappings with bump=False also suppresses bump
    bump_mock.reset_mock()
    await replace_client_mappings(
        db=db_session,
        workspace_id=ws_id,
        connection_id=conn.id,
        mappings=[
            {
                "board_id": "board-caller",
                "mapping_type": "board",
                "external_ref": "board-caller",
                "client_name": "Client Delta",
            }
        ],
        bump=False,
    )
    assert bump_mock.await_count == 0


# -----------------------------------------------------------------------------
# 2. GitHub Remap Tests (IndexingService.remap_repository_client)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_remap_bumps_once_after_commit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, _ = await _setup_workspace_and_user(async_client, db_session, prefix="gh_bump")
    ws_id = ws.id
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws_id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws_id}",
        external_account_id=f"ext-gh-{ws_id}",
        external_username=f"gh-{ws_id}",
    )
    repo = GithubRepository(
        workspace_id=ws_id,
        connection_id=conn.id,
        github_repo_id="gh-repo-remap",
        full_name="org/repo-remap",
        description=None,
        url="https://github.com/org/repo-remap",
        default_branch="main",
        private=False,
        included=True,
        client_id=None,
    )
    client_rec = TrelloClientRecord(workspace_id=ws_id, name="Client Repo Beta")
    db_session.add_all([repo, client_rec])
    await db_session.flush()

    chunk = _create_test_chunk(
        workspace_id=ws_id,
        repository_id=repo.id,
        client_id=None,
        source_type="github",
    )
    db_session.add(chunk)
    await db_session.commit()

    call_sequence: list[str] = []
    orig_commit = db_session.commit

    async def _logged_commit() -> None:
        call_sequence.append("commit")
        await orig_commit()

    bump_mock = AsyncMock(side_effect=lambda w, **kw: call_sequence.append("bump") or 1)
    monkeypatch.setattr(db_session, "commit", _logged_commit)
    monkeypatch.setattr("app.modules.context.indexer.increment_workspace_data_version", bump_mock)

    indexer = IndexingService(db_session)
    updated = await indexer.remap_repository_client(
        workspace_id=ws_id,
        repository_id=repo.id,
        new_client_id=client_rec.id,
    )
    assert updated == 1

    await db_session.refresh(chunk)
    assert chunk.client_id == client_rec.id

    # Commit must precede bump
    assert call_sequence == ["commit", "bump"]
    assert bump_mock.await_count == 1
    assert bump_mock.call_args[0][0] == ws_id


@pytest.mark.asyncio
async def test_github_remap_noop_does_not_bump(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, _ = await _setup_workspace_and_user(async_client, db_session, prefix="gh_noop")
    ws_id = ws.id
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws_id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws_id}",
        external_account_id=f"ext-gh-{ws_id}",
        external_username=f"gh-{ws_id}",
    )
    client_rec = TrelloClientRecord(workspace_id=ws_id, name="Client Existing Repo")
    repo = GithubRepository(
        workspace_id=ws_id,
        connection_id=conn.id,
        github_repo_id="gh-repo-noop",
        full_name="org/repo-noop",
        description=None,
        url="https://github.com/org/repo-noop",
        default_branch="main",
        private=False,
        included=True,
        client_id=None,
    )
    db_session.add_all([client_rec, repo])
    await db_session.flush()

    # Case A: Repo with 0 chunks -> remap returns 0, no bump
    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr("app.modules.context.indexer.increment_workspace_data_version", bump_mock)

    indexer = IndexingService(db_session)
    updated_empty = await indexer.remap_repository_client(
        workspace_id=ws_id,
        repository_id=repo.id,
        new_client_id=client_rec.id,
    )
    assert updated_empty == 0
    assert bump_mock.await_count == 0

    # Case B: Repo has chunk with client_rec.id, remapping to client_rec.id again -> 0 updated, no bump
    chunk = _create_test_chunk(
        workspace_id=ws_id,
        repository_id=repo.id,
        client_id=client_rec.id,
        source_type="github",
    )
    db_session.add(chunk)
    await db_session.commit()

    updated_same = await indexer.remap_repository_client(
        workspace_id=ws_id,
        repository_id=repo.id,
        new_client_id=client_rec.id,
    )
    assert updated_same == 0
    assert bump_mock.await_count == 0


@pytest.mark.asyncio
async def test_github_remap_avoid_double_bump_when_caller_already_bumps(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, _ = await _setup_workspace_and_user(async_client, db_session, prefix="gh_caller")
    ws_id = ws.id
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws_id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws_id}",
        external_account_id=f"ext-gh-{ws_id}",
        external_username=f"gh-{ws_id}",
    )
    repo = GithubRepository(
        workspace_id=ws_id,
        connection_id=conn.id,
        github_repo_id="gh-repo-suppress",
        full_name="org/repo-suppress",
        description=None,
        url="https://github.com/org/repo-suppress",
        default_branch="main",
        private=False,
        included=True,
        client_id=None,
    )
    client_rec = TrelloClientRecord(workspace_id=ws_id, name="Client Suppress")
    db_session.add_all([repo, client_rec])
    await db_session.flush()

    chunk = _create_test_chunk(
        workspace_id=ws_id,
        repository_id=repo.id,
        client_id=None,
        source_type="github",
    )
    db_session.add(chunk)
    await db_session.commit()

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr("app.modules.context.indexer.increment_workspace_data_version", bump_mock)

    indexer = IndexingService(db_session)
    updated = await indexer.remap_repository_client(
        workspace_id=ws_id,
        repository_id=repo.id,
        new_client_id=client_rec.id,
        bump=False,
    )
    assert updated == 1
    assert bump_mock.await_count == 0


# -----------------------------------------------------------------------------
# 3. Fail-Soft Redis Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_workspace_data_version_fails_soft_on_redis_error() -> None:
    ws_id = uuid.uuid4()

    fake_failing_redis = AsyncMock()
    fake_failing_redis.incr.side_effect = RedisError("Connection refused by peer")

    # Must return None and NEVER raise
    res = await increment_workspace_data_version(ws_id, redis=fake_failing_redis)
    assert res is None


@pytest.mark.asyncio
async def test_redis_failure_during_remap_bump_does_not_raise(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws, membership = await _setup_workspace_and_user(async_client, db_session, prefix="failsoft")
    ws_id = ws.id

    # 1. Setup GitHub repo with chunk
    gh_conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws_id,
        provider="github",
        user_id=user.id,
        encrypted_token=f"enc-gh-{ws_id}",
        external_account_id=f"ext-gh-{ws_id}",
        external_username=f"gh-{ws_id}",
    )
    repo = GithubRepository(
        workspace_id=ws_id,
        connection_id=gh_conn.id,
        github_repo_id="gh-repo-failsoft",
        full_name="org/repo-failsoft",
        description=None,
        url="https://github.com/org/repo-failsoft",
        default_branch="main",
        private=False,
        included=True,
        client_id=None,
    )
    client_rec = TrelloClientRecord(workspace_id=ws_id, name="Client Failsoft")
    db_session.add_all([repo, client_rec])
    await db_session.flush()

    chunk = _create_test_chunk(
        workspace_id=ws_id,
        repository_id=repo.id,
        client_id=None,
        source_type="github",
    )
    db_session.add(chunk)
    await db_session.commit()

    # Monkeypatch loop redis to simulate catastrophic Redis connection drop
    failing_redis = AsyncMock()
    failing_redis.incr.side_effect = RedisError("Redis cluster unreachable")
    monkeypatch.setattr("app.modules.context.indexer._get_loop_redis", lambda: failing_redis)

    indexer = IndexingService(db_session)
    # Must NOT raise, and chunks.client_id must still be updated in DB
    updated = await indexer.remap_repository_client(
        workspace_id=ws_id,
        repository_id=repo.id,
        new_client_id=client_rec.id,
    )
    assert updated == 1
    await db_session.refresh(chunk)
    assert chunk.client_id == client_rec.id

    # 2. Setup Trello with chunk and test save_client_mappings during Redis failure
    t_conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws_id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"enc-t-{ws_id}",
        external_account_id=f"ext-t-{ws_id}",
        external_username=f"t-{ws_id}",
    )
    source = TrelloSource(
        workspace_id=ws_id,
        connection_id=t_conn.id,
        trello_board_id="board-failsoft",
        name="Board Failsoft",
        url="https://trello.com/b/failsoft",
        excluded=False,
    )
    db_session.add(source)
    await db_session.flush()

    card = TrelloCard(
        workspace_id=ws_id,
        source_id=source.id,
        trello_card_id="c-failsoft-1",
        name="Card Failsoft",
        description="Desc",
        list_id="l1",
        list_name="Todo",
        labels=[],
        member_ids=[],
        closed=False,
        content_hash=hashlib.sha256(b"card").hexdigest(),
        client_id=None,
    )
    db_session.add(card)
    await db_session.flush()

    t_chunk = _create_test_chunk(
        workspace_id=ws_id,
        source_id=source.id,
        card_id=card.id,
        client_id=None,
    )
    db_session.add(t_chunk)
    await db_session.commit()

    req = TrelloClientMappingRequest(
        mappings=[
            TrelloClientMappingInput(
                board_id="board-failsoft",
                mapping_type="board",
                external_ref="board-failsoft",
                client_name="Client Failsoft",
            )
        ]
    )

    # Must NOT raise when Redis fails, and chunk.client_id must be committed
    resp = await save_client_mappings(
        payload=req,
        workspace_context=(ws, membership),
        db=db_session,
    )
    assert resp.saved == 1
    await db_session.refresh(t_chunk)
    assert t_chunk.client_id is not None
