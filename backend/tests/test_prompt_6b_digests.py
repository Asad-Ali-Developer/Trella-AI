"""Tests for Phase 6b prompt hardening, citation retry, map-reduce digests, and native schema."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.core.config import settings
from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.llm.base import LLMResult
from app.modules.llm.gemini import GEMINI_API_BASE, GeminiProvider
from app.modules.runs.models import ClientDigest
from app.modules.runs.report_schemas import ClientNeedsReportV2, Headline, Health
from app.modules.runs.schemas import RunCreateRequest
from app.modules.runs.service import RunService
from app.modules.skills.models import Skill
from app.modules.skills.schemas import CitedSource, NeedInsight
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientRecord,
    TrelloSource,
)
from app.modules.workspaces.models import Workspace


async def _setup_workspace(
    db: AsyncSession, name: str = "Test WS"
) -> tuple[Workspace, Skill, TrelloClientRecord, TrelloSource, User]:
    user = User(
        email=f"user_{uuid.uuid4().hex[:6]}@example.com",
        name="Tester",
        hashed_password="pw",
    )
    db.add(user)
    await db.flush()

    workspace = Workspace(
        name=name,
        slug=f"ws-{uuid.uuid4().hex[:6]}",
        owner_id=user.id,
    )
    db.add(workspace)
    await db.flush()

    connection = await ConnectionRepository(db).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="trello",
        user_id=user.id,
        encrypted_token=f"token-{workspace.id}",
        external_account_id=f"acc-{workspace.id}",
        external_username=f"user-{workspace.id}",
    )

    source = TrelloSource(
        workspace_id=workspace.id,
        connection_id=connection.id,
        trello_board_id=f"board_{uuid.uuid4().hex[:6]}",
        name="Board",
        url="https://trello.com/b/test",
        excluded=False,
    )
    db.add(source)
    await db.flush()

    client = TrelloClientRecord(workspace_id=workspace.id, name=f"Client-{uuid.uuid4().hex[:4]}")
    db.add(client)
    await db.flush()

    skill = Skill(
        workspace_id=workspace.id,
        name="Needs Analyzer",
        slug=f"skill-{uuid.uuid4().hex[:6]}",
        version=1,
        prompt_template="Analyze client {{client_name}} context.",
        scope_json={
            "sources": ["board:*"],
            "clients": "all",
            "include": ["cards", "comments"],
            "date_range": "all",
        },
        output_schema_json={"needs": []},
        model_config_json={"provider": "gemini", "model": "gemini-3-flash-preview"},
    )
    db.add(skill)
    await db.flush()
    return workspace, skill, client, source, user


def _make_report(cited_ids: list[str]) -> ClientNeedsReportV2:
    needs = [
        NeedInsight(
            text=f"Need citing {cid}",
            priority="high",
            sources=[CitedSource(source_id=cid, source_type="card", title="Title", valid=True)],
        )
        for cid in cited_ids
    ]
    return ClientNeedsReportV2(
        headline=Headline(
            status_word="stable",
            status_word_tone="positive",
            rest=".",
            summary="Client summary.",
        ),
        health=Health(status="green", confidence="high"),
        needs=needs,
        patterns=[],
        stakeholders=[],
        risks=[],
    )


# ---------------------------------------------------------------------------
# 1. Citation retry triggers once and strips
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_citation_retry_triggers_once_and_strips(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_workspace(db_session)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card-real-123",
        name="Real Feature Card",
        description="Working on auth.",
        list_id="l1",
        content_hash="h1",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)
    req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, req)

    call_count = 0
    corrective_instruction_seen = False

    async def _mock_generate_structured(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
        nonlocal call_count, corrective_instruction_seen
        call_count += 1
        prompt = kwargs.get("prompt", "")
        if "CORRECTIVE INSTRUCTION" in prompt:
            corrective_instruction_seen = True
            # Second call adheres to valid IDs, plus 1 invalid that will be stripped
            report = _make_report(["card-real-123"] * 5 + ["card-hallucinated-strip"])
        else:
            # First call has > 20% invalid citations (e.g. 100% invalid)
            report = _make_report(["hallucinated-1", "hallucinated-2", "hallucinated-3"])

        res = LLMResult(
            content=report.model_dump_json(),
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            model="gemini",
            provider="gemini",
        )
        return report, res

    with (
        patch("app.core.config.settings.RUN_PIPELINE", "scoped"),
        patch("app.core.config.settings.RUN_CITATION_INVALID_RATIO", 0.2),
        patch(
            "app.modules.llm.gemini.GeminiProvider.generate_structured",
            side_effect=_mock_generate_structured,
        ),
    ):
        executed_run = await run_svc.execute_run(run.id)

    assert executed_run.status == "completed"
    assert call_count == 2
    assert corrective_instruction_seen is True

    output = executed_run.output_json or {}
    meta = output.get("_meta", {})
    citation_retry = meta.get("citation_retry", {})
    assert citation_retry.get("retried") is True
    assert citation_retry.get("retry_count") == 1
    assert citation_retry.get("stripped_count") >= 1
    assert meta.get("retry_count") == 1
    assert meta.get("stripped_count") >= 1

    # Invalid item was stripped, valid kept
    needs = output.get("needs", [])
    assert len(needs) == 5
    for n in needs:
        assert n["sources"][0]["source_id"] == "card-real-123"


# ---------------------------------------------------------------------------
# 2. Run fails when still invalid
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_fails_when_still_invalid(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_workspace(db_session)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card-real-456",
        name="Card",
        description="Desc",
        list_id="l1",
        content_hash="h2",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)
    req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, req)

    call_count = 0

    async def _mock_generate_structured(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
        nonlocal call_count
        call_count += 1
        # Both calls return invalid citations > threshold (100% invalid)
        report = _make_report(["hallucinated-x", "hallucinated-y"])
        res = LLMResult(
            content=report.model_dump_json(),
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            model="gemini",
            provider="gemini",
        )
        return report, res

    with (
        patch("app.core.config.settings.RUN_PIPELINE", "scoped"),
        patch("app.core.config.settings.RUN_CITATION_INVALID_RATIO", 0.2),
        patch(
            "app.modules.llm.gemini.GeminiProvider.generate_structured",
            side_effect=_mock_generate_structured,
        ),
    ):
        executed_run = await run_svc.execute_run(run.id)

    assert executed_run.status == "failed"
    assert call_count == 2
    assert "Citation validation failed" in (executed_run.error or "")
    meta = (executed_run.output_json or {}).get("_meta", {})
    assert meta.get("retry_count") == 1


# ---------------------------------------------------------------------------
# 3. Digest cache hit avoids a second LLM call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_digest_cache_hit_avoids_a_second_llm_call(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_workspace(db_session)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card-digest-test",
        name="Big Digest Work Item",
        description="Detailed description for client work.",
        list_id="l1",
        content_hash="hash-digest-1",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)
    digest_generate_calls = 0

    async def _mock_generate(*args: Any, **kwargs: Any) -> LLMResult:
        nonlocal digest_generate_calls
        digest_generate_calls += 1
        return LLMResult(
            content="Dense summary of client activity.",
            prompt_tokens=80,
            completion_tokens=40,
            total_tokens=120,
            cost_usd=0.0005,
            model="gemini",
            provider="gemini",
        )

    async def _mock_generate_structured(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
        report = _make_report(["card-digest-test"])
        res = LLMResult(
            content=report.model_dump_json(),
            prompt_tokens=150,
            completion_tokens=60,
            total_tokens=210,
            cost_usd=0.001,
            model="gemini",
            provider="gemini",
        )
        return report, res

    with (
        patch("app.core.config.settings.RUN_PIPELINE", "scoped"),
        patch("app.core.config.settings.RUN_DIGEST_THRESHOLD_TOKENS", 10),  # Force digest path
        patch("app.modules.llm.gemini.GeminiProvider.generate", side_effect=_mock_generate),
        patch("app.modules.llm.gemini.GeminiProvider.generate_structured", side_effect=_mock_generate_structured),
    ):
        # Run 1: Cache miss, calls LLM for digest
        run1 = await run_svc.create_run(workspace.id, None, RunCreateRequest(skill_id=skill.id, client_id=client.id))
        exec1 = await run_svc.execute_run(run1.id)
        assert exec1.status == "completed"
        assert digest_generate_calls == 1
        assert (exec1.output_json or {}).get("_meta", {}).get("digest_cache_misses") == 1

        # Check record in client_digests table
        cd_res = await db_session.scalars(select(ClientDigest).where(ClientDigest.workspace_id == workspace.id))
        digests = list(cd_res.all())
        assert len(digests) == 1
        assert digests[0].client_id == client.id

        # Run 2: Same input context, MUST hit cache and avoid LLM call for digest
        run2 = await run_svc.create_run(workspace.id, None, RunCreateRequest(skill_id=skill.id, client_id=client.id))
        exec2 = await run_svc.execute_run(run2.id)
        assert exec2.status == "completed"
        assert digest_generate_calls == 1  # No additional generate call!
        assert (exec2.output_json or {}).get("_meta", {}).get("digest_cache_hits") == 1


# ---------------------------------------------------------------------------
# 4. Digest path only above threshold
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_digest_path_only_above_threshold(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_workspace(db_session)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card-threshold-check",
        name="Small Item",
        description="Just a few tokens.",
        list_id="l1",
        content_hash="h-thresh",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)

    async def _mock_generate_structured(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
        report = _make_report(["card-threshold-check"])
        res = LLMResult(
            content=report.model_dump_json(),
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            model="gemini",
            provider="gemini",
        )
        return report, res

    with (
        patch("app.core.config.settings.RUN_PIPELINE", "scoped"),
        patch(
            "app.modules.llm.gemini.GeminiProvider.generate_structured",
            side_effect=_mock_generate_structured,
        ),
    ):
        # Case A: Below threshold (default 40000)
        with patch("app.core.config.settings.RUN_DIGEST_THRESHOLD_TOKENS", 40000):
            run_below = await run_svc.create_run(workspace.id, None, RunCreateRequest(skill_id=skill.id, client_id=client.id))
            exec_below = await run_svc.execute_run(run_below.id)
            meta_below = (exec_below.output_json or {}).get("_meta", {})
            assert meta_below.get("digest_path") is not True

        # Case B: Above threshold (forced low to 5)
        with (
            patch("app.core.config.settings.RUN_DIGEST_THRESHOLD_TOKENS", 5),
            patch("app.modules.llm.gemini.GeminiProvider.generate", new=AsyncMock(return_value=LLMResult(
                content="Digest above threshold",
                prompt_tokens=50,
                completion_tokens=20,
                total_tokens=70,
                cost_usd=0.0002,
                model="gemini",
                provider="gemini",
            ))),
        ):
            run_above = await run_svc.create_run(workspace.id, None, RunCreateRequest(skill_id=skill.id, client_id=client.id))
            exec_above = await run_svc.execute_run(run_above.id)
            meta_above = (exec_above.output_json or {}).get("_meta", {})
            assert meta_above.get("digest_path") is True


# ---------------------------------------------------------------------------
# 5. Citations validate for excerpts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_citations_validate_for_excerpts(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_workspace(db_session)
    card1 = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card-excerpt-active",
        name="Active Card in Excerpt",
        description="Detailed description for active work.",
        list_id="l1",
        content_hash="h-excerpt-1",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card1)
    await db_session.commit()

    run_svc = RunService(db_session)

    async def _mock_generate(*args: Any, **kwargs: Any) -> LLMResult:
        return LLMResult(
            content="Client high-level digest.",
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
            cost_usd=0.0002,
            model="gemini",
            provider="gemini",
        )

    async def _mock_generate_structured(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
        # Citing the raw excerpt card
        report = _make_report(["card-excerpt-active"])
        res = LLMResult(
            content=report.model_dump_json(),
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            model="gemini",
            provider="gemini",
        )
        return report, res

    with (
        patch("app.core.config.settings.RUN_PIPELINE", "scoped"),
        patch("app.core.config.settings.RUN_DIGEST_THRESHOLD_TOKENS", 10),
        patch("app.modules.llm.gemini.GeminiProvider.generate", side_effect=_mock_generate),
        patch("app.modules.llm.gemini.GeminiProvider.generate_structured", side_effect=_mock_generate_structured),
    ):
        run = await run_svc.create_run(workspace.id, None, RunCreateRequest(skill_id=skill.id, client_id=client.id))
        exec_run = await run_svc.execute_run(run.id)

    assert exec_run.status == "completed"
    assert exec_run.citations_valid is True
    needs = (exec_run.output_json or {}).get("needs", [])
    assert len(needs) == 1
    assert needs[0]["sources"][0]["source_id"] == "card-excerpt-active"
    assert needs[0]["sources"][0]["valid"] is True


# ---------------------------------------------------------------------------
# 6. 429 honors Retry-After
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_429_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MAX_ATTEMPTS", 2)

    recorded_sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        recorded_sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    url = f"{GEMINI_API_BASE}/gemini-3-flash-preview:generateContent"
    # First attempt: 429 with Retry-After: 1.5; Second attempt: 200 OK
    respx.post(url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1.5"}, json={"error": "rate limited"}),
            httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": "Success after backoff"}]}}],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
                },
            ),
        ]
    )

    provider = GeminiProvider(default_model="gemini-3-flash-preview")
    result = await provider.generate(prompt="Hello Gemini")

    assert result.content == "Success after backoff"
    assert 1.5 in [pytest.approx(s) for s in recorded_sleeps]


# ---------------------------------------------------------------------------
# 7. Migration upgrade and downgrade
# ---------------------------------------------------------------------------
def test_migration_upgrade_and_downgrade() -> None:
    alembic_cfg = Config("alembic.ini")
    # Downgrade to prior revision
    command.downgrade(alembic_cfg, "c3d4e5f6a7b8")
    # Upgrade back to head
    command.upgrade(alembic_cfg, "head")


# ---------------------------------------------------------------------------
# 8. Workspace isolation of digests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workspace_isolation_of_digests(db_session: AsyncSession) -> None:
    ws1, skill1, client1, _, _ = await _setup_workspace(db_session, name="Workspace 1")
    ws2, skill2, client2, _, _ = await _setup_workspace(db_session, name="Workspace 2")

    # Insert digest in Workspace 1
    d1 = ClientDigest(
        workspace_id=ws1.id,
        client_id=client1.id,
        period_start=None,
        period_end=None,
        input_hash="shared-hash-xyz",
        model="gemini",
        prompt_version="v1",
        digest="Workspace 1 confidential digest.",
        input_tokens=100,
        output_tokens=50,
    )
    db_session.add(d1)
    await db_session.commit()

    # Query Workspace 2 using Workspace 1's digest criteria
    q_ws2 = select(ClientDigest).where(
        ClientDigest.workspace_id == ws2.id,
        ClientDigest.input_hash == "shared-hash-xyz",
    )
    res_ws2 = await db_session.scalars(q_ws2)
    assert res_ws2.first() is None, "Digest from Workspace 1 leaked into Workspace 2!"

    # Token counts property test
    assert d1.token_counts == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}


# ---------------------------------------------------------------------------
# 9. Legacy path untouched
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_legacy_path_untouched(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_workspace(db_session)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="legacy-card",
        name="Legacy Card",
        description="Legacy desc",
        list_id="l1",
        content_hash="h-legacy",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)
    req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, req)

    async def _mock_legacy_gen(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
        # Return 100% invalid citations to ensure legacy path does NOT fail or retry
        report = _make_report(["hallucinated-legacy-id"])
        res = LLMResult(
            content=report.model_dump_json(),
            prompt_tokens=80,
            completion_tokens=40,
            total_tokens=120,
            cost_usd=0.0008,
            model="gemini",
            provider="gemini",
        )
        return report, res

    with (
        patch("app.core.config.settings.RUN_PIPELINE", "legacy"),
        patch("app.core.config.settings.RUN_CITATION_INVALID_RATIO", 0.2),
        patch("app.core.config.settings.RUN_DIGEST_THRESHOLD_TOKENS", 5),
        patch(
            "app.modules.llm.gemini.GeminiProvider.generate_structured",
            side_effect=_mock_legacy_gen,
        ),
    ):
        executed_run = await run_svc.execute_run(run.id)

    # Legacy path completes (does not fail even with invalid citations), strips invalid
    assert executed_run.status == "completed"
    output = executed_run.output_json or {}
    meta = output.get("_meta", {})
    # Legacy does not add _meta.budget or _meta.citation_retry or digest_path
    assert "budget" not in meta
    assert "citation_retry" not in meta
    assert "digest_path" not in meta
    # Legacy stats include real item counts
    stats = output.get("stats", {})
    assert "card_count" in stats
    assert "comment_count" in stats
    assert "commit_count" in stats


# ---------------------------------------------------------------------------
# 10. Fail-soft Native Schema on HTTP 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_gemini_native_schema_fail_soft_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_NATIVE_SCHEMA", True)

    url = f"{GEMINI_API_BASE}/gemini-3-flash-preview:generateContent"
    valid_report = _make_report(["c1"])

    call_records: list[dict[str, Any]] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        call_records.append(body)
        gen_cfg = body.get("generationConfig", {})
        if "responseSchema" in gen_cfg:
            # Reject native schema with HTTP 400
            return httpx.Response(400, json={"error": {"message": "Invalid responseSchema"}})
        # Succeed on retry without responseSchema
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": valid_report.model_dump_json()}]}}],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 15},
            },
        )

    respx.post(url).mock(side_effect=mock_handler)

    provider = GeminiProvider(default_model="gemini-3-flash-preview")
    parsed, res = await provider.generate_structured(
        prompt="Generate report",
        response_schema=ClientNeedsReportV2,
    )

    assert parsed.headline.status_word == "stable"
    assert len(call_records) == 2
    assert "responseSchema" in call_records[0]["generationConfig"]
    assert "responseSchema" not in call_records[1]["generationConfig"]
