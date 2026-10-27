"""Comprehensive tests for Phase 4: LLM Layer, Skill Engine, Runs, and Citations."""

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.context.schemas import (
    ContextChunk,
    ContextItem,
    ContextSource,
    WorkspaceContextResponse,
)
from app.modules.llm.base import LLMResult
from app.modules.llm.factory import get_llm_provider
from app.modules.llm.gemini import GeminiProvider
from app.modules.runs.citations import validate_and_enrich_citations
from app.modules.runs.models import Insight, Run
from app.modules.runs.schemas import RunCreateRequest
from app.modules.runs.service import RunService
from app.modules.skills.builtin import BUILTIN_SKILLS
from app.modules.skills.models import Skill
from app.modules.skills.schemas import (
    CitedSource,
    ClientNeedsReport,
    NeedInsight,
    PatternInsight,
    RiskInsight,
    SkillCreate,
    StakeholderInsight,
)
from app.modules.skills.service import SkillService
from app.modules.workspaces.models import Workspace


async def _create_user_and_workspace(async_client: AsyncClient) -> tuple[str, str]:
    email = f"skilltest_{uuid.uuid4().hex[:8]}@example.com"
    signup_resp = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Skill Tester", "password": "Password123!"},
    )
    assert signup_resp.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    csrf_token = async_client.cookies.get("csrf_token")
    if csrf_token is not None:
        async_client.headers["X-CSRF-Token"] = csrf_token

    # Create workspace for this user
    slug = f"skill-ws-{uuid.uuid4().hex[:6]}"
    ws_resp = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Skill Test Workspace", "slug": slug},
    )
    assert ws_resp.status_code == 201
    workspace_id = str(ws_resp.json()["id"])
    async_client.headers["X-Workspace-Id"] = workspace_id
    return email, workspace_id


def test_gemini_cost_calculation() -> None:
    """Test cost calculation formula for Gemini Flash ($0.075 / 1M in, $0.30 / 1M out)."""
    with patch("app.modules.llm.gemini.settings") as mock_settings:
        mock_settings.GEMINI_API_KEY = "test_key"
        mock_settings.GEMINI_CONTEXT_MODEL = "gemini-2.5-flash"
        provider = GeminiProvider(api_key="test_key")

        # 1M prompt tokens = $0.075, 1M completion tokens = $0.30 -> Total $0.375
        cost = provider._calculate_cost(1_000_000, 1_000_000)
        assert cost == 0.375

        # 2,000 prompt tokens, 500 completion tokens
        cost_small = provider._calculate_cost(2000, 500)
        expected = round((2000 / 1_000_000 * 0.075) + (500 / 1_000_000 * 0.30), 6)
        assert cost_small == expected


@pytest.mark.asyncio
async def test_citation_validator_valid_and_invalid() -> None:
    """Test grounding validator: verifies matches and flags ungrounded source IDs."""
    source_id = uuid.uuid4()
    card_uuid = uuid.uuid4()

    context = WorkspaceContextResponse(
        workspace_id=uuid.uuid4(),
        workspace_name="Test Workspace",
        generated_at=datetime.now(UTC),
        token_budget=8000,
        estimated_tokens=500,
        connected_accounts=[],
        sources=[
            ContextSource(
                id=source_id,
                provider="trello",
                name="Main Board",
                url="https://trello.com/b/main",
                account_name="Team Account",
                sync_status="completed",
                last_synced_at=None,
            )
        ],
        clients=[],
        members=[],
        item_count=2,
        chunks=[
            ContextChunk(
                index=0,
                estimated_tokens=500,
                items=[
                    ContextItem(
                        item_type="card",
                        card_id=card_uuid,
                        external_id="trello-card-123",
                        title="Integrate Payment Gateway",
                        text="Client requests Stripe integration by Friday",
                        url="https://trello.com/c/123",
                    ),
                    ContextItem(
                        item_type="commit",
                        source_id=source_id,
                        external_id="abc1234",
                        title="Add checkout webhook",
                        text="Initial commit for checkout",
                        url="https://github.com/repo/commit/abc1234",
                    ),
                ],
            )
        ],
    )

    # 1. Report with fully valid citations
    valid_report = ClientNeedsReport(
        client_name="Acme Corp",
        executive_summary="Client needs payment processing.",
        needs=[
            NeedInsight(
                text="Stripe checkout integration",
                priority="high",
                sources=[CitedSource(source_id="trello-card-123")],
            )
        ],
        patterns=[
            PatternInsight(
                text="Regular checkout updates",
                sources=[CitedSource(source_id="abc1234")],
            )
        ],
        stakeholders=[],
        risks=[
            RiskInsight(
                text="Tight deadline for payment",
                severity="high",
                sources=[CitedSource(source_id=str(card_uuid))],
            )
        ],
    )

    enriched, all_valid = validate_and_enrich_citations(valid_report, context)
    assert all_valid is True
    assert enriched.needs[0].sources[0].valid is True
    assert enriched.needs[0].sources[0].title == "Integrate Payment Gateway"
    assert enriched.needs[0].sources[0].url == "https://trello.com/c/123"
    assert enriched.patterns[0].sources[0].valid is True
    assert enriched.patterns[0].sources[0].title == "Add checkout webhook"
    assert enriched.risks[0].sources[0].valid is True

    # 2. Report with hallucinated/invalid citation
    invalid_report = ClientNeedsReport(
        client_name="Acme Corp",
        executive_summary="Client needs payments.",
        needs=[
            NeedInsight(
                text="Unsupported feature request",
                priority="medium",
                sources=[CitedSource(source_id="hallucinated-id-999")],
            )
        ],
        patterns=[],
        stakeholders=[],
        risks=[],
    )

    enriched_invalid, all_valid_false = validate_and_enrich_citations(invalid_report, context)
    assert all_valid_false is False
    assert enriched_invalid.needs[0].sources[0].valid is False


@pytest.mark.asyncio
async def test_skills_service_builtin_seeding(db_session: AsyncSession) -> None:
    """Test seeding built-in skills and querying them."""
    service = SkillService(db_session)
    await service.seed_builtin_skills()

    analyzer = await service.get_skill_by_slug("client-needs-analyzer")
    assert analyzer is not None
    assert analyzer.name == "Client Needs Analyzer"
    assert analyzer.workspace_id is None

    scope_detector = await service.get_skill_by_slug("scope-change-detector")
    assert scope_detector is not None
    assert scope_detector.name == "Scope Change Detector"


async def _create_db_workspace(db_session: AsyncSession, name: str) -> tuple[User, Workspace]:
    user = User(
        email=f"owner_{uuid.uuid4().hex[:8]}@example.com",
        name="Test Owner",
        hashed_password="fake_hashed_pw",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    ws_slug = f"ws-{uuid.uuid4().hex[:8]}"
    workspace = Workspace(name=name, slug=ws_slug, owner_id=user.id)
    db_session.add(workspace)
    await db_session.flush()
    return user, workspace


@pytest.mark.asyncio
async def test_skills_service_workspace_custom_skill(db_session: AsyncSession) -> None:
    """Test custom skill creation and update in a workspace."""
    service = SkillService(db_session)
    await service.seed_builtin_skills()

    _, workspace = await _create_db_workspace(db_session, "Skill WS")

    # Create custom skill
    custom_slug = f"custom-sprint-{uuid.uuid4().hex[:6]}"
    custom_skill = await service.create_skill(
        workspace.id,
        SkillCreate(
            name="Custom Sprint Auditor",
            slug=custom_slug,
            description="Audits sprint tasks",
            prompt_template="Analyze tasks for {{client_name}}",
        ),
    )
    assert custom_skill.id is not None
    assert custom_skill.workspace_id == workspace.id

    # List skills for workspace should include built-ins + custom skill
    skills = await service.list_skills(workspace.id)
    slugs = {s.slug for s in skills}
    assert "client-needs-analyzer" in slugs
    assert "scope-change-detector" in slugs
    assert custom_slug in slugs


@pytest.mark.asyncio
async def test_run_service_create_and_execute(db_session: AsyncSession) -> None:
    """Test complete Run execution workflow with mocked LLM output and insight persistence."""
    skill_service = SkillService(db_session)
    await skill_service.seed_builtin_skills()
    skill = await skill_service.get_skill_by_slug("client-needs-analyzer")
    assert skill is not None

    user, workspace = await _create_db_workspace(db_session, "Run Test WS")

    run_service = RunService(db_session)
    run = await run_service.create_run(
        workspace_id=workspace.id,
        user_id=user.id,
        request=RunCreateRequest(skill_id=skill.id),
    )
    assert run.status == "pending"

    # Mock LLM provider to return structured ClientNeedsReport
    mock_report = ClientNeedsReport(
        client_name="Test Client",
        executive_summary="Summary of findings",
        needs=[
            NeedInsight(
                text="Require SSO login",
                priority="high",
                sources=[],
            )
        ],
        patterns=[
            PatternInsight(
                text="Daily deployment cadence",
                sources=[],
            )
        ],
        stakeholders=[
            StakeholderInsight(
                name="John Doe",
                role="Product Owner",
                sources=[],
            )
        ],
        risks=[
            RiskInsight(
                text="Database migration delay",
                severity="medium",
                sources=[],
            )
        ],
    )
    mock_llm_result = LLMResult(
        content=mock_report.model_dump_json(),
        prompt_tokens=150,
        completion_tokens=80,
        total_tokens=230,
        cost_usd=0.000035,
        model="gemini-2.5-flash",
        provider="gemini",
    )

    with patch("app.modules.runs.service.get_llm_provider") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.generate_structured.return_value = (mock_report, mock_llm_result)
        mock_get_provider.return_value = mock_provider

        executed_run = await run_service.execute_run(run.id)
        assert executed_run.status == "completed"
        assert executed_run.tokens_in == 150
        assert executed_run.tokens_out == 80
        assert executed_run.cost_usd == 0.000035
        assert executed_run.completed_at is not None

        # Verify insights were created in DB
        fetched_run = await run_service.get_run(run.id, workspace.id)
        assert len(fetched_run.insights) == 4
        categories = {i.category for i in fetched_run.insights}
        assert categories == {"need", "pattern", "stakeholder", "risk"}

        # Test insight feedback
        insight = fetched_run.insights[0]
        updated_insight = await run_service.submit_insight_feedback(
            insight_id=insight.id,
            workspace_id=workspace.id,
            feedback="thumbs_up",
            notes="Very accurate insight",
        )
        assert updated_insight.feedback == "thumbs_up"
        assert updated_insight.feedback_notes == "Very accurate insight"


@pytest.mark.asyncio
async def test_skills_and_runs_api_workflow(async_client: AsyncClient) -> None:
    """Test full HTTP API endpoints for /skills and /runs."""
    _, workspace_id = await _create_user_and_workspace(async_client)

    # 1. GET /api/v1/skills (built-in skills should be listed)
    skills_resp = await async_client.get("/api/v1/skills")
    assert skills_resp.status_code == 200
    skills = skills_resp.json()
    assert len(skills) >= 2
    slugs = [s["slug"] for s in skills]
    assert "client-needs-analyzer" in slugs

    analyzer_skill = next(s for s in skills if s["slug"] == "client-needs-analyzer")
    skill_id = analyzer_skill["id"]

    # 2. POST /api/v1/runs with execute_async=False (synchronous mock execution)
    mock_report = ClientNeedsReport(
        client_name="API Client",
        executive_summary="API summary",
        needs=[],
        patterns=[],
        stakeholders=[],
        risks=[],
    )
    mock_llm_result = LLMResult(
        content=mock_report.model_dump_json(),
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.000022,
        model="gemini-2.5-flash",
        provider="gemini",
    )

    with patch("app.modules.runs.service.get_llm_provider") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.generate_structured.return_value = (mock_report, mock_llm_result)
        mock_get_provider.return_value = mock_provider

        create_run_resp = await async_client.post(
            "/api/v1/runs?execute_async=false",
            json={"skill_id": skill_id, "trigger": "manual"},
        )
        assert create_run_resp.status_code == 201
        run_data = create_run_resp.json()
        assert run_data["status"] == "completed"
        assert run_data["tokens_in"] == 100
        run_id = run_data["id"]

        # 3. GET /api/v1/runs
        list_resp = await async_client.get("/api/v1/runs")
        assert list_resp.status_code == 200
        runs_list = list_resp.json()
        assert any(r["id"] == run_id for r in runs_list)

        # 4. GET /api/v1/runs/{run_id}
        detail_resp = await async_client.get(f"/api/v1/runs/{run_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["id"] == run_id
        assert detail_data["output_json"] is not None
