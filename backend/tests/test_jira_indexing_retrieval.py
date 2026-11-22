"""Tests for Jira Cloud chunking, per-kind chunker versioning, bulk indexing, CHECK constraints, client remapping, and hybrid retrieval (/search, /ask, /context/search)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import event, func, pool, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alembic import command
from app.main import app
from app.modules.auth.models import User
from app.modules.connections.models import WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.context.chunker import (
    CHUNKER_VERSION,
    CHUNKER_VERSION_BY_KIND,
    IssueBodyInput,
    IssueCommentInput,
    IssueTransitionInput,
    chunk_issue_body,
    chunk_issue_comments,
    chunk_issue_transitions,
    chunker_version_for_kind,
    compute_content_hash,
)
from app.modules.context.indexer import IndexingService
from app.modules.context.models import ContextChunkRecord
from app.modules.context.retriever import HybridRetriever, resolve_active_sources
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.jira.models import (
    JiraChangelogItem,
    JiraComment,
    JiraIssue,
    JiraProject,
)
from app.modules.search.router import get_redis
from app.modules.trello.models import TrelloCard, TrelloClientRecord, TrelloSource
from app.modules.workspaces.models import Workspace


def _unit_vec(index: int, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[index % dim] = 1.0
    return vec


class FakeRedis:
    """In-memory Redis stub for search result cache and data_version testing."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        del ex
        if nx and key in self.store:
            return False
        self.store[key] = str(value) if not isinstance(value, (str, bytes)) else value
        return True

    async def setex(self, key: str, ttl: int, value: Any) -> bool:
        del ttl
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        val = int(self.store.get(key, "0")) + 1
        self.store[key] = str(val)
        return val

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        if "del" in script and numkeys == 1:
            k = str(keys_and_args[0])
            expected = str(keys_and_args[1])
            if self.store.get(k) == expected:
                self.store.pop(k, None)
                return 1
            return 0
        return [1, 0]


class CountingEmbedder:
    """Deterministic embedder stub that records all embedded texts."""

    def __init__(self, vec_index: int = 1) -> None:
        self.vec_index = vec_index
        self.embedded_texts: list[str] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.embedded_texts.extend(texts)
        return [_unit_vec(self.vec_index) for _ in texts]

    def embed(self, text: str, *, query: bool = False) -> list[float]:
        del text, query
        return _unit_vec(self.vec_index)


async def _setup_workspace(
    async_client: AsyncClient,
    db_session: AsyncSession,
    *,
    name: str,
) -> tuple[User, Workspace]:
    email = f"jira-idx-{uuid4().hex[:10]}@example.com"
    reg = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Jira Index Tester", "password": "Password123!"},
    )
    assert reg.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    csrf_token = async_client.cookies.get("csrf_token")
    if csrf_token is not None:
        async_client.headers["X-CSRF-Token"] = csrf_token

    ws_resp = await async_client.post("/api/v1/workspaces", json={"name": name})
    assert ws_resp.status_code == 201
    ws_id = UUID(ws_resp.json()["id"])
    async_client.headers["X-Workspace-Id"] = str(ws_id)

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    ws = (await db_session.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
    return user, ws


async def _create_jira_project_with_issue(
    db_session: AsyncSession,
    *,
    user: User,
    workspace: Workspace,
    client_id: UUID | None = None,
    included: bool = True,
    project_key: str = "ACME",
    issue_key: str = "ACME-123",
    summary: str = "Fix SAML assertion validation",
    description: str = "Ensure ClockSkew tolerance is applied to SAML assertions.",
) -> tuple[WorkspaceConnection, JiraProject, JiraIssue]:
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="jira",
        user_id=user.id,
        encrypted_token="enc-jira-token",
        external_account_id=f"jira-acct-{uuid4().hex[:8]}",
        external_username="alice@acme.com",
    )
    project = JiraProject(
        workspace_id=workspace.id,
        connection_id=conn.id,
        cloud_id="acme.atlassian.net",
        jira_project_id=f"proj-{uuid4().hex[:6]}",
        key=project_key,
        name=f"{project_key} Platform",
        included=included,
        client_id=client_id,
        sync_status="completed",
    )
    db_session.add(project)
    await db_session.flush()

    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    issue = JiraIssue(
        workspace_id=workspace.id,
        project_id=project.id,
        cloud_id=project.cloud_id,
        jira_issue_id=f"issue-{uuid4().hex[:6]}",
        key=issue_key,
        summary=summary,
        description=description,
        status="In Progress",
        issue_type="Bug",
        priority="High",
        assignee="Alice Eng",
        reporter="Bob PM",
        labels=["saml", "auth"],
        created_at_jira=now - timedelta(days=1),
        updated_at_jira=now,
        content_hash=compute_content_hash(f"{issue_key}:{summary}:{description}"),
        url=f"https://acme.atlassian.net/browse/{issue_key}",
    )
    db_session.add(issue)
    await db_session.flush()
    return conn, project, issue


def test_pure_jira_chunkers_and_per_kind_version_map() -> None:
    assert CHUNKER_VERSION == 1
    assert chunker_version_for_kind("card_body") == 1
    assert chunker_version_for_kind("comment_group") == 1
    assert chunker_version_for_kind("commit_group") == 1
    assert chunker_version_for_kind("issue_body") == 2
    assert chunker_version_for_kind("issue_comment_group") == 2
    assert chunker_version_for_kind("issue_transition_group") == 2
    assert set(CHUNKER_VERSION_BY_KIND.keys()) == {
        "card_body",
        "comment_group",
        "commit_group",
        "issue_body",
        "issue_comment_group",
        "issue_transition_group",
    }

    # 1. issue_body format and no truncation on oversized paragraphs
    long_desc = " ".join(f"ParagraphToken{i}" for i in range(900))
    body_chunks = chunk_issue_body(
        IssueBodyInput(
            client_name="Acme Corp",
            project_name="Identity Core",
            issue_key="ACME-101",
            summary="SAML SSO login failure",
            description=long_desc,
            status="In Progress",
            issue_type="Bug",
            priority="Highest",
            assignee="Alice Chen",
            reporter="Bob Smith",
            labels=("sso", "urgent"),
            occurred_at=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
        )
    )
    assert len(body_chunks) >= 2
    for ch in body_chunks:
        assert ch.kind == "issue_body"
        assert ch.text.startswith("Client: Acme Corp | Project: Identity Core | Issue ACME-101: SAML SSO login failure")
    assert "Status: In Progress" in body_chunks[0].text
    assert "Type: Bug" in body_chunks[0].text
    assert "Priority: Highest" in body_chunks[0].text
    assert "Assignee: Alice Chen" in body_chunks[0].text
    assert "Labels: sso, urgent" in body_chunks[0].text
    # Every token from long_desc is preserved without truncation
    combined_body_text = "\n".join(c.text for c in body_chunks)
    assert "ParagraphToken0" in combined_body_text
    assert "ParagraphToken899" in combined_body_text

    # 2. issue_comment_group deterministic ~400 token grouping with author + timestamp
    t0 = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
    comments = [
        IssueCommentInput(
            comment_id=f"c-{i}",
            author_name=f"User{i}",
            created_at=t0 + timedelta(minutes=i * 10),
            body=f"Detailed investigation note #{i}: " + ("diagnostic trace data " * 30),
        )
        for i in range(6)
    ]
    c_chunks_1 = chunk_issue_comments(
        comments,
        client_name="Acme Corp",
        project_name="Identity Core",
        issue_key="ACME-101",
        issue_summary="SAML SSO login failure",
    )
    c_chunks_2 = chunk_issue_comments(
        list(reversed(comments)),
        client_name="Acme Corp",
        project_name="Identity Core",
        issue_key="ACME-101",
        issue_summary="SAML SSO login failure",
    )
    assert len(c_chunks_1) >= 2
    assert [c.content_hash for c in c_chunks_1] == [c.content_hash for c in c_chunks_2]
    assert "[2026-03-10T09:00:00+00:00] User0:" in c_chunks_1[0].text or "User0" in c_chunks_1[0].text

    # 3. issue_transition_group filters status changes with author and date
    transitions = [
        IssueTransitionInput(
            history_id="h-1",
            item_index=0,
            author_name="Alice Chen",
            created_at=t0,
            field="status",
            from_value="To Do",
            to_value="In Progress",
        ),
        IssueTransitionInput(
            history_id="h-2",
            item_index=0,
            author_name="Alice Chen",
            created_at=t0 + timedelta(hours=1),
            field="priority",
            from_value="Medium",
            to_value="Highest",
        ),
        IssueTransitionInput(
            history_id="h-3",
            item_index=0,
            author_name="Bob Smith",
            created_at=t0 + timedelta(hours=2),
            field="Status",
            from_value="In Progress",
            to_value="Done",
        ),
    ]
    t_chunks = chunk_issue_transitions(
        transitions,
        client_name="Acme Corp",
        project_name="Identity Core",
        issue_key="ACME-101",
        issue_summary="SAML SSO login failure",
    )
    assert len(t_chunks) == 1
    assert t_chunks[0].kind == "issue_transition_group"
    assert "Status changed from 'To Do' to 'In Progress'" in t_chunks[0].text
    assert "Status changed from 'In Progress' to 'Done'" in t_chunks[0].text
    assert "Highest" not in t_chunks[0].text


@pytest.mark.asyncio
async def test_chunks_check_constraints_reject_zero_or_two_parents_and_jira_without_project_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, ws = await _setup_workspace(async_client, db_session, name="Check Constraints WS")
    _, project, issue = await _create_jira_project_with_issue(
        db_session,
        user=user,
        workspace=ws,
    )
    trello_conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="trello",
        user_id=user.id,
        encrypted_token="enc-t",
        external_account_id="t-1",
        external_username="tuser",
    )
    source = TrelloSource(
        workspace_id=ws.id,
        connection_id=trello_conn.id,
        trello_board_id="b-check",
        name="Check Board",
        url="https://trello.com/b/check",
        excluded=False,
    )
    db_session.add(source)
    await db_session.flush()
    card = TrelloCard(
        workspace_id=ws.id,
        source_id=source.id,
        trello_card_id="c-check",
        list_id="l1",
        list_name="To Do",
        name="Check Card",
        description="",
        closed=False,
        url="https://trello.com/c/check",
        labels=[],
        content_hash="h1",
    )
    db_session.add(card)
    await db_session.commit()

    # 1. Zero parent IDs rejected by ck_chunks_exactly_one_parent
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ContextChunkRecord(
                    workspace_id=ws.id,
                    source_type="jira",
                    project_id=project.id,
                    card_id=None,
                    repository_id=None,
                    issue_id=None,
                    chunk_kind="issue_body",
                    ordinal=0,
                    text="Invalid zero parents",
                    token_estimate=5,
                    chunker_version=2,
                    content_hash=compute_content_hash("zero"),
                )
            )
            await db_session.flush()

    # 2. Two parent IDs (card_id + issue_id) rejected by ck_chunks_exactly_one_parent
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ContextChunkRecord(
                    workspace_id=ws.id,
                    source_type="jira",
                    source_id=source.id,
                    project_id=project.id,
                    card_id=card.id,
                    repository_id=None,
                    issue_id=issue.id,
                    chunk_kind="issue_body",
                    ordinal=0,
                    text="Invalid two parents",
                    token_estimate=5,
                    chunker_version=2,
                    content_hash=compute_content_hash("two"),
                )
            )
            await db_session.flush()

    # 3. Jira chunk without project_id rejected by ck_chunks_parent_source_consistency
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ContextChunkRecord(
                    workspace_id=ws.id,
                    source_type="jira",
                    project_id=None,
                    card_id=None,
                    repository_id=None,
                    issue_id=issue.id,
                    chunk_kind="issue_body",
                    ordinal=0,
                    text="Invalid jira chunk missing project_id",
                    token_estimate=5,
                    chunker_version=2,
                    content_hash=compute_content_hash("no-proj"),
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_per_kind_version_does_not_reembed_trello_github_and_unchanged_jira_is_noop(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, ws = await _setup_workspace(async_client, db_session, name="Version Noop WS")
    _, project, issue = await _create_jira_project_with_issue(
        db_session,
        user=user,
        workspace=ws,
    )
    now = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
    db_session.add(
        JiraComment(
            workspace_id=ws.id,
            issue_id=issue.id,
            cloud_id=project.cloud_id,
            jira_comment_id="jc-1",
            author="Alice Eng",
            body="Verified SAML metadata XML.",
            created_at_jira=now,
            updated_at_jira=now,
            content_hash=compute_content_hash("jc-1"),
        )
    )
    db_session.add(
        JiraChangelogItem(
            workspace_id=ws.id,
            issue_id=issue.id,
            jira_history_id="jh-1",
            item_index=0,
            field="status",
            from_value="To Do",
            to_value="In Progress",
            author="Alice Eng",
            created_at_jira=now,
        )
    )

    # Also seed a Trello card and a GitHub repository + commit at version 1
    trello_conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="trello",
        user_id=user.id,
        encrypted_token="enc-t",
        external_account_id="t-ver",
        external_username="tuser",
    )
    board = TrelloSource(
        workspace_id=ws.id,
        connection_id=trello_conn.id,
        trello_board_id="b-ver",
        name="Ver Board",
        url="https://trello.com/b/ver",
        excluded=False,
    )
    db_session.add(board)
    await db_session.flush()
    card = TrelloCard(
        workspace_id=ws.id,
        source_id=board.id,
        trello_card_id="c-ver",
        list_id="l1",
        list_name="Doing",
        name="Trello Version 1 Card",
        description="Trello body text",
        closed=False,
        url="https://trello.com/c/ver",
        labels=[],
        last_activity_at=now,
        content_hash=compute_content_hash("c-ver"),
    )
    db_session.add(card)

    gh_conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="github",
        user_id=user.id,
        encrypted_token="enc-gh",
        external_account_id="gh-ver",
        external_username="octocat",
    )
    repo = GithubRepository(
        workspace_id=ws.id,
        connection_id=gh_conn.id,
        github_repo_id="r-ver",
        full_name="acme/ver-repo",
        description="Repo",
        url="https://github.com/acme/ver-repo",
        default_branch="main",
        private=True,
        included=True,
        sync_status="completed",
    )
    db_session.add(repo)
    await db_session.flush()
    commit = GithubCommit(
        workspace_id=ws.id,
        repository_id=repo.id,
        sha="a" * 40,
        message="fix: initial commit",
        author_name="Alice",
        author_login="alice",
        committed_at=now,
        url="https://github.com/acme/ver-repo/commit/" + ("a" * 40),
        additions=1,
        deletions=0,
        changed_files=1,
    )
    db_session.add(commit)
    await db_session.commit()

    embedder = CountingEmbedder()
    fake_redis = FakeRedis()
    indexer = IndexingService(db_session, gemini_client=embedder, redis=fake_redis)  # type: ignore[arg-type]

    # Initial index of Trello, GitHub, and Jira
    res_card_1 = await indexer.index_source(board.id)
    res_repo_1 = await indexer.index_repository(repo.id)
    res_jira_1 = await indexer.index_jira_project(project.id)

    assert res_card_1.embedded == 1
    assert res_repo_1.embedded == 1
    assert res_jira_1.inserted == 3
    assert res_jira_1.embedded == 3

    # Verify stored chunker_version values: Trello/GitHub == 1, Jira == 2
    card_chunk = (
        await db_session.execute(
            select(ContextChunkRecord).where(ContextChunkRecord.card_id == card.id)
        )
    ).scalar_one()
    repo_chunk = (
        await db_session.execute(
            select(ContextChunkRecord).where(ContextChunkRecord.repository_id == repo.id)
        )
    ).scalar_one()
    jira_chunks = (
        await db_session.scalars(
            select(ContextChunkRecord).where(ContextChunkRecord.issue_id == issue.id)
        )
    ).all()
    assert card_chunk.chunker_version == 1
    assert repo_chunk.chunker_version == 1
    assert {c.chunker_version for c in jira_chunks} == {2}

    # Re-run index_source, index_repository, and index_jira_project on unchanged data:
    # Must insert 0, delete 0, update 0, and embed 0!
    embedder.embedded_texts.clear()
    res_card_2 = await indexer.index_source(board.id)
    res_repo_2 = await indexer.index_repository(repo.id)

    sql_statements: list[str] = []

    def _capture_sql(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        sql_statements.append(statement.strip().upper())

    sync_engine = db_session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(sync_engine, "before_cursor_execute", _capture_sql)
    try:
        res_jira_2 = await indexer.index_jira_project(project.id)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _capture_sql)

    assert res_card_2.inserted == 0 and res_card_2.deleted == 0 and res_card_2.embedded == 0
    assert res_repo_2.inserted == 0 and res_repo_2.deleted == 0 and res_repo_2.embedded == 0
    assert res_jira_2.inserted == 0
    assert res_jira_2.deleted == 0
    assert res_jira_2.embedded == 0
    assert res_jira_2.unchanged == 3
    assert embedder.embedded_texts == []
    # Verify no INSERT, UPDATE, or DELETE statements were executed during unchanged index_jira_project
    assert not any(
        s.startswith(("INSERT", "UPDATE", "DELETE")) for s in sql_statements
    )


@pytest.mark.asyncio
async def test_issue_edit_reembeds_only_changed_chunk_and_comment_delete_updates_chunks_and_issue_delete_cascades(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, ws = await _setup_workspace(async_client, db_session, name="Diff & Cascade WS")
    _, project, issue = await _create_jira_project_with_issue(
        db_session,
        user=user,
        workspace=ws,
    )
    now = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
    comment_1 = JiraComment(
        workspace_id=ws.id,
        issue_id=issue.id,
        cloud_id=project.cloud_id,
        jira_comment_id="jc-edit-1",
        author="Alice Eng",
        body="First comment body text.",
        created_at_jira=now,
        updated_at_jira=now,
        content_hash=compute_content_hash("jc-edit-1"),
    )
    comment_2 = JiraComment(
        workspace_id=ws.id,
        issue_id=issue.id,
        cloud_id=project.cloud_id,
        jira_comment_id="jc-edit-2",
        author="Bob PM",
        body="UNIQUE_OBSOLETE_COMMENT_TO_DELETE_777",
        created_at_jira=now + timedelta(minutes=5),
        updated_at_jira=now + timedelta(minutes=5),
        content_hash=compute_content_hash("jc-edit-2"),
    )
    transition = JiraChangelogItem(
        workspace_id=ws.id,
        issue_id=issue.id,
        jira_history_id="jh-edit-1",
        item_index=0,
        field="status",
        from_value="Open",
        to_value="In Progress",
        author="Alice Eng",
        created_at_jira=now,
    )
    db_session.add_all([comment_1, comment_2, transition])
    await db_session.commit()

    embedder = CountingEmbedder()
    indexer = IndexingService(db_session, gemini_client=embedder, redis=FakeRedis())  # type: ignore[arg-type]

    res1 = await indexer.index_jira_project(project.id)
    assert res1.inserted == 3
    assert res1.embedded == 3

    chunks_before = {
        c.chunk_kind: c
        for c in (
            await db_session.scalars(
                select(ContextChunkRecord).where(ContextChunkRecord.issue_id == issue.id)
            )
        ).all()
    }
    assert "UNIQUE_OBSOLETE_COMMENT_TO_DELETE_777" in chunks_before["issue_comment_group"].text
    comment_chunk_id_before = chunks_before["issue_comment_group"].id
    transition_chunk_id_before = chunks_before["issue_transition_group"].id

    # 1. Edit ONLY the issue description -> only issue_body is re-embedded!
    embedder.embedded_texts.clear()
    issue.description = "Updated description with new SAML certificate fingerprint."
    await db_session.commit()

    res2 = await indexer.index_jira_project(project.id)
    assert res2.inserted == 0
    assert res2.updated == 1
    assert res2.deleted == 0
    assert res2.embedded == 1
    assert res2.unchanged == 2
    assert len(embedder.embedded_texts) == 1
    assert "Updated description with new SAML certificate fingerprint." in embedder.embedded_texts[0]

    chunks_after_body_edit = {
        c.chunk_kind: c
        for c in (
            await db_session.scalars(
                select(ContextChunkRecord).where(ContextChunkRecord.issue_id == issue.id)
            )
        ).all()
    }
    assert chunks_after_body_edit["issue_comment_group"].id == comment_chunk_id_before
    assert chunks_after_body_edit["issue_transition_group"].id == transition_chunk_id_before

    # 2. Delete comment_2 WITHOUT touching issue.content_hash, then re-index:
    # Old comment text must be removed from chunks!
    embedder.embedded_texts.clear()
    await db_session.delete(comment_2)
    await db_session.commit()

    res3 = await indexer.index_jira_project(project.id)
    assert res3.inserted == 0
    assert res3.updated == 1
    assert res3.deleted == 0
    assert res3.embedded == 1
    assert res3.unchanged == 2

    all_issue_chunks = (
        await db_session.scalars(
            select(ContextChunkRecord).where(ContextChunkRecord.issue_id == issue.id)
        )
    ).all()
    for ch in all_issue_chunks:
        assert "UNIQUE_OBSOLETE_COMMENT_TO_DELETE_777" not in ch.text

    # 3. Deleting the JiraIssue cascades and removes all its chunks
    await db_session.delete(issue)
    await db_session.commit()

    remaining_chunks = await db_session.scalar(
        select(func.count())
        .select_from(ContextChunkRecord)
        .where(ContextChunkRecord.issue_id == issue.id)
    )
    assert remaining_chunks == 0


@pytest.mark.asyncio
async def test_jira_retrieval_keyword_key_lookup_exclusion_cache_invalidation_remap_and_disconnect(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _async_noop(*a: Any, **kw: Any) -> None:
        return None

    monkeypatch.setattr("app.modules.jira.service.notify_app_connected", _async_noop)
    monkeypatch.setattr("app.workers.tasks.sync_jira_project_task.delay", lambda *a, **kw: None)

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr("app.modules.context.indexer._get_loop_redis", lambda: fake_redis)

    class StubGeminiClient:
        async def __aenter__(self) -> StubGeminiClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def embed(self, text: str, *, query: bool = False) -> list[float]:
            del text, query
            return _unit_vec(1)

    monkeypatch.setattr("app.modules.context.service.GeminiContextClient", StubGeminiClient)
    monkeypatch.setattr("app.modules.context.retriever.GeminiContextClient", StubGeminiClient)

    try:
        user1, ws1 = await _setup_workspace(async_client, db_session, name="Retrieval WS 1")
        client_a = TrelloClientRecord(workspace_id=ws1.id, name="Client Alpha")
        client_b = TrelloClientRecord(workspace_id=ws1.id, name="Client Beta")
        db_session.add_all([client_a, client_b])
        await db_session.flush()

        conn1, project1, issue1 = await _create_jira_project_with_issue(
            db_session,
            user=user1,
            workspace=ws1,
            client_id=client_a.id,
            included=True,
            project_key="ACME",
            issue_key="ACME-123",
            summary="Payment gateway webhook signature verification",
            description="Investigate HMAC verification failure on ACME-123.",
        )
        await db_session.commit()

        embedder = CountingEmbedder(vec_index=1)
        indexer = IndexingService(db_session, gemini_client=embedder, redis=fake_redis)  # type: ignore[arg-type]
        await indexer.index_jira_project(project1.id)

        # 1. Exact KEY-123 query is found via the keyword path (keyword_rank == 1)
        # Use an orthogonal query embedding so vector similarity doesn't drive rank 1
        class OrthogonalQueryEmbedder:
            def embed(self, text: str, *, query: bool = False) -> list[float]:
                del text
                assert query is True
                return _unit_vec(99)

        retriever = HybridRetriever(db_session, embedder=OrthogonalQueryEmbedder())
        active = await resolve_active_sources(db_session, ws1.id)
        assert active.project_ids == [project1.id]

        kw_hits = await retriever.search(
            workspace_id=ws1.id,
            query="ACME-123",
            source_ids=active.source_ids,
            repository_ids=active.repository_ids,
            project_ids=active.project_ids,
            limit=5,
        )
        assert len(kw_hits) == 1
        assert kw_hits[0].source_type == "jira"
        assert kw_hits[0].issue_id == issue1.id
        assert kw_hits[0].project_id == project1.id
        assert kw_hits[0].jira_issue_key == "ACME-123"
        assert kw_hits[0].parent_title == "ACME-123: Payment gateway webhook signature verification"
        assert kw_hits[0].parent_url == "https://acme.atlassian.net/browse/ACME-123"
        assert kw_hits[0].scores["keyword_rank"] == 1

        # 2. /api/v1/search returns the Jira chunk and caches it
        search_resp_1 = await async_client.post(
            "/api/v1/search",
            json={"query": "ACME-123", "limit": 5},
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert search_resp_1.status_code == 200
        s1_data = search_resp_1.json()
        assert s1_data["cached"] is False
        assert len(s1_data["results"]) == 1
        assert s1_data["results"][0]["parent_type"] == "issue"
        assert s1_data["results"][0]["parent_id"] == str(issue1.id)
        assert "ACME-123" in s1_data["results"][0]["title"]

        # Second identical /api/v1/search hits cache
        search_resp_cached = await async_client.post(
            "/api/v1/search",
            json={"query": "ACME-123", "limit": 5},
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert search_resp_cached.status_code == 200
        assert search_resp_cached.json()["cached"] is True
        assert len(search_resp_cached.json()["results"]) == 1

        # 3. /api/v1/context/search returns the Jira chunk with additive fields
        ctx_resp_1 = await async_client.post(
            "/api/v1/context/search",
            json={"query": "ACME-123", "limit": 5},
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert ctx_resp_1.status_code == 200
        ctx_results = ctx_resp_1.json()["results"]
        assert len(ctx_results) == 1
        assert ctx_results[0]["source_type"] == "jira"
        assert ctx_results[0]["issue_id"] == str(issue1.id)
        assert ctx_results[0]["project_id"] == str(project1.id)
        assert ctx_results[0]["trello_card_id"] == "ACME-123"

        # 4. Client remap via PUT /api/v1/connections/jira/projects updates chunks.client_id and bumps data_version once
        v_before_remap = int(fake_redis.store.get(f"ws:{ws1.id}:data_version", "1"))
        remap_resp = await async_client.put(
            "/api/v1/connections/jira/projects",
            json={
                "selections": [
                    {
                        "project_id": str(project1.id),
                        "included": True,
                        "client_id": str(client_b.id),
                    }
                ]
            },
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert remap_resp.status_code == 200
        v_after_remap = int(fake_redis.store.get(f"ws:{ws1.id}:data_version", "1"))
        assert v_after_remap == v_before_remap + 1

        chunk_client_ids = (
            await db_session.scalars(
                select(ContextChunkRecord.client_id).where(
                    ContextChunkRecord.project_id == project1.id
                )
            )
        ).all()
        assert list(chunk_client_ids) == [client_b.id]

        # Also test IndexingService.remap_jira_project_client directly
        updated_rows = await indexer.remap_jira_project_client(ws1.id, project1.id, client_a.id)
        assert updated_rows == 1
        assert int(fake_redis.store.get(f"ws:{ws1.id}:data_version", "1")) == v_after_remap + 1

        # 5. Exclude the Jira project -> never returned from /search, /ask, or /context/search,
        # and result cache never serves stale results!
        excl_resp = await async_client.put(
            "/api/v1/connections/jira/projects",
            json={
                "selections": [
                    {
                        "project_id": str(project1.id),
                        "included": False,
                        "client_id": str(client_a.id),
                    }
                ]
            },
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert excl_resp.status_code == 200

        # /api/v1/search returns empty (not stale cached result!)
        search_after_excl = await async_client.post(
            "/api/v1/search",
            json={"query": "ACME-123", "limit": 5},
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert search_after_excl.status_code == 200
        assert search_after_excl.json()["results"] == []

        # /api/v1/context/search returns empty
        ctx_after_excl = await async_client.post(
            "/api/v1/context/search",
            json={"query": "ACME-123", "limit": 5},
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert ctx_after_excl.status_code == 200
        assert ctx_after_excl.json()["results"] == []

        # /api/v1/ask returns empty sources in meta event
        ask_after_excl = await async_client.post(
            "/api/v1/ask",
            json={"question": "What happened on ACME-123?"},
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert ask_after_excl.status_code == 200
        assert '"sources": []' in ask_after_excl.text

        # Re-include project1 to test workspace isolation and disconnect cascade
        await async_client.put(
            "/api/v1/connections/jira/projects",
            json={
                "selections": [
                    {
                        "project_id": str(project1.id),
                        "included": True,
                        "client_id": str(client_a.id),
                    }
                ]
            },
            headers={"X-Workspace-Id": str(ws1.id)},
        )

        # 6. Workspace isolation: User 2 in WS 2 never sees WS 1's Jira chunks
        _, ws2 = await _setup_workspace(async_client, db_session, name="Retrieval WS 2")
        ws2_search = await async_client.post(
            "/api/v1/search",
            json={"query": "ACME-123", "limit": 5},
            headers={"X-Workspace-Id": str(ws2.id)},
        )
        assert ws2_search.status_code == 200
        assert ws2_search.json()["results"] == []

        # 7. Disconnect Jira in WS 1 leaves zero Jira rows and zero Jira chunks
        # Switch back to user 1 by logging in as user 1
        login_u1 = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user1.email, "password": "Password123!"},
        )
        assert login_u1.status_code == 200
        csrf_u1 = async_client.cookies.get("csrf_token")
        if csrf_u1 is not None:
            async_client.headers["X-CSRF-Token"] = csrf_u1

        disc_resp = await async_client.delete(
            "/api/v1/connections/jira",
            headers={"X-Workspace-Id": str(ws1.id)},
        )
        assert disc_resp.status_code == 200

        jira_chunks_left = await db_session.scalar(
            select(func.count())
            .select_from(ContextChunkRecord)
            .where(
                ContextChunkRecord.workspace_id == ws1.id,
                ContextChunkRecord.source_type == "jira",
            )
        )
        assert jira_chunks_left == 0
        for model in (JiraProject, JiraIssue, JiraComment, JiraChangelogItem):
            cnt = await db_session.scalar(
                select(func.count()).select_from(model).where(model.workspace_id == ws1.id)
            )
            assert cnt == 0
    finally:
        app.dependency_overrides.pop(get_redis, None)


def test_a7b8c9d0e1f2_migration_upgrade_downgrade_upgrade_on_throwaway_db_with_trello_github_chunks() -> None:
    """Run upgrade head -> downgrade -1 (f5a6b7c8d9e0) -> upgrade head on an isolated throwaway database
    with real-looking Trello, GitHub, and Jira chunks present before downgrade.
    """
    from tests.test_prompt_6b_digests import (
        _assert_migration_target_safe,
        _build_migration_test_url,
        _create_throwaway_database,
        _drop_throwaway_database,
    )

    target_url = _assert_migration_target_safe(_build_migration_test_url())
    asyncio.run(_create_throwaway_database(target_url))
    prev_env = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = target_url
    try:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", target_url)

        # 1. Upgrade to head (a7b8c9d0e1f2)
        command.upgrade(alembic_cfg, "head")

        # 2. Seed realistic Trello, GitHub, and Jira entities + chunks at head
        async def _seed_and_check_at_head() -> tuple[UUID, UUID, UUID]:
            eng = create_async_engine(target_url, poolclass=pool.NullPool)
            try:
                async with eng.begin() as conn:
                    uid = uuid4()
                    ws_id = uuid4()
                    t_acct = uuid4()
                    g_acct = uuid4()
                    j_acct = uuid4()
                    t_conn = uuid4()
                    g_conn = uuid4()
                    j_conn = uuid4()
                    src_id = uuid4()
                    card_id = uuid4()
                    repo_id = uuid4()
                    proj_id = uuid4()
                    issue_id = uuid4()
                    t_chunk_id = uuid4()
                    g_chunk_id = uuid4()
                    j_chunk_id = uuid4()

                    await conn.execute(
                        text(
                            "INSERT INTO users (id, email, name, hashed_password, is_active, is_verified) "
                            "VALUES (:id, 'mig8b@example.com', 'Mig 8B', 'pw', true, true)"
                        ),
                        {"id": uid},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO workspaces (id, name, slug, owner_id) "
                            "VALUES (:id, 'Mig 8B WS', 'mig-8b-ws', :uid)"
                        ),
                        {"id": ws_id, "uid": uid},
                    )
                    for acct_id, prov in ((t_acct, "trello"), (g_acct, "github"), (j_acct, "jira")):
                        await conn.execute(
                            text(
                                "INSERT INTO provider_accounts (id, user_id, provider, encrypted_token, status, external_account_id, external_username) "
                                "VALUES (:id, :uid, :prov, 'tok', 'active', :ext, :prov)"
                            ),
                            {"id": acct_id, "uid": uid, "prov": prov, "ext": f"ext-{prov}"},
                        )
                    for cid, acct_id, prov in (
                        (t_conn, t_acct, "trello"),
                        (g_conn, g_acct, "github"),
                        (j_conn, j_acct, "jira"),
                    ):
                        await conn.execute(
                            text(
                                "INSERT INTO connections (id, workspace_id, user_id, provider, status, provider_account_id) "
                                "VALUES (:id, :ws, :uid, :prov, 'active', :acct)"
                            ),
                            {"id": cid, "ws": ws_id, "uid": uid, "prov": prov, "acct": acct_id},
                        )

                    await conn.execute(
                        text(
                            "INSERT INTO sources (id, workspace_id, connection_id, trello_board_id, name, url, excluded, sync_status) "
                            "VALUES (:id, :ws, :conn, 'b1', 'Board 1', 'https://trello.com/b/1', false, 'completed')"
                        ),
                        {"id": src_id, "ws": ws_id, "conn": t_conn},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO cards (id, workspace_id, source_id, trello_card_id, list_id, list_name, name, description, closed, url, labels, member_ids, content_hash) "
                            "VALUES (:id, :ws, :src, 'c1', 'l1', 'Doing', 'Card 1', 'Desc', false, 'https://trello.com/c/1', '[]'::jsonb, '[]'::jsonb, :ch)"
                        ),
                        {"id": card_id, "ws": ws_id, "src": src_id, "ch": "a" * 64},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO github_repositories (id, workspace_id, connection_id, github_repo_id, full_name, url, default_branch, private, included, sync_status) "
                            "VALUES (:id, :ws, :conn, 'r1', 'acme/repo', 'https://github.com/acme/repo', 'main', true, true, 'completed')"
                        ),
                        {"id": repo_id, "ws": ws_id, "conn": g_conn},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO jira_projects (id, workspace_id, connection_id, cloud_id, jira_project_id, key, name, project_type_key, included, sync_status) "
                            "VALUES (:id, :ws, :conn, 'acme.atlassian.net', 'jp1', 'ACME', 'Acme', 'software', true, 'completed')"
                        ),
                        {"id": proj_id, "ws": ws_id, "conn": j_conn},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO jira_issues (id, workspace_id, project_id, cloud_id, jira_issue_id, key, summary, description, status, issue_type, labels, url, content_hash) "
                            "VALUES (:id, :ws, :proj, 'acme.atlassian.net', 'ji1', 'ACME-1', 'Issue 1', 'Body', 'Open', 'Bug', '[]'::jsonb, 'https://acme.atlassian.net/browse/ACME-1', :ch)"
                        ),
                        {"id": issue_id, "ws": ws_id, "proj": proj_id, "ch": "b" * 64},
                    )

                    # Insert Trello chunk, GitHub chunk, and Jira chunk
                    await conn.execute(
                        text(
                            "INSERT INTO chunks (id, workspace_id, source_id, source_type, card_id, chunk_kind, ordinal, text, token_estimate, chunker_version, content_hash, metadata) "
                            "VALUES (:id, :ws, :src, 'trello', :card, 'card_body', 0, 'Trello chunk text', 4, 1, :ch, '{}'::jsonb)"
                        ),
                        {"id": t_chunk_id, "ws": ws_id, "src": src_id, "card": card_id, "ch": "c" * 64},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO chunks (id, workspace_id, repository_id, source_type, group_key, chunk_kind, ordinal, text, token_estimate, chunker_version, content_hash, metadata) "
                            "VALUES (:id, :ws, :repo, 'github', '2026-03-15', 'commit_group', 0, 'GitHub chunk text', 4, 1, :ch, '{}'::jsonb)"
                        ),
                        {"id": g_chunk_id, "ws": ws_id, "repo": repo_id, "ch": "d" * 64},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO chunks (id, workspace_id, project_id, source_type, issue_id, chunk_kind, ordinal, text, token_estimate, chunker_version, content_hash, metadata) "
                            "VALUES (:id, :ws, :proj, 'jira', :issue, 'issue_body', 0, 'Jira chunk text', 4, 2, :ch, '{}'::jsonb)"
                        ),
                        {"id": j_chunk_id, "ws": ws_id, "proj": proj_id, "issue": issue_id, "ch": "e" * 64},
                    )
                    return t_chunk_id, g_chunk_id, j_chunk_id
            finally:
                await eng.dispose()

        t_cid, g_cid, _ = asyncio.run(_seed_and_check_at_head())

        # 3. Downgrade -1 (to f5a6b7c8d9e0): derived Jira chunk is removed, Trello & GitHub chunks survive
        command.downgrade(alembic_cfg, "-1")

        async def _verify_after_downgrade() -> None:
            eng = create_async_engine(target_url, poolclass=pool.NullPool)
            try:
                async with eng.connect() as conn:
                    ver = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                    assert ver == "f5a6b7c8d9e0"
                    remaining_ids = set((await conn.scalars(text("SELECT id FROM chunks"))).all())
                    assert remaining_ids == {t_cid, g_cid}
            finally:
                await eng.dispose()

        asyncio.run(_verify_after_downgrade())

        # 4. Upgrade back to head (a7b8c9d0e1f2): Trello & GitHub chunks still intact
        command.upgrade(alembic_cfg, "head")

        async def _verify_after_reupgrade() -> None:
            eng = create_async_engine(target_url, poolclass=pool.NullPool)
            try:
                async with eng.connect() as conn:
                    ver = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                    assert ver == "a7b8c9d0e1f2"
                    remaining_ids = set((await conn.scalars(text("SELECT id FROM chunks"))).all())
                    assert remaining_ids == {t_cid, g_cid}
            finally:
                await eng.dispose()

        asyncio.run(_verify_after_reupgrade())
    finally:
        if prev_env is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = prev_env
        asyncio.run(_drop_throwaway_database(target_url))
