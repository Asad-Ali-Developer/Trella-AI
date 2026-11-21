"""Comprehensive tests for Jira Cloud integration, ADF conversion, SSRF protection, sync, and reconciliation."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.encryption import encryption
from app.modules.auth.models import User
from app.modules.connections.models import ProviderAccount
from app.modules.connections.repository import ConnectionRepository
from app.modules.jira.adf import adf_to_text
from app.modules.jira.client import (
    JiraAPIError,
    JiraClient,
    JiraRateLimitError,
    validate_jira_site_url,
    validate_same_host_url,
)
from app.modules.jira.models import (
    JiraChangelogItem,
    JiraComment,
    JiraIssue,
    JiraProject,
)
from app.modules.jira.service import JiraConnectionService
from app.modules.jira.sync import (
    compute_jira_comment_content_hash,
    compute_jira_issue_content_hash,
    format_jql_datetime,
    sync_jira_project,
    sync_workspace_jira_projects,
)
from app.modules.trello.models import TrelloClientRecord
from app.modules.workspaces.models import Membership, MembershipRole, Workspace


async def _setup_user_and_workspace(
    async_client: AsyncClient,
    db_session: AsyncSession,
    prefix: str = "jira_sync",
) -> tuple[User, Workspace]:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    signup_resp = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Jira Sync Tester", "password": "Password123!"},
    )
    assert signup_resp.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    csrf_token = async_client.cookies.get("csrf_token")
    if csrf_token is not None:
        async_client.headers["X-CSRF-Token"] = csrf_token

    ws_resp = await async_client.post(
        "/api/v1/workspaces",
        json={"name": f"Workspace {prefix}"},
    )
    assert ws_resp.status_code == 201
    workspace_id = uuid.UUID(ws_resp.json()["id"])
    async_client.headers["X-Workspace-Id"] = str(workspace_id)

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    ws = (await db_session.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
    return user, ws


# ---------------------------------------------------------------------------
# 1. ADF to Plain Text Tests
# ---------------------------------------------------------------------------


def test_adf_to_text_handles_primitives_and_complex_nodes() -> None:
    assert adf_to_text(None) == ""
    assert adf_to_text("already plain text") == "already plain text"
    assert adf_to_text(42) == "42"

    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Sprint Summary"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Hello "},
                    {"type": "mention", "attrs": {"id": "u-1", "text": "@asad"}},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Status is "},
                    {"type": "status", "attrs": {"text": "IN PROGRESS"}},
                    {"type": "text", "text": " "},
                    {"type": "emoji", "attrs": {"shortName": ":rocket:", "text": "🚀"}},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "First bullet"}],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Second bullet"}],
                            }
                        ],
                    },
                ],
            },
            {
                "type": "orderedList",
                "attrs": {"order": 1},
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Step one"}],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Step two"}],
                            }
                        ],
                    },
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [{"type": "text", "text": "print('ok')"}],
            },
            {
                "type": "panel",
                "attrs": {"panelType": "info", "title": "Note"},
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "inlineCard", "attrs": {"url": "https://acme.atlassian.net/browse/ACME-1"}}
                        ],
                    }
                ],
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "Col A"}]}
                                ],
                            },
                            {
                                "type": "tableHeader",
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "Col B"}]}
                                ],
                            },
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "Val 1"}]}
                                ],
                            },
                            {
                                "type": "tableCell",
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "Val 2"}]}
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }

    plain = adf_to_text(doc)
    assert "Sprint Summary" in plain
    assert "Hello @asad\nStatus is [IN PROGRESS] 🚀" in plain
    assert "- First bullet\n- Second bullet" in plain
    assert "1. Step one\n2. Step two" in plain
    assert "print('ok')" in plain
    assert "Note\nhttps://acme.atlassian.net/browse/ACME-1" in plain
    assert "Col A | Col B\nVal 1 | Val 2" in plain


# ---------------------------------------------------------------------------
# 2. SSRF & Same-Host Validation Tests
# ---------------------------------------------------------------------------


def test_ssrf_site_url_validation() -> None:
    assert validate_jira_site_url("https://acme-team.atlassian.net/") == "https://acme-team.atlassian.net"

    # Reject non-https
    with pytest.raises(JiraAPIError, match="HTTPS"):
        validate_jira_site_url("http://acme.atlassian.net")

    # Reject non-atlassian.net host
    with pytest.raises(JiraAPIError, match="atlassian.net"):
        validate_jira_site_url("https://evil.example.com")

    with pytest.raises(JiraAPIError, match="atlassian.net"):
        validate_jira_site_url("https://atlassian.net.evil.com")

    # Reject bare atlassian.net without tenant subdomain
    with pytest.raises(JiraAPIError, match="atlassian.net"):
        validate_jira_site_url("https://atlassian.net")

    # Reject IP literals
    with pytest.raises(JiraAPIError, match="IP address"):
        validate_jira_site_url("https://127.0.0.1")

    with pytest.raises(JiraAPIError, match="IP address"):
        validate_jira_site_url("https://[::1]")

    # Reject custom ports, credentials, paths, queries
    with pytest.raises(JiraAPIError, match="port"):
        validate_jira_site_url("https://acme.atlassian.net:8443")

    with pytest.raises(JiraAPIError, match="credentials"):
        validate_jira_site_url("https://user:pass@acme.atlassian.net")

    with pytest.raises(JiraAPIError, match="path"):
        validate_jira_site_url("https://acme.atlassian.net/subpath")


@pytest.mark.asyncio
async def test_ssrf_rejects_cross_host_redirects_and_pagination_links() -> None:
    with pytest.raises(JiraAPIError, match="unexpected host"):
        validate_same_host_url(
            "https://attacker.example.com/rest/api/3/project/search?startAt=50",
            "https://acme.atlassian.net",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        if "project/search" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "values": [{"id": "100", "key": "ACME", "name": "Acme"}],
                    "isLast": False,
                    "nextPage": "https://evil.atlassian.net/rest/api/3/project/search?startAt=50",
                },
            )
        return httpx.Response(
            302,
            headers={"Location": "https://evil.example.com/steal"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="dev@acme.com",
            api_token="secret-api-token",
            http_client=http_client,
        )
        async with client:
            with pytest.raises(JiraAPIError, match="unexpected host"):
                await client.get_projects()

            with pytest.raises(JiraAPIError, match="unexpected host"):
                await client.verify_myself()


# ---------------------------------------------------------------------------
# 3. Pagination & 429 Retry-After Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_client_search_jql_pagination_and_429_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept_durations: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept_durations.append(seconds)

    monkeypatch.setattr("app.modules.jira.client.asyncio.sleep", fake_sleep)

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert request.method == "POST"
        assert request.url.path == "/rest/api/3/search/jql"
        body = json.loads(request.content.decode())

        if call_count == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "1.5"},
                json={"errorMessages": ["Rate limit exceeded"]},
            )
        if call_count == 2:
            assert "nextPageToken" not in body
            return httpx.Response(
                200,
                json={
                    "issues": [{"id": "101", "key": "ACME-1", "fields": {"summary": "First"}}],
                    "nextPageToken": "page-token-2",
                },
            )
        assert body.get("nextPageToken") == "page-token-2"
        return httpx.Response(
            200,
            json={
                "issues": [{"id": "102", "key": "ACME-2", "fields": {"summary": "Second"}}],
                "isLast": True,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="user@acme.com",
            api_token="tok-123",
            http_client=http_client,
        )
        async with client:
            issues = await client.search_issues_jql(jql='project = "ACME"')

    assert len(issues) == 2
    assert [i["key"] for i in issues] == ["ACME-1", "ACME-2"]
    assert slept_durations == [1.5]
    assert call_count == 3


@pytest.mark.asyncio
async def test_jira_client_429_raises_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.modules.jira.client.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.1"}, text="secret-upstream-body")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="user@acme.com",
            api_token="tok-123",
            http_client=http_client,
            max_retries=2,
        )
        async with client:
            with pytest.raises(JiraRateLimitError) as exc_info:
                await client.search_issues_jql(jql='project = "ACME"')
            assert "secret-upstream-body" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Content Hash & JQL Timezone Formatting Tests
# ---------------------------------------------------------------------------


def test_content_hash_exact_fields_and_jql_timezone_format() -> None:
    created = datetime(2026, 11, 20, 10, 0, 0, tzinfo=UTC)
    updated = datetime(2026, 11, 20, 12, 30, 0, tzinfo=UTC)

    expected_issue_payload = {
        "key": "ACME-1",
        "summary": "Fix login bug",
        "description": "Plain text body",
        "status": "In Progress",
        "issue_type": "Bug",
        "priority": "High",
        "assignee": "Alice",
        "reporter": "Bob",
        "labels": ["auth", "urgent"],
        "created_at_jira": "2026-11-20T10:00:00+00:00",
        "updated_at_jira": "2026-11-20T12:30:00+00:00",
        "url": "https://acme.atlassian.net/browse/ACME-1",
    }
    expected_issue_hash = hashlib.sha256(
        json.dumps(expected_issue_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    actual_issue_hash = compute_jira_issue_content_hash(
        key="ACME-1",
        summary="Fix login bug",
        description="Plain text body",
        status="In Progress",
        issue_type="Bug",
        priority="High",
        assignee="Alice",
        reporter="Bob",
        labels=["urgent", "auth"],  # unsorted input is sorted deterministically
        created_at_jira=created,
        updated_at_jira=updated,
        url="https://acme.atlassian.net/browse/ACME-1",
    )
    assert actual_issue_hash == expected_issue_hash

    expected_comment_payload = {
        "jira_comment_id": "9001",
        "author": "Charlie",
        "body": "Looks good to me",
        "created_at_jira": "2026-11-20T10:00:00+00:00",
        "updated_at_jira": "2026-11-20T12:30:00+00:00",
    }
    expected_comment_hash = hashlib.sha256(
        json.dumps(expected_comment_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    actual_comment_hash = compute_jira_comment_content_hash(
        jira_comment_id="9001",
        author="Charlie",
        body="Looks good to me",
        created_at_jira=created,
        updated_at_jira=updated,
    )
    assert actual_comment_hash == expected_comment_hash

    # JQL datetime formatting in user's timezone (Asia/Karachi is UTC+5)
    utc_dt = datetime(2026, 11, 20, 10, 15, 0, tzinfo=UTC)
    assert format_jql_datetime(utc_dt, "Asia/Karachi") == "2026-11-20 15:15"
    assert format_jql_datetime(utc_dt, "America/New_York") == "2026-11-20 05:15"
    assert format_jql_datetime(utc_dt, "Invalid/Timezone") == "2026-11-20 10:15"


# ---------------------------------------------------------------------------
# 5. Idempotent Sync, Expand vs Truncated Fallback, and Safe Comment Deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_sync_and_comment_deletion_only_on_full_success(
    db_session: AsyncSession,
) -> None:
    user = User(
        email=f"sync_{uuid.uuid4().hex[:8]}@example.com",
        name="Sync Tester",
        hashed_password="unused",
    )
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(
        name="Jira Sync WS",
        slug=f"jira-sync-{uuid.uuid4().hex[:8]}",
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
                    "email": "sync@acme.com",
                    "api_token": "secret-token",
                }
            )
        ),
        external_account_id="acme.atlassian.net:acc-1",
        external_username="Sync User",
    )
    project = JiraProject(
        workspace_id=workspace.id,
        connection_id=connection.id,
        cloud_id="acme.atlassian.net",
        jira_project_id="10000",
        key="ACME",
        name="Acme Core",
        included=True,
    )
    db_session.add(project)
    await db_session.commit()

    recorded_jqls: list[str] = []
    comment_endpoint_calls = 0
    fail_truncated_comment_fetch = False
    active_comments = [
        {
            "id": "c-1",
            "author": {"displayName": "Alice"},
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Comment 1"}]}
                ],
            },
            "created": "2026-11-20T09:00:00.000+0000",
            "updated": "2026-11-20T09:00:00.000+0000",
        },
        {
            "id": "c-2",
            "author": {"displayName": "Bob"},
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Comment 2"}]}
                ],
            },
            "created": "2026-11-20T09:30:00.000+0000",
            "updated": "2026-11-20T09:30:00.000+0000",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal comment_endpoint_calls
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(
                200,
                json={"accountId": "acc-1", "displayName": "Sync User", "timeZone": "Asia/Karachi"},
            )
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode())
            if body.get("fields") == ["id"]:
                return httpx.Response(200, json={"issues": [{"id": "2001"}], "isLast": True})
            recorded_jqls.append(body["jql"])
            assert body.get("expand") == "changelog"
            # When fail_truncated_comment_fetch is True, simulate truncated inline comments (total=5 > len=1)
            comment_payload = (
                {"comments": active_comments[:1], "total": 5, "maxResults": 1}
                if fail_truncated_comment_fetch
                else {
                    "comments": active_comments,
                    "total": len(active_comments),
                    "maxResults": 50,
                }
            )
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "id": "2001",
                            "key": "ACME-1",
                            "fields": {
                                "summary": "Implement Jira sync",
                                "description": {
                                    "type": "doc",
                                    "version": 1,
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [{"type": "text", "text": "Issue body"}],
                                        }
                                    ],
                                },
                                "status": {"name": "In Progress"},
                                "issuetype": {"name": "Task"},
                                "priority": {"name": "High"},
                                "assignee": {"displayName": "Alice"},
                                "reporter": {"displayName": "Bob"},
                                "labels": ["backend", "jira"],
                                "created": "2026-11-20T08:00:00.000+0000",
                                "updated": "2026-11-20T10:00:00.000+0000",
                                "comment": comment_payload,
                            },
                            "changelog": {
                                "histories": [
                                    {
                                        "id": "hist-1",
                                        "author": {"displayName": "Alice"},
                                        "created": "2026-11-20T08:30:00.000+0000",
                                        "items": [
                                            {
                                                "field": "status",
                                                "fromString": "To Do",
                                                "toString": "In Progress",
                                            },
                                            {
                                                "field": "priority",
                                                "fromString": "Medium",
                                                "toString": "High",
                                            },
                                        ],
                                    }
                                ],
                                "total": 1,
                                "maxResults": 50,
                            },
                        }
                    ],
                    "isLast": True,
                },
            )
        if request.url.path == "/rest/api/3/issue/ACME-1/comment":
            comment_endpoint_calls += 1
            if fail_truncated_comment_fetch:
                return httpx.Response(500, json={"errorMessages": ["Server error"]})
            return httpx.Response(
                200,
                json={"comments": active_comments, "total": len(active_comments), "maxResults": 100},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="sync@acme.com",
            api_token="secret-token",
            http_client=http_client,
        )
        async with client:
            before_sync = datetime.now(UTC)
            count1 = await sync_jira_project(db_session, project, client=client)
            await db_session.commit()

            # Verify no per-issue comment call was made because inline comments were not truncated
            assert count1 == 1
            assert comment_endpoint_calls == 0
            assert project.last_synced_at is not None
            assert project.last_synced_at >= before_sync

            # Second sync: idempotent upsert + JQL uses 10-minute lookback in user's timezone (Asia/Karachi)
            count2 = await sync_jira_project(db_session, project, client=client)
            await db_session.commit()
            assert count2 == 1
            assert len(recorded_jqls) == 2
            assert "updated >=" in recorded_jqls[1]

            issues = list(
                (
                    await db_session.scalars(
                        select(JiraIssue).where(JiraIssue.project_id == project.id)
                    )
                ).all()
            )
            comments = list(
                (
                    await db_session.scalars(
                        select(JiraComment).where(JiraComment.workspace_id == workspace.id)
                    )
                ).all()
            )
            changelogs = list(
                (
                    await db_session.scalars(
                        select(JiraChangelogItem).where(
                            JiraChangelogItem.workspace_id == workspace.id
                        )
                    )
                ).all()
            )
            assert len(issues) == 1
            assert issues[0].description == "Issue body"
            assert len(comments) == 2
            assert len(changelogs) == 2
            assert {c.item_index for c in changelogs} == {0, 1}

            # Now simulate a truncated comment fetch that FAILS mid-way: local comment c-2 must NOT be deleted!
            fail_truncated_comment_fetch = True
            await sync_jira_project(db_session, project, client=client)
            await db_session.commit()
            assert comment_endpoint_calls == 1
            comments_after_failed_fetch = list(
                (
                    await db_session.scalars(
                        select(JiraComment).where(JiraComment.workspace_id == workspace.id)
                    )
                ).all()
            )
            assert len(comments_after_failed_fetch) == 2

            # Now remove c-2 in Jira and allow full comment fetch to succeed -> c-2 is deleted locally
            fail_truncated_comment_fetch = False
            active_comments = active_comments[:1]
            await sync_jira_project(db_session, project, client=client)
            await db_session.commit()
            comments_after_success = list(
                (
                    await db_session.scalars(
                        select(JiraComment).where(JiraComment.workspace_id == workspace.id)
                    )
                ).all()
            )
            assert len(comments_after_success) == 1
            assert comments_after_success[0].jira_comment_id == "c-1"


# ---------------------------------------------------------------------------
# 6. Reconciliation Tests (Normal <= 50% Deletion vs > 50% Mass-Deletion Guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_deletes_under_threshold_and_aborts_over_50_percent(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = User(
        email=f"rec_{uuid.uuid4().hex[:8]}@example.com",
        name="Reconcile Tester",
        hashed_password="unused",
    )
    db_session.add(user)
    await db_session.flush()
    workspace = Workspace(
        name="Reconcile WS",
        slug=f"reconcile-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()
    connection = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="jira",
        user_id=user.id,
        encrypted_token=encryption.encrypt("{}"),
        external_account_id="acme:1",
        external_username="Rec User",
    )
    project = JiraProject(
        workspace_id=workspace.id,
        connection_id=connection.id,
        cloud_id="acme.atlassian.net",
        jira_project_id="10001",
        key="REC",
        name="Reconcile Project",
        included=True,
    )
    db_session.add(project)
    await db_session.flush()

    # Seed 4 local issues
    for idx in range(1, 5):
        db_session.add(
            JiraIssue(
                workspace_id=workspace.id,
                project_id=project.id,
                cloud_id="acme.atlassian.net",
                jira_issue_id=f"issue-{idx}",
                key=f"REC-{idx}",
                summary=f"Sensitive Summary {idx}",
                description=f"Sensitive Description {idx}",
                status="Open",
                issue_type="Task",
                content_hash="a" * 64,
            )
        )
    await db_session.commit()

    # Case 1: Remote returns only 1 of 4 issues (would delete 3/4 = 75% > 50%) -> ABORT and log warning without content
    remote_ids = ["issue-1"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"accountId": "1", "timeZone": "UTC"})
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode())
            if body.get("fields") == ["id"]:
                return httpx.Response(
                    200,
                    json={"issues": [{"id": rid} for rid in remote_ids], "isLast": True},
                )
            return httpx.Response(200, json={"issues": [], "isLast": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="rec@acme.com",
            api_token="tok",
            http_client=http_client,
        )
        async with client:
            with caplog.at_level(logging.WARNING):
                await sync_jira_project(db_session, project, client=client)
                await db_session.commit()

            remaining_after_abort = list(
                (
                    await db_session.scalars(
                        select(JiraIssue).where(JiraIssue.project_id == project.id)
                    )
                ).all()
            )
            assert len(remaining_after_abort) == 4
            assert "Sensitive Summary" not in caplog.text
            assert "Sensitive Description" not in caplog.text

            # Case 2: Remote returns 3 of 4 issues (deletes 1/4 = 25% <= 50%) -> deletes issue-4
            remote_ids = ["issue-1", "issue-2", "issue-3"]
            await sync_jira_project(db_session, project, client=client)
            await db_session.commit()

            remaining_after_reconcile = list(
                (
                    await db_session.scalars(
                        select(JiraIssue).where(JiraIssue.project_id == project.id)
                    )
                ).all()
            )
            assert {i.jira_issue_id for i in remaining_after_reconcile} == {
                "issue-1",
                "issue-2",
                "issue-3",
            }


# ---------------------------------------------------------------------------
# 7. Per-Project Non-Fatal Failures, Disconnect Cascade, Workspace Isolation,
#    Data Version Bumps, and Credentials Never Logged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_project_non_fatal_failure_and_disconnect_leaves_zero_rows(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, ws = await _setup_user_and_workspace(async_client, db_session, prefix="cascade")
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=ws.id,
        provider="jira",
        user_id=user.id,
        encrypted_token=encryption.encrypt(
            json.dumps(
                {
                    "auth_type": "api_token",
                    "site_url": "https://acme.atlassian.net",
                    "cloud_id": "acme.atlassian.net",
                    "email": "user@acme.com",
                    "api_token": "top-secret-jira-token",
                }
            )
        ),
        external_account_id="acme:acc-1",
        external_username="Cascade User",
    )
    proj_fail = JiraProject(
        workspace_id=ws.id,
        connection_id=conn.id,
        cloud_id="acme.atlassian.net",
        jira_project_id="p-fail",
        key="FAIL",
        name="Failing Project",
        included=True,
    )
    proj_ok = JiraProject(
        workspace_id=ws.id,
        connection_id=conn.id,
        cloud_id="acme.atlassian.net",
        jira_project_id="p-ok",
        key="OK",
        name="Working Project",
        included=True,
    )
    db_session.add_all([proj_fail, proj_ok])
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"accountId": "acc-1", "timeZone": "UTC"})
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode())
            if '"FAIL"' in body.get("jql", ""):
                return httpx.Response(403, json={"errorMessages": ["Forbidden project"]})
            if body.get("fields") == ["id"]:
                return httpx.Response(200, json={"issues": [{"id": "ok-1"}], "isLast": True})
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "id": "ok-1",
                            "key": "OK-1",
                            "fields": {
                                "summary": "Healthy issue",
                                "description": "Healthy desc",
                                "status": {"name": "Done"},
                                "issuetype": {"name": "Story"},
                                "comment": {
                                    "comments": [
                                        {
                                            "id": "ok-c-1",
                                            "author": {"displayName": "Dev"},
                                            "body": "Done comment",
                                            "created": "2026-11-20T10:00:00.000+0000",
                                        }
                                    ],
                                    "total": 1,
                                    "maxResults": 50,
                                },
                            },
                            "changelog": {
                                "histories": [
                                    {
                                        "id": "ok-h-1",
                                        "author": {"displayName": "Dev"},
                                        "created": "2026-11-20T10:00:00.000+0000",
                                        "items": [
                                            {"field": "status", "fromString": "Open", "toString": "Done"}
                                        ],
                                    }
                                ],
                                "total": 1,
                                "maxResults": 50,
                            },
                        }
                    ],
                    "isLast": True,
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = JiraClient(
            site_url="https://acme.atlassian.net",
            email="user@acme.com",
            api_token="top-secret-jira-token",
            http_client=http_client,
        )
        async with client:
            results = await sync_workspace_jira_projects(
                db_session,
                ws.id,
                conn.id,
                client=client,
            )

    assert results == {proj_ok.id: 1}
    await db_session.refresh(proj_fail)
    await db_session.refresh(proj_ok)
    assert proj_fail.sync_status == "failed"
    assert proj_fail.sync_error is not None
    assert proj_ok.sync_status == "completed"

    # Verify rows exist before disconnect
    assert (
        await db_session.scalar(
            select(func.count(JiraIssue.id)).where(JiraIssue.workspace_id == ws.id)
        )
    ) == 1
    assert (
        await db_session.scalar(
            select(func.count(JiraComment.id)).where(JiraComment.workspace_id == ws.id)
        )
    ) == 1
    assert (
        await db_session.scalar(
            select(func.count(JiraChangelogItem.id)).where(
                JiraChangelogItem.workspace_id == ws.id
            )
        )
    ) == 1

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.modules.jira.service.increment_workspace_data_version",
        bump_mock,
    )

    # Disconnect via API -> must cascade delete all Jira rows and bump data_version after commit
    disc_resp = await async_client.delete("/api/v1/connections/jira")
    assert disc_resp.status_code == 200
    assert disc_resp.json()["connected"] is False
    bump_mock.assert_awaited_once_with(ws.id)

    for model in (JiraProject, JiraIssue, JiraComment, JiraChangelogItem):
        count = await db_session.scalar(
            select(func.count()).select_from(model).where(model.workspace_id == ws.id)
        )
        assert count == 0


@pytest.mark.asyncio
async def test_workspace_isolation_and_credentials_never_logged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_token = "ATATT3xFfGF0_SUPER_SECRET_JIRA_TOKEN_99999"
    user_a, ws_a = await _setup_user_and_workspace(async_client, db_session, prefix="iso_a")

    def ok_myself_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(
                200,
                json={"accountId": "acc-iso", "displayName": "Iso User", "emailAddress": "iso@acme.com"},
            )
        if request.url.path == "/rest/api/3/project/search":
            return httpx.Response(
                200,
                json={
                    "values": [
                        {
                            "id": "5001",
                            "key": "ISO",
                            "name": "Isolated Project",
                            "projectTypeKey": "software",
                            "avatarUrls": {"48x48": "https://acme.atlassian.net/avatar.png"},
                        }
                    ],
                    "isLast": True,
                },
            )
        return httpx.Response(404)

    orig_init = JiraClient.__init__

    def patched_init(self: JiraClient, *args: Any, **kwargs: Any) -> None:
        kwargs["http_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(ok_myself_handler),
            follow_redirects=False,
        )
        orig_init(self, *args, **kwargs)
        self._owns_client = True

    monkeypatch.setattr(JiraClient, "__init__", patched_init)
    monkeypatch.setattr("app.modules.jira.service.notify_app_connected", AsyncMock())

    with caplog.at_level(logging.DEBUG):
        # 1. Test connection endpoint
        test_resp = await async_client.post(
            "/api/v1/connections/jira/test",
            json={
                "site_url": "https://acme.atlassian.net",
                "email": "iso@acme.com",
                "api_token": secret_token,
            },
        )
        assert test_resp.status_code == 200
        assert test_resp.json()["ok"] is True

        # 2. Save connection endpoint
        connect_resp = await async_client.post(
            "/api/v1/connections/jira",
            json={
                "site_url": "https://acme.atlassian.net",
                "email": "iso@acme.com",
                "api_token": secret_token,
            },
        )
        assert connect_resp.status_code == 200
        assert connect_resp.json()["connected"] is True

        # Verify encrypted at rest in DB
        account = (
            await db_session.scalars(
                select(ProviderAccount).where(
                    ProviderAccount.user_id == user_a.id,
                    ProviderAccount.provider == "jira",
                )
            )
        ).first()
        assert account is not None
        assert secret_token not in account.encrypted_token

        # 3. Fetch projects in Workspace A
        projects_resp = await async_client.get("/api/v1/connections/jira/projects")
        assert projects_resp.status_code == 200
        proj_id = projects_resp.json()[0]["id"]

        # 4. Select project & map to client in Workspace A
        client_rec = TrelloClientRecord(workspace_id=ws_a.id, name="Client A")
        db_session.add(client_rec)
        await db_session.commit()

        scheduled: list[uuid.UUID] = []

        async def fake_enqueue(pid: uuid.UUID) -> None:
            scheduled.append(pid)

        monkeypatch.setattr("app.modules.jira.router.enqueue_jira_project_sync", fake_enqueue)
        bump_mock = AsyncMock(return_value=1)
        monkeypatch.setattr(
            "app.modules.jira.service.increment_workspace_data_version",
            bump_mock,
        )

        save_resp = await async_client.put(
            "/api/v1/connections/jira/projects",
            json={
                "selections": [
                    {"project_id": proj_id, "included": True, "client_id": str(client_rec.id)}
                ]
            },
        )
        assert save_resp.status_code == 200
        assert save_resp.json()[0]["included"] is True
        assert save_resp.json()[0]["client_id"] == str(client_rec.id)
        assert len(scheduled) == 1
        assert bump_mock.await_count == 1

        # 5. Manual sync endpoint
        sync_resp = await async_client.post("/api/v1/connections/jira/sync")
        assert sync_resp.status_code == 202
        assert sync_resp.json()["scheduled"] == 1

        # 6. Create User B / Workspace B -> must not access Workspace A's Jira connection or projects
        _, ws_b = await _setup_user_and_workspace(async_client, db_session, prefix="iso_b")
        status_b = await async_client.get("/api/v1/connections/jira")
        assert status_b.status_code == 200
        assert status_b.json()["connected"] is False

        projects_b = await async_client.get("/api/v1/connections/jira/projects")
        assert projects_b.status_code == 409

    # Secret token must never appear anywhere in logs
    assert secret_token not in caplog.text


@pytest.mark.asyncio
async def test_oauth_token_refresh_uses_row_lock_and_updates_encrypted_token(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.jira.client import JiraOAuthTokens

    user = User(
        email=f"oauth_lock_{uuid.uuid4().hex[:8]}@example.com",
        name="OAuth Lock Tester",
        hashed_password="unused",
    )
    db_session.add(user)
    await db_session.flush()
    workspace = Workspace(
        name="OAuth Lock WS",
        slug=f"oauth-lock-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()

    expired_bundle = {
        "auth_type": "oauth",
        "access_token": "expired-access-token",
        "refresh_token": "valid-refresh-token",
        "expires_at": 1000,
        "cloud_id": "cloud-123",
        "site_name": "Acme",
        "site_url": "https://acme.atlassian.net",
    }
    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="jira",
        user_id=user.id,
        encrypted_token=encryption.encrypt(json.dumps(expired_bundle)),
        external_account_id="jira-oauth-1",
        external_username="OAuth User",
    )
    await db_session.commit()

    monkeypatch.setattr("app.modules.jira.service.settings.JIRA_CLIENT_ID", "cid")
    monkeypatch.setattr("app.modules.jira.service.settings.JIRA_CLIENT_SECRET", "csecret")

    refresh_mock = AsyncMock(
        return_value=JiraOAuthTokens(
            access_token="fresh-access-token",
            refresh_token="fresh-refresh-token",
            expires_in=3600,
        )
    )
    monkeypatch.setattr(
        "app.modules.jira.service.JiraOAuthClient.refresh_tokens",
        refresh_mock,
    )

    account = await db_session.get(ProviderAccount, conn.provider_account_id)
    assert account is not None
    service = JiraConnectionService(db_session, workspace.id, user.id)
    client, cloud_id, _ = await service.open_client(account)
    await db_session.commit()

    assert cloud_id == "cloud-123"
    assert client.access_token == "fresh-access-token"
    refresh_mock.assert_awaited_once_with("valid-refresh-token")

    await db_session.refresh(account)
    updated_data = json.loads(encryption.decrypt(account.encrypted_token))
    assert updated_data["access_token"] == "fresh-access-token"
    assert updated_data["refresh_token"] == "fresh-refresh-token"
