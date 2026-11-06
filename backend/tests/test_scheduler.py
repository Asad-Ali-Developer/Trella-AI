"""Automated tests for Report Schedules, Cron calculations, and Delta reports."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.delivery.models import Delivery
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.runs.models import Run
from app.modules.scheduler.delta import has_context_changes_since
from app.modules.scheduler.schemas import ScheduleCreateRequest
from app.modules.scheduler.service import ScheduleService, calculate_next_run
from app.modules.skills.models import Skill
from app.modules.trello.models import TrelloCard, TrelloSource
from app.modules.trello.models import TrelloClientRecord as Client
from app.modules.workspaces.models import Workspace

# ---------------------------------------------------------------------------
# Unit tests: calculate_next_run
# ---------------------------------------------------------------------------


def test_calculate_next_run_utc() -> None:
    # Every day at 9:00 UTC
    base = datetime(2026, 11, 1, 8, 0, 0, tzinfo=UTC)
    next_run = calculate_next_run("0 9 * * *", "UTC", base_time=base)
    assert next_run == datetime(2026, 11, 1, 9, 0, 0, tzinfo=UTC)

    # After 9:00 UTC, next run should be next day
    base_after = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
    next_run_after = calculate_next_run("0 9 * * *", "UTC", base_time=base_after)
    assert next_run_after == datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)


def test_calculate_next_run_with_timezone() -> None:
    # 9:00 AM in Asia/Karachi (UTC+5) = 4:00 AM UTC
    base_utc = datetime(2026, 11, 1, 3, 0, 0, tzinfo=UTC)
    next_run = calculate_next_run("0 9 * * *", "Asia/Karachi", base_time=base_utc)
    assert next_run == datetime(2026, 11, 1, 4, 0, 0, tzinfo=UTC)


def test_calculate_next_run_invalid_cron() -> None:
    with pytest.raises(HTTPException) as exc_info:
        calculate_next_run("invalid-cron-format", "UTC")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Helper: Setup workspace with skill and client
# ---------------------------------------------------------------------------


async def _setup_workspace(db_session: AsyncSession) -> tuple[Workspace, Skill, Client, TrelloSource]:
    from app.modules.auth.models import User
    from app.modules.connections.repository import ConnectionRepository

    user = User(
        email=f"owner_{uuid.uuid4().hex[:6]}@example.com",
        name="Workspace Owner",
        hashed_password="hashed_pw_test",
    )
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(
        name="Schedule Test Workspace",
        slug=f"ws-{uuid.uuid4().hex[:6]}",
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()

    connection = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"encrypted-{workspace.id}",
        external_account_id=f"account-{workspace.id}",
        external_username=f"user-{workspace.id}",
    )

    source = TrelloSource(
        workspace_id=workspace.id,
        connection_id=connection.id,
        trello_board_id=f"board_{uuid.uuid4().hex[:6]}",
        name="Test Board",
        url="https://trello.com/b/123",
        excluded=False,
    )
    db_session.add(source)
    await db_session.flush()

    skill = Skill(
        workspace_id=workspace.id,
        name="Scheduled Test Skill",
        slug=f"skill-{uuid.uuid4().hex[:6]}",
        version=1,
        prompt_template="Analyze client {{client_name}}",
        scope_json={"sources": ["board:*"]},
        output_schema_json={"needs": []},
        model_config_json={"provider": "gemini", "model": "gemini-2.0-flash"},
    )
    db_session.add(skill)

    client = Client(workspace_id=workspace.id, name="Schedule Client Inc")
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(workspace)
    await db_session.refresh(skill)
    await db_session.refresh(client)
    await db_session.refresh(source)
    return workspace, skill, client, source


# ---------------------------------------------------------------------------
# Integration tests: Delta detection & Skipped Scheduled Run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_detection(db_session: AsyncSession) -> None:
    workspace, _, client, source = await _setup_workspace(db_session)

    # 1. First run ever (since=None) -> changes detected
    assert await has_context_changes_since(db_session, workspace.id, None, client_id=client.id) is True

    # 2. Since 10 minutes ago, but no cards created -> no changes
    ten_mins_ago = datetime.now(UTC) - timedelta(minutes=10)
    assert await has_context_changes_since(db_session, workspace.id, ten_mins_ago, client_id=client.id) is False

    # 3. Create a card with recent last_activity_at
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        list_id="list_123",
        list_name="In Progress",
        trello_card_id=f"card_{uuid.uuid4().hex[:8]}",
        name="Urgent bug in checkout",
        content_hash="abc123hash",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    # Now delta should detect changes
    assert await has_context_changes_since(db_session, workspace.id, ten_mins_ago, client_id=client.id) is True


@pytest.mark.asyncio
async def test_delta_detection_includes_github_commits(db_session: AsyncSession) -> None:
    """Regression test: has_context_changes_since detects new GitHub commits."""
    workspace, _, client, source = await _setup_workspace(db_session)
    ten_mins_ago = datetime.now(UTC) - timedelta(minutes=10)

    # Initially no changes
    assert await has_context_changes_since(db_session, workspace.id, ten_mins_ago, client_id=client.id) is False

    other_client = Client(workspace_id=workspace.id, name="Other Client Ltd")
    db_session.add(other_client)
    await db_session.flush()

    repo = GithubRepository(
        workspace_id=workspace.id,
        connection_id=source.connection_id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:6]}",
        full_name="acme/backend",
        url="https://github.com/acme/backend",
        default_branch="main",
        private=True,
        included=True,
        client_id=client.id,
    )
    db_session.add(repo)
    await db_session.flush()

    commit = GithubCommit(
        workspace_id=workspace.id,
        repository_id=repo.id,
        sha=uuid.uuid4().hex + "12345678",
        message="fix: handle webhook edge case",
        author_name="Dev",
        committed_at=datetime.now(UTC),
        url="https://github.com/acme/backend/commit/1",
    )
    db_session.add(commit)
    await db_session.commit()

    # Commit for `client` is detected for workspace and for `client`, but not for `other_client`
    assert await has_context_changes_since(db_session, workspace.id, ten_mins_ago) is True
    assert await has_context_changes_since(db_session, workspace.id, ten_mins_ago, client_id=client.id) is True
    assert await has_context_changes_since(db_session, workspace.id, ten_mins_ago, client_id=other_client.id) is False


@pytest.mark.asyncio
async def test_delta_skip_records_valid_run_and_delivery_fk(db_session: AsyncSession) -> None:
    """Regression test: skipping a delta run creates a skipped Run row and valid Delivery.run_id FK."""
    workspace, skill, client, _ = await _setup_workspace(db_session)
    service = ScheduleService(db_session)

    schedule = await service.create_schedule(
        workspace.id,
        ScheduleCreateRequest(
            skill_id=skill.id,
            client_id=client.id,
            name="Delta Skip Test Schedule",
            cron="0 9 * * 1",
            timezone="UTC",
            channel="email",
            recipients=["alerts@example.com"],
            is_delta_only=True,
            active=True,
        ),
    )
    schedule.last_run_at = datetime.now(UTC) + timedelta(seconds=5)
    await db_session.commit()

    # Execute when no context changes have occurred since last_run_at
    result = await service.execute_scheduled_run(schedule.id)
    assert result is None

    deliveries = list(
        (
            await db_session.scalars(
                select(Delivery).where(
                    Delivery.workspace_id == workspace.id,
                    Delivery.schedule_id == schedule.id,
                )
            )
        ).all()
    )
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.status == "skipped"
    assert delivery.run_id != schedule.id

    skipped_run = await db_session.get(Run, delivery.run_id)
    assert skipped_run is not None
    assert skipped_run.status == "skipped"
    assert skipped_run.trigger == "scheduled"
    assert skipped_run.workspace_id == workspace.id


# ---------------------------------------------------------------------------
# API tests: Schedule CRUD & Workspace Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_crud_and_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Sign up user
    email = f"scheduler_{uuid.uuid4().hex[:6]}@example.com"
    signup_res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Scheduler Admin", "password": "Password123!"},
    )
    assert signup_res.status_code == 201
    csrf_token = async_client.cookies.get("csrf_token")
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf_token or ""}

    # 2. Create workspace
    slug = f"ws-sched-{uuid.uuid4().hex[:6]}"
    ws_res = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Scheduler Test WS", "slug": slug},
        headers=headers,
    )
    assert ws_res.status_code == 201
    workspace_id = ws_res.json()["id"]
    headers["X-Workspace-ID"] = workspace_id

    # 3. Get available skills (built-in seeded skill)
    skills_res = await async_client.get("/api/v1/skills", headers=headers)
    assert skills_res.status_code == 200
    skills = skills_res.json()
    assert len(skills) > 0
    skill_id = skills[0]["id"]

    # 4. Create Schedule
    create_payload = {
        "skill_id": skill_id,
        "name": "Weekly Monday Synthesis",
        "cron": "0 9 * * 1",
        "timezone": "UTC",
        "channel": "email",
        "recipients": ["team@example.com"],
        "is_delta_only": True,
        "active": True,
    }
    create_res = await async_client.post(
        "/api/v1/schedules",
        json=create_payload,
        headers=headers,
    )
    assert create_res.status_code == 201
    schedule = create_res.json()
    schedule_id = schedule["id"]
    assert schedule["name"] == "Weekly Monday Synthesis"
    assert schedule["next_run_at"] is not None

    # 4. List Schedules
    list_res = await async_client.get("/api/v1/schedules", headers=headers)
    assert list_res.status_code == 200
    schedules = list_res.json()
    assert len(schedules) >= 1
    assert any(s["id"] == schedule_id for s in schedules)

    # 5. Get Schedule by ID
    get_res = await async_client.get(f"/api/v1/schedules/{schedule_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["cron"] == "0 9 * * 1"

    # 6. Update Schedule
    update_res = await async_client.patch(
        f"/api/v1/schedules/{schedule_id}",
        json={"name": "Updated Schedule Name", "cron": "0 10 * * 2"},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Schedule Name"
    assert update_res.json()["cron"] == "0 10 * * 2"

    # 7. Deliveries history endpoint
    deliv_res = await async_client.get("/api/v1/schedules/deliveries", headers=headers)
    assert deliv_res.status_code == 200
    assert "deliveries" in deliv_res.json()
    assert "total" in deliv_res.json()

    # 7.5. Run Now endpoint execution
    with patch("app.modules.runs.service.RunService.execute_run") as mock_exec:
        async def _fake_exec(run_id: uuid.UUID) -> Run:
            r = await db_session.get(Run, run_id)
            assert r is not None
            r.status = "completed"
            await db_session.flush()
            return r

        mock_exec.side_effect = _fake_exec

        run_now_res = await async_client.post(
            f"/api/v1/schedules/{schedule_id}/run-now",
            headers=headers,
        )
        assert run_now_res.status_code == 200
        assert run_now_res.json()["status"] == "completed"

    # 8. Delete Schedule
    del_res = await async_client.delete(f"/api/v1/schedules/{schedule_id}", headers=headers)
    assert del_res.status_code == 204

    # Confirm 404 after deletion
    get_after = await async_client.get(f"/api/v1/schedules/{schedule_id}", headers=headers)
    assert get_after.status_code == 404
