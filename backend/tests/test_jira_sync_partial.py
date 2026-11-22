"""Tests for Jira sync partial-fetch handling, idempotent retry, lock heartbeat extension, and log safety."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.encryption import encryption
from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.jira.client import JiraClient
from app.modules.jira.models import (
    JiraChangelogItem,
    JiraComment,
    JiraIssue,
    JiraProject,
)
from app.modules.jira.sync import (
    acquire_jira_project_lock,
    extend_jira_project_lock,
    release_jira_project_lock,
    sync_jira_project,
)
from app.modules.workspaces.models import Membership, MembershipRole, Workspace
from app.workers.tasks import _EXTEND_LOCK_LUA, _RELEASE_LOCK_LUA


class FakeRedisLockStore:
    """In-memory fake Redis client implementing SET NX EX and Lua compare-and-extend / compare-and-delete."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.extend_calls: list[tuple[str, str, int]] = []
        self.release_calls: list[tuple[str, str]] = []

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        self.set_calls.append((key, value, ex))
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        assert numkeys == 1
        key = str(keys_and_args[0])
        token = str(keys_and_args[1])
        if script.strip() == _EXTEND_LOCK_LUA.strip():
            ttl = int(keys_and_args[2])
            self.extend_calls.append((key, token, ttl))
            if self.store.get(key) == token:
                self.ttls[key] = ttl
                return 1
            return 0
        if script.strip() == _RELEASE_LOCK_LUA.strip():
            self.release_calls.append((key, token))
            if self.store.get(key) == token:
                del self.store[key]
                self.ttls.pop(key, None)
                return 1
            return 0
        raise AssertionError(f"Unexpected Lua script: {script}")


async def _seed_project(
    db_session: AsyncSession,
    *,
    last_synced_at: datetime | None = None,
) -> tuple[Workspace, JiraProject]:
    user = User(
        email=f"partial_{uuid.uuid4().hex[:8]}@example.com",
        name="Partial Sync Tester",
        hashed_password="unused",
    )
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(
        name="Partial Sync WS",
        slug=f"partial-ws-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(
        Membership(workspace_id=workspace.id, user_id=user.id, role=MembershipRole.OWNER)
    )

    connection = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="jira",
        user_id=user.id,
        encrypted_token=encryption.encrypt(
            json.dumps(
                {
                    "auth_type": "api_token",
                    "site_url": "https://acme.atlassian.net",
                    "cloud_id": "acme.atlassian.net",
                    "email": "partial@acme.com",
                    "api_token": "secret-api-token",
                }
            )
        ),
        external_account_id="acme.atlassian.net:acc-partial",
        external_username="Partial Sync User",
    )

    project = JiraProject(
        workspace_id=workspace.id,
        connection_id=connection.id,
        cloud_id="acme.atlassian.net",
        jira_project_id="20000",
        key="PART",
        name="Partial Project",
        included=True,
        last_synced_at=last_synced_at,
    )
    db_session.add(project)
    await db_session.commit()
    return workspace, project


@pytest.mark.asyncio
async def test_failed_comment_fetch_keeps_last_synced_at_and_persists_healthy_issues_then_recovers(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    initial_last_synced = datetime(2026, 11, 20, 8, 0, 0, tzinfo=UTC)
    workspace, project = await _seed_project(
        db_session,
        last_synced_at=initial_last_synced,
    )

    sensitive_summary_1 = "SENSITIVE_ISSUE_SUMMARY_ALPHA_9001"
    sensitive_desc_1 = "SENSITIVE_ISSUE_DESCRIPTION_ALPHA_9001"
    sensitive_comment_body = "SENSITIVE_COMMENT_BODY_BETA_9002"
    sensitive_upstream_error = "SENSITIVE_UPSTREAM_ERROR_BODY_GAMMA_9003"

    fail_comment_fetch = True
    recorded_jqls: list[str] = []

    full_comments_issue_2 = [
        {
            "id": "c-201",
            "author": {"displayName": "Alice"},
            "body": sensitive_comment_body,
            "created": "2026-11-20T09:00:00.000+0000",
            "updated": "2026-11-20T09:00:00.000+0000",
        },
        {
            "id": "c-202",
            "author": {"displayName": "Bob"},
            "body": "Second full comment on PART-2",
            "created": "2026-11-20T09:15:00.000+0000",
            "updated": "2026-11-20T09:15:00.000+0000",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(
                200,
                json={"accountId": "acc-1", "displayName": "Tester", "timeZone": "UTC"},
            )
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode())
            if body.get("fields") == ["id"]:
                return httpx.Response(
                    200,
                    json={"issues": [{"id": "101"}, {"id": "102"}], "isLast": True},
                )
            recorded_jqls.append(body["jql"])
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "id": "101",
                            "key": "PART-1",
                            "fields": {
                                "summary": sensitive_summary_1,
                                "description": sensitive_desc_1,
                                "status": {"name": "In Progress"},
                                "issuetype": {"name": "Task"},
                                "priority": {"name": "High"},
                                "assignee": {"displayName": "Alice"},
                                "reporter": {"displayName": "Bob"},
                                "labels": ["ok"],
                                "created": "2026-11-20T08:00:00.000+0000",
                                "updated": "2026-11-20T08:30:00.000+0000",
                                "comment": {
                                    "comments": [
                                        {
                                            "id": "c-101",
                                            "author": {"displayName": "Alice"},
                                            "body": "Healthy inline comment",
                                            "created": "2026-11-20T08:10:00.000+0000",
                                            "updated": "2026-11-20T08:10:00.000+0000",
                                        }
                                    ],
                                    "total": 1,
                                    "maxResults": 50,
                                },
                            },
                            "changelog": {
                                "histories": [
                                    {
                                        "id": "h-101",
                                        "author": {"displayName": "Alice"},
                                        "created": "2026-11-20T08:20:00.000+0000",
                                        "items": [
                                            {
                                                "field": "status",
                                                "fromString": "Open",
                                                "toString": "In Progress",
                                            }
                                        ],
                                    }
                                ],
                                "total": 1,
                                "maxResults": 50,
                            },
                        },
                        {
                            "id": "102",
                            "key": "PART-2",
                            "fields": {
                                "summary": "Issue with truncated comments",
                                "description": "Needs follow-up comment call",
                                "status": {"name": "Open"},
                                "issuetype": {"name": "Bug"},
                                "created": "2026-11-20T08:05:00.000+0000",
                                "updated": "2026-11-20T08:45:00.000+0000",
                                "comment": {
                                    "comments": full_comments_issue_2[:1],
                                    "total": 2,
                                    "maxResults": 1,
                                },
                            },
                            "changelog": {
                                "histories": [],
                                "total": 0,
                                "maxResults": 50,
                            },
                        },
                    ],
                    "isLast": True,
                },
            )
        if request.url.path == "/rest/api/3/issue/PART-2/comment":
            if fail_comment_fetch:
                return httpx.Response(
                    500,
                    json={"errorMessages": [sensitive_upstream_error]},
                )
            return httpx.Response(
                200,
                json={"comments": full_comments_issue_2, "total": 2, "maxResults": 50},
            )
        return httpx.Response(404)

    fake_redis = FakeRedisLockStore()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="partial@acme.com",
            api_token="secret-api-token",
            http_client=http_client,
        )
        async with client:
            with caplog.at_level(logging.DEBUG):
                # Run 1: Comment fetch for PART-2 fails -> sync is incomplete
                count1 = await sync_jira_project(
                    db_session,
                    project,
                    client=client,
                    redis=fake_redis,
                )
                await db_session.commit()

            assert count1 == 2
            # last_synced_at MUST remain unchanged
            assert project.last_synced_at == initial_last_synced
            assert project.sync_status == "failed"
            assert project.sync_error is not None
            assert "1 comment fetch(es) failed" in project.sync_error
            assert "0 changelog fetch(es) failed" in project.sync_error

            # Sensitive content and upstream body must NEVER appear in sync_error or logs
            for secret in (
                sensitive_summary_1,
                sensitive_desc_1,
                sensitive_comment_body,
                sensitive_upstream_error,
            ):
                assert secret not in (project.sync_error or "")
                assert secret not in caplog.text

            # Fully synced issue PART-1 (and PART-2 issue row + inline comment) are persisted
            persisted_issues = list(
                (
                    await db_session.scalars(
                        select(JiraIssue)
                        .where(JiraIssue.project_id == project.id)
                        .order_by(JiraIssue.key)
                    )
                ).all()
            )
            assert [i.key for i in persisted_issues] == ["PART-1", "PART-2"]

            part1_comments = list(
                (
                    await db_session.scalars(
                        select(JiraComment).where(
                            JiraComment.issue_id == persisted_issues[0].id
                        )
                    )
                ).all()
            )
            assert len(part1_comments) == 1
            assert part1_comments[0].jira_comment_id == "c-101"

            # Run 2: Next sync uses the SAME old last_synced_at window, succeeds, and advances last_synced_at
            fail_comment_fetch = False
            before_run2 = datetime.now(UTC)
            count2 = await sync_jira_project(
                db_session,
                project,
                client=client,
                redis=fake_redis,
            )
            await db_session.commit()

            assert count2 == 2
            assert len(recorded_jqls) == 2
            # Because last_synced_at did not advance on Run 1, Run 2 used the exact same JQL cutoff
            assert recorded_jqls[0] == recorded_jqls[1]
            assert project.sync_status == "completed"
            assert project.sync_error is None
            assert project.last_synced_at is not None
            assert project.last_synced_at >= before_run2
            advanced_last_synced = project.last_synced_at

            part2_comments = list(
                (
                    await db_session.scalars(
                        select(JiraComment)
                        .where(JiraComment.issue_id == persisted_issues[1].id)
                        .order_by(JiraComment.jira_comment_id)
                    )
                ).all()
            )
            assert [c.jira_comment_id for c in part2_comments] == ["c-201", "c-202"]

            # Run 3: Re-running after success is idempotent (no duplicate comments or changelog rows)
            count3 = await sync_jira_project(
                db_session,
                project,
                client=client,
                redis=fake_redis,
            )
            await db_session.commit()
            assert count3 == 2
            assert project.last_synced_at >= advanced_last_synced

            total_comments = await db_session.scalar(
                select(func.count(JiraComment.id)).where(
                    JiraComment.workspace_id == workspace.id
                )
            )
            total_changelogs = await db_session.scalar(
                select(func.count(JiraChangelogItem.id)).where(
                    JiraChangelogItem.workspace_id == workspace.id
                )
            )
            assert total_comments == 3  # c-101, c-201, c-202
            assert total_changelogs == 1  # h-101 item 0


@pytest.mark.asyncio
async def test_failed_changelog_fetch_keeps_last_synced_at_and_recovers_idempotently(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    initial_last_synced = datetime(2026, 11, 20, 10, 0, 0, tzinfo=UTC)
    workspace, project = await _seed_project(
        db_session,
        last_synced_at=initial_last_synced,
    )

    fail_changelog_fetch = True
    sensitive_upstream_changelog_err = "UPSTREAM_CHANGELOG_SECRET_FAILURE_555"
    recorded_jqls: list[str] = []

    full_histories = [
        {
            "id": "hist-1",
            "author": {"displayName": "Alice"},
            "created": "2026-11-20T10:05:00.000+0000",
            "items": [
                {"field": "status", "fromString": "To Do", "toString": "In Progress"},
            ],
        },
        {
            "id": "hist-2",
            "author": {"displayName": "Bob"},
            "created": "2026-11-20T10:15:00.000+0000",
            "items": [
                {"field": "status", "fromString": "In Progress", "toString": "Done"},
            ],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"accountId": "acc-1", "timeZone": "UTC"})
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode())
            if body.get("fields") == ["id"]:
                return httpx.Response(200, json={"issues": [{"id": "301"}], "isLast": True})
            recorded_jqls.append(body["jql"])
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "id": "301",
                            "key": "PART-301",
                            "fields": {
                                "summary": "Changelog truncation test",
                                "description": "Body",
                                "status": {"name": "Done"},
                                "issuetype": {"name": "Task"},
                                "comment": {"comments": [], "total": 0, "maxResults": 50},
                            },
                            "changelog": {
                                "histories": full_histories[:1],
                                "total": 2,
                                "maxResults": 1,
                            },
                        }
                    ],
                    "isLast": True,
                },
            )
        if request.url.path == "/rest/api/3/issue/PART-301/changelog":
            if fail_changelog_fetch:
                return httpx.Response(
                    502,
                    json={"errorMessages": [sensitive_upstream_changelog_err]},
                )
            return httpx.Response(
                200,
                json={"values": full_histories, "total": 2, "isLast": True},
            )
        return httpx.Response(404)

    fake_redis = FakeRedisLockStore()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="partial@acme.com",
            api_token="secret-api-token",
            http_client=http_client,
        )
        async with client:
            with caplog.at_level(logging.DEBUG):
                await sync_jira_project(
                    db_session,
                    project,
                    client=client,
                    redis=fake_redis,
                )
                await db_session.commit()

            assert project.last_synced_at == initial_last_synced
            assert project.sync_status == "failed"
            assert project.sync_error is not None
            assert "0 comment fetch(es) failed" in project.sync_error
            assert "1 changelog fetch(es) failed" in project.sync_error
            assert sensitive_upstream_changelog_err not in (project.sync_error or "")
            assert sensitive_upstream_changelog_err not in caplog.text

            # Only inline history (hist-1) was persisted during the failed run
            changelogs_run1 = list(
                (
                    await db_session.scalars(
                        select(JiraChangelogItem).where(
                            JiraChangelogItem.workspace_id == workspace.id
                        )
                    )
                ).all()
            )
            assert [c.jira_history_id for c in changelogs_run1] == ["hist-1"]

            # Next run succeeds, uses the old cutoff, fetches both histories, and advances last_synced_at
            fail_changelog_fetch = False
            before_run2 = datetime.now(UTC)
            await sync_jira_project(
                db_session,
                project,
                client=client,
                redis=fake_redis,
            )
            await db_session.commit()

            assert len(recorded_jqls) == 2
            assert recorded_jqls[0] == recorded_jqls[1]
            assert project.sync_status == "completed"
            assert project.sync_error is None
            assert project.last_synced_at is not None
            assert project.last_synced_at >= before_run2

            changelogs_run2 = list(
                (
                    await db_session.scalars(
                        select(JiraChangelogItem)
                        .where(JiraChangelogItem.workspace_id == workspace.id)
                        .order_by(JiraChangelogItem.jira_history_id)
                    )
                ).all()
            )
            assert [c.jira_history_id for c in changelogs_run2] == ["hist-1", "hist-2"]

            # Re-run for idempotency
            await sync_jira_project(
                db_session,
                project,
                client=client,
                redis=fake_redis,
            )
            await db_session.commit()
            total_changelogs = await db_session.scalar(
                select(func.count(JiraChangelogItem.id)).where(
                    JiraChangelogItem.workspace_id == workspace.id
                )
            )
            assert total_changelogs == 2


@pytest.mark.asyncio
async def test_lock_extended_during_long_sync_and_aborts_without_deleting_foreign_token(
    db_session: AsyncSession,
) -> None:
    _, project = await _seed_project(db_session)
    fake_redis = FakeRedisLockStore()
    lock_key = f"lock:sync:jira_project:{project.id}"

    # 1. Direct unit check on acquire / extend / release with token comparison
    assert await acquire_jira_project_lock(project.id, "token-a", ttl_seconds=1800, redis=fake_redis)
    assert fake_redis.store[lock_key] == "token-a"
    assert fake_redis.ttls[lock_key] == 1800

    assert await extend_jira_project_lock(project.id, "token-a", ttl_seconds=1800, redis=fake_redis)
    # Replace with another owner's token -> neither extend nor release for token-a may touch it
    fake_redis.store[lock_key] = "token-b"
    fake_redis.ttls[lock_key] = 900
    assert not await extend_jira_project_lock(project.id, "token-a", ttl_seconds=1800, redis=fake_redis)
    assert fake_redis.store[lock_key] == "token-b"
    assert fake_redis.ttls[lock_key] == 900
    assert not await release_jira_project_lock(project.id, "token-a", redis=fake_redis)
    assert fake_redis.store[lock_key] == "token-b"
    # Clean up token-b
    assert await release_jira_project_lock(project.id, "token-b", redis=fake_redis)

    # 2. During a long sync, heartbeat extends the lock TTL; if another token takes over mid-sync,
    #    the sync stops cleanly without committing further writes and does not delete the new owner's lock.
    steal_lock_on_second_issue = False

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"accountId": "acc-1", "timeZone": "UTC"})
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode())
            if body.get("fields") == ["id"]:
                return httpx.Response(200, json={"issues": [{"id": "501"}], "isLast": True})
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "id": "501",
                            "key": "PART-501",
                            "fields": {
                                "summary": "First issue in slow sync",
                                "description": "Desc 1",
                                "status": {"name": "Open"},
                                "issuetype": {"name": "Task"},
                                "comment": {
                                    "comments": [{"id": "c-501", "body": " inline "}],
                                    "total": 2,
                                    "maxResults": 1,
                                },
                            },
                            "changelog": {"histories": [], "total": 0, "maxResults": 50},
                        },
                        {
                            "id": "502",
                            "key": "PART-502",
                            "fields": {
                                "summary": "Second issue after lock stolen",
                                "description": "Desc 2",
                                "status": {"name": "Open"},
                                "issuetype": {"name": "Task"},
                                "comment": {"comments": [], "total": 0, "maxResults": 50},
                            },
                            "changelog": {"histories": [], "total": 0, "maxResults": 50},
                        },
                    ],
                    "isLast": True,
                },
            )
        if request.url.path == "/rest/api/3/issue/PART-501/comment":
            if steal_lock_on_second_issue:
                fake_redis.store[lock_key] = "foreign-owner-token"
                fake_redis.ttls[lock_key] = 1800
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {
                            "id": "c-501",
                            "author": {"displayName": "Dev"},
                            "body": "Full comment",
                            "created": "2026-11-20T10:00:00.000+0000",
                        }
                    ],
                    "total": 1,
                    "maxResults": 50,
                },
            )
        return httpx.Response(404)

    fake_redis.extend_calls.clear()
    transport = httpx.MockTransport(slow_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="partial@acme.com",
            api_token="secret-api-token",
            http_client=http_client,
        )
        async with client:
            # First run: normal slow sync -> heartbeat and step checks extend the lock, then release it
            count_ok = await sync_jira_project(
                db_session,
                project,
                client=client,
                redis=fake_redis,
                heartbeat_interval_seconds=0.01,
            )
            await db_session.commit()
            assert count_ok == 2
            assert len(fake_redis.extend_calls) >= 2
            assert lock_key not in fake_redis.store

    # Reset DB issues and simulate lock stolen mid-sync before PART-502 is processed
    project_pk = project.id
    for issue in (
        await db_session.scalars(select(JiraIssue).where(JiraIssue.project_id == project_pk))
    ).all():
        await db_session.delete(issue)
    project.last_synced_at = None
    await db_session.commit()

    steal_lock_on_second_issue = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="partial@acme.com",
            api_token="secret-api-token",
            http_client=http_client,
        )
        async with client:
            count_aborted = await sync_jira_project(
                db_session,
                project,
                client=client,
                redis=fake_redis,
                heartbeat_interval_seconds=0.01,
            )
            await db_session.commit()

    assert count_aborted == 0
    # Foreign token must still own the lock (not overwritten by extend and not deleted by release)
    assert fake_redis.store.get(lock_key) == "foreign-owner-token"
    # Uncommitted writes from the aborted run were rolled back cleanly
    remaining_issues = list(
        (
            await db_session.scalars(
                select(JiraIssue).where(JiraIssue.project_id == project_pk)
            )
        ).all()
    )
    assert remaining_issues == []
