"""Tests for Client Profile, Timeline, and Management APIs."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connections.repository import ConnectionRepository
from app.modules.llm.base import LLMResult
from app.modules.skills.schemas import ClientNeedsReport, NeedInsight, RiskInsight
from app.modules.skills.service import SkillService
from app.modules.trello.models import TrelloCard, TrelloClientRecord, TrelloSource
from app.modules.workspaces.models import Membership, Workspace


async def _create_user_and_workspace(async_client: AsyncClient, name: str = "Client WS") -> tuple[str, str]:
    email = f"client_test_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "SecurePassword123!"

    resp = await async_client.post("/api/v1/auth/signup", json={"email": email, "password": pwd, "name": "Client Tester"})
    assert resp.status_code == 201

    user_id = str(resp.json()["user"]["id"])
    async_client.headers["Origin"] = "http://localhost:3000"
    csrf_token = async_client.cookies.get("csrf_token")
    if csrf_token is not None:
        async_client.headers["X-CSRF-Token"] = csrf_token

    slug = f"ws-{uuid.uuid4().hex[:6]}"
    ws_resp = await async_client.post("/api/v1/workspaces", json={"name": name, "slug": slug, "client_name": "Acme Corp"})
    assert ws_resp.status_code == 201
    workspace_id = str(ws_resp.json()["id"])
    async_client.headers["X-Workspace-Id"] = workspace_id
    return user_id, workspace_id


@pytest.mark.asyncio
async def test_clients_crud_and_profile_api(async_client: AsyncClient, db_session: AsyncSession) -> None:
    """Test creating clients, listing them, and fetching deep profile and timeline."""
    user_id, workspace_id = await _create_user_and_workspace(async_client, "Client Profile WS")
    ws_uuid = uuid.UUID(workspace_id)
    user_uuid = uuid.UUID(user_id)

    # 1. Initially, no clients
    resp = await async_client.get("/api/v1/clients")
    assert resp.status_code == 200
    assert resp.json() == []

    # 2. Create client "Acme Corporation"
    create_resp = await async_client.post("/api/v1/clients", json={"name": "Acme Corporation"})
    assert create_resp.status_code == 201
    client_data = create_resp.json()
    client_id = client_data["id"]
    assert client_data["name"] == "Acme Corporation"
    assert client_data["cards_count"] == 0

    # 3. Duplicate name returns 409
    dup_resp = await async_client.post("/api/v1/clients", json={"name": "Acme Corporation"})
    assert dup_resp.status_code == 409

    # 4. Add mock card linked to client
    conn_repo = ConnectionRepository(db_session)
    conn = await conn_repo.upsert_provider_connection(
        workspace_id=ws_uuid,
        provider="trello",
        user_id=user_uuid,
        encrypted_token="enc_token",
        external_account_id=f"acc_{uuid.uuid4().hex[:6]}",
        external_username="test_user",
    )
    source = TrelloSource(
        workspace_id=ws_uuid,
        connection_id=conn.id,
        trello_board_id=f"board_{uuid.uuid4().hex[:6]}",
        name="Acme Roadmap",
        url="https://trello.com/b/acme",
        sync_status="completed",
    )
    db_session.add(source)
    await db_session.flush()

    card = TrelloCard(
        workspace_id=ws_uuid,
        source_id=source.id,
        client_id=uuid.UUID(client_id),
        trello_card_id=f"card_{uuid.uuid4().hex[:8]}",
        name="Deliver API Documentation",
        description="Write OpenAPI docs for client review",
        list_id="list_1",
        list_name="In Progress",
        content_hash="mock_hash_123",
    )
    db_session.add(card)
    await db_session.commit()

    # 5. Seed skill and execute run for this client
    skill_service = SkillService(db_session)
    await skill_service.seed_builtin_skills()
    skill = await skill_service.get_skill_by_slug("client-needs-analyzer")
    assert skill is not None

    mock_report = ClientNeedsReport(
        client_name="Acme Corporation",
        executive_summary="Executive report for Acme",
        needs=[
            NeedInsight(
                text="Require SSO authentication for Acme",
                priority="high",
                sources=[],
            )
        ],
        patterns=[],
        stakeholders=[],
        risks=[
            RiskInsight(
                text="Delivery timeline pushed back",
                severity="high",
                sources=[],
            )
        ],
    )
    mock_llm_result = LLMResult(
        content=mock_report.model_dump_json(),
        prompt_tokens=200,
        completion_tokens=100,
        total_tokens=300,
        cost_usd=0.000045,
        model="gemini-3.5-flash",
        provider="gemini",
    )

    with patch("app.modules.runs.service.get_llm_provider") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.generate_structured.return_value = (mock_report, mock_llm_result)
        mock_get_provider.return_value = mock_provider

        run_resp = await async_client.post(
            "/api/v1/runs?execute_async=false",
            json={"skill_id": str(skill.id), "client_id": client_id, "trigger": "manual"},
        )
        assert run_resp.status_code == 201

    # 6. List clients - should now show metrics (1 card, 2 insights, 1 need, 1 risk)
    list_resp = await async_client.get("/api/v1/clients")
    assert list_resp.status_code == 200
    clients_list = list_resp.json()
    assert len(clients_list) == 1
    c = clients_list[0]
    assert c["name"] == "Acme Corporation"
    assert c["cards_count"] == 1
    assert c["insights_count"] == 2
    assert c["needs_count"] == 1
    assert c["risks_count"] == 1
    assert c["last_run_at"] is not None

    # 7. Get full client profile
    profile_resp = await async_client.get(f"/api/v1/clients/{client_id}")
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["client"]["name"] == "Acme Corporation"
    assert profile["total_cards"] == 1
    assert profile["total_insights"] == 2
    assert len(profile["needs"]) == 1
    assert profile["needs"][0]["title"] == "Require SSO authentication for Acme"
    assert len(profile["risks"]) == 1
    assert profile["risks"][0]["severity_or_priority"] == "high"
    assert len(profile["timeline"]) >= 2  # Has card + run + risk
    assert len(profile["recent_runs"]) == 1

    # 8. Timeline endpoint
    timeline_resp = await async_client.get(f"/api/v1/clients/{client_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline_events = timeline_resp.json()
    assert len(timeline_events) >= 2
    types = [e["event_type"] for e in timeline_events]
    assert "skill_run" in types
    assert "card_activity" in types


@pytest.mark.asyncio
async def test_client_workspace_isolation(async_client: AsyncClient) -> None:
    """Verify workspace isolation: Client created in WS1 cannot be retrieved in WS2."""
    _, ws1_id = await _create_user_and_workspace(async_client, "Isolation WS 1")
    create_resp = await async_client.post("/api/v1/clients", json={"name": "Confidential Client"})
    assert create_resp.status_code == 201
    client_id = create_resp.json()["id"]

    # Switch header to WS2
    _, ws2_id = await _create_user_and_workspace(async_client, "Isolation WS 2")
    async_client.headers["X-Workspace-Id"] = ws2_id

    # List in WS2 should not contain client
    list_resp = await async_client.get("/api/v1/clients")
    assert list_resp.status_code == 200
    assert not any(c["id"] == client_id for c in list_resp.json())

    # Direct profile fetch should 404
    get_resp = await async_client.get(f"/api/v1/clients/{client_id}")
    assert get_resp.status_code == 404
