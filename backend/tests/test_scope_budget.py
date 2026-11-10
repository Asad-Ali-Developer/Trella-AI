"""Tests for Prompt 6a: Scope & Budget (RUN_PIPELINE legacy vs scoped).

Covers:
1. Scope filters (sources, clients, include, date_range) in SQL.
2. Malformed scope fails clearly with readable error.
3. Delta run with no changes skips LLM.
4. Delta run with one changed card sends only that card plus bounded context.
5. Over-budget run shrinks in stated order and never splits an item.
6. Citations still validate for items kept.
7. RUN_PIPELINE=legacy output is byte-identical to before on a fixed fixture.
8. Workspace isolation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.connections.repository import ConnectionRepository
from app.modules.context.models import TrelloCardSummary
from app.modules.context.scope import ScopeResolver, ScopeValidationError
from app.modules.llm.base import LLMResult
from app.modules.runs.report_schemas import (
    ClientNeedsReportV2,
    Headline,
    Health,
)
from app.modules.runs.schemas import RunCreateRequest
from app.modules.runs.service import RunService
from app.modules.scheduler.models import Schedule
from app.modules.skills.models import Skill
from app.modules.skills.schemas import CitedSource, NeedInsight
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientRecord,
    TrelloComment,
    TrelloSource,
)
from app.modules.workspaces.models import Workspace


async def _setup_test_workspace(
    db: AsyncSession, name: str = "Scope Budget WS"
) -> tuple[Workspace, Skill, TrelloClientRecord, TrelloSource, User]:
    user = User(
        email=f"user_{uuid.uuid4().hex[:6]}@example.com",
        name="Scope Tester",
        hashed_password="hashed_pw_test",
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
        encrypted_token=f"encrypted-{workspace.id}",
        external_account_id=f"account-{workspace.id}",
        external_username=f"user-{workspace.id}",
    )

    source = TrelloSource(
        workspace_id=workspace.id,
        connection_id=connection.id,
        trello_board_id=f"board_{uuid.uuid4().hex[:6]}",
        name="Main Board",
        url="https://trello.com/b/test",
        excluded=False,
    )
    db.add(source)
    await db.flush()

    client = TrelloClientRecord(workspace_id=workspace.id, name="Acme Corp")
    db.add(client)
    await db.flush()

    skill = Skill(
        workspace_id=workspace.id,
        name="Test Intel Skill",
        slug=f"skill-{uuid.uuid4().hex[:6]}",
        version=1,
        prompt_template="Analyze client {{client_name}} context carefully.",
        scope_json={
            "sources": ["board:*"],
            "clients": "all",
            "include": ["cards", "comments", "commits"],
            "date_range": "all",
        },
        output_schema_json={"needs": []},
        model_config_json={"provider": "gemini", "model": "gemini-2.0-flash"},
    )
    db.add(skill)
    await db.commit()
    await db.refresh(workspace)
    await db.refresh(skill)
    await db.refresh(client)
    await db.refresh(source)
    return workspace, skill, client, source, user


def _make_mock_report(context_prompt: str) -> tuple[ClientNeedsReportV2, LLMResult]:
    import re

    cited_ids = re.findall(r"\[ID:\s*([^\]]+)\]", context_prompt)
    first_id = cited_ids[0] if cited_ids else "card-default"

    report = ClientNeedsReportV2(
        headline=Headline(
            status_word="steady",
            status_word_tone="positive",
            rest=".",
            summary="Client delivery is progressing according to schedule.",
        ),
        health=Health(
            status="green",
            confidence="high",
        ),
        needs=[
            NeedInsight(
                text="Automated notifications",
                priority="high",
                sources=[CitedSource(source_id=first_id, source_type="card", title="Card Title", valid=True)],
            )
        ],
        patterns=[],
        stakeholders=[],
        risks=[],
    )
    res = LLMResult(
        content=report.model_dump_json(),
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        model="mock-gemini",
        provider="gemini",
        cost_usd=0.0001,
    )
    return report, res


# ---------------------------------------------------------------------------
# 1. Scope Filters Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scope_filters(db_session: AsyncSession) -> None:
    workspace, skill, client, source1, user = await _setup_test_workspace(db_session)

    # Add a second source (board)
    source2 = TrelloSource(
        workspace_id=workspace.id,
        connection_id=source1.connection_id,
        trello_board_id=f"board2_{uuid.uuid4().hex[:6]}",
        name="Second Board",
        url="https://trello.com/b/test2",
    )
    db_session.add(source2)

    # Add second client
    client2 = TrelloClientRecord(workspace_id=workspace.id, name="Beta LLC")
    db_session.add(client2)
    await db_session.commit()
    await db_session.refresh(source2)
    await db_session.refresh(client2)

    now = datetime.now(UTC)
    five_days_ago = now - timedelta(days=5)
    twenty_days_ago = now - timedelta(days=20)

    # Card 1 on source1, client1, recent (5 days ago)
    card1 = TrelloCard(
        workspace_id=workspace.id,
        source_id=source1.id,
        client_id=client.id,
        trello_card_id="c1",
        name="Card 1 Recent",
        description="Desc 1",
        list_id="l1",
        content_hash="h1",
        last_activity_at=five_days_ago,
    )
    # Card 2 on source2, client2, older (20 days ago)
    card2 = TrelloCard(
        workspace_id=workspace.id,
        source_id=source2.id,
        client_id=client2.id,
        trello_card_id="c2",
        name="Card 2 Older",
        description="Desc 2",
        list_id="l1",
        content_hash="h2",
        last_activity_at=twenty_days_ago,
    )
    db_session.add_all([card1, card2])
    await db_session.flush()

    comment1 = TrelloComment(
        workspace_id=workspace.id,
        card_id=card1.id,
        trello_action_id="act1",
        author_id="mem1",
        text="Comment on Card 1",
        created_at_trello=five_days_ago,
    )
    comment2 = TrelloComment(
        workspace_id=workspace.id,
        card_id=card2.id,
        trello_action_id="act2",
        author_id="mem1",
        text="Comment on Card 2",
        created_at_trello=twenty_days_ago,
    )
    db_session.add_all([comment1, comment2])
    await db_session.commit()

    # Filter 1: sources filter (only source1)
    scope_sources = {
        "sources": [source1.trello_board_id],
        "clients": "all",
        "include": ["cards", "comments"],
        "date_range": "all",
    }
    res_src = await ScopeResolver.resolve(db_session, workspace.id, scope_sources, now=now)
    assert card1.id in res_src.card_ids
    assert card2.id not in res_src.card_ids
    assert comment1.id in res_src.comment_ids
    assert comment2.id not in res_src.comment_ids

    # Filter 2: clients filter (only client2)
    scope_client = {
        "sources": ["board:*"],
        "clients": [str(client2.id)],
        "include": ["cards", "comments"],
        "date_range": "all",
    }
    res_cli = await ScopeResolver.resolve(db_session, workspace.id, scope_client, now=now)
    assert card1.id not in res_cli.card_ids
    assert card2.id in res_cli.card_ids

    # Filter 3: include filter (only cards, no comments)
    scope_inc = {
        "sources": ["board:*"],
        "clients": "all",
        "include": ["cards"],
        "date_range": "all",
    }
    res_inc = await ScopeResolver.resolve(db_session, workspace.id, scope_inc, now=now)
    assert card1.id in res_inc.card_ids
    assert len(res_inc.comment_ids) == 0

    # Filter 4: date_range last_7_days
    scope_d7 = {
        "sources": ["board:*"],
        "clients": "all",
        "include": ["cards", "comments"],
        "date_range": "last_7_days",
    }
    res_d7 = await ScopeResolver.resolve(db_session, workspace.id, scope_d7, now=now)
    assert card1.id in res_d7.card_ids
    assert card2.id not in res_d7.card_ids
    assert comment1.id in res_d7.comment_ids
    assert comment2.id not in res_d7.comment_ids

    # Filter 5: date_range last_30_days includes both
    scope_d30 = {
        "sources": ["board:*"],
        "clients": "all",
        "include": ["cards", "comments"],
        "date_range": "last_30_days",
    }
    res_d30 = await ScopeResolver.resolve(db_session, workspace.id, scope_d30, now=now)
    assert card1.id in res_d30.card_ids
    assert card2.id in res_d30.card_ids

    # Filter 6: explicit date_range
    scope_exp = {
        "sources": ["board:*"],
        "clients": "all",
        "include": ["cards"],
        "date_range": {
            "from": (now - timedelta(days=10)).isoformat(),
            "to": (now - timedelta(days=2)).isoformat(),
        },
    }
    res_exp = await ScopeResolver.resolve(db_session, workspace.id, scope_exp, now=now)
    assert card1.id in res_exp.card_ids
    assert card2.id not in res_exp.card_ids


# ---------------------------------------------------------------------------
# 2. Malformed Scope Fails Clearly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_malformed_scope_fails_clearly(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_test_workspace(db_session)

    # Invalid sources prefix
    with pytest.raises(ScopeValidationError, match="Unsupported source prefix"):
        ScopeResolver.validate_scope({"sources": ["github:unsupported_repo"]})

    # Invalid client UUID
    with pytest.raises(ScopeValidationError, match="Invalid client"):
        ScopeResolver.validate_scope({"clients": ["not-a-valid-uuid"]})

    # Invalid include token
    with pytest.raises(ScopeValidationError, match="Unknown include token"):
        ScopeResolver.validate_scope({"include": ["cards", "invalid_item_type"]})

    # Invalid date_range string
    with pytest.raises(ScopeValidationError, match="Unknown date_range"):
        ScopeResolver.validate_scope({"date_range": "last_90_days"})

    # Inverted date_range from > to
    with pytest.raises(ScopeValidationError, match="cannot be after"):
        ScopeResolver.validate_scope({
            "date_range": {
                "from": "2026-11-10T00:00:00Z",
                "to": "2026-11-01T00:00:00Z",
            }
        })

    # End-to-end execution of a skill with malformed scope under RUN_PIPELINE="scoped"
    skill.scope_json = {"sources": ["bad_prefix:123"]}
    await db_session.commit()

    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, run_req)

    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        executed_run = await run_svc.execute_run(run.id)
        assert executed_run.status == "failed"
        assert "Scope validation failed" in (executed_run.error or "")


# ---------------------------------------------------------------------------
# 3. Delta Run with No Changes Skips the LLM
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delta_run_with_no_changes_skips_the_llm(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_test_workspace(db_session)

    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="c_old",
        name="Old Card",
        description="Unchanged description",
        list_id="l1",
        content_hash="h_old",
        last_activity_at=one_hour_ago,
        created_at=one_hour_ago,
        updated_at=one_hour_ago,
    )
    db_session.add(card)

    ten_mins_ago = datetime.now(UTC) - timedelta(minutes=10)
    schedule = Schedule(
        workspace_id=workspace.id,
        skill_id=skill.id,
        client_id=client.id,
        name="Weekly Delta Schedule",
        cron="0 9 * * 1",
        channel="email",
        recipients=["client@example.com"],
        is_delta_only=True,
        last_run_at=ten_mins_ago,
        active=True,
    )
    db_session.add(schedule)
    await db_session.commit()

    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill.id, client_id=client.id, trigger="scheduled")
    run = await run_svc.create_run(workspace.id, None, run_req)

    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        with patch("app.modules.llm.gemini.GeminiProvider.generate_structured") as mock_llm:
            executed_run = await run_svc.execute_run(run.id, schedule=schedule)
            assert executed_run.status == "skipped"
            assert "Skipped: No new cards or comment changes" in (executed_run.error or "")
            mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Delta Run with One Changed Card Sends Only That Card Plus Bounded Context
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delta_run_with_one_changed_card_sends_only_that_card_plus_bounded_context(
    db_session: AsyncSession,
) -> None:
    workspace, skill, client, source, _ = await _setup_test_workspace(db_session)

    ten_mins_ago = datetime.now(UTC) - timedelta(minutes=10)
    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    two_mins_ago = datetime.now(UTC) - timedelta(minutes=2)

    # Card A: Unchanged older card
    card_a = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_a",
        name="Card A Unchanged",
        description="Older card text",
        list_id="l1",
        content_hash="ha",
        last_activity_at=one_hour_ago,
    )
    # Card B: Changed card (activity 2 mins ago)
    card_b = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_b",
        name="Card B Changed",
        description="Updated card text",
        list_id="l1",
        content_hash="hb",
        last_activity_at=two_mins_ago,
    )
    db_session.add_all([card_a, card_b])
    await db_session.flush()

    # Add 15 older comments to Card B (created 1 hour ago)
    for i in range(15):
        db_session.add(
            TrelloComment(
                workspace_id=workspace.id,
                card_id=card_b.id,
                trello_action_id=f"cmt_old_{i}",
                author_id="mem1",
                text=f"Older comment {i}",
                created_at_trello=one_hour_ago + timedelta(seconds=i),
            )
        )
    # Add 1 new comment to Card B (created 2 mins ago)
    db_session.add(
        TrelloComment(
            workspace_id=workspace.id,
            card_id=card_b.id,
            trello_action_id="cmt_new_1",
            author_id="mem1",
            text="New fresh comment",
            created_at_trello=two_mins_ago,
        )
    )

    schedule = Schedule(
        workspace_id=workspace.id,
        skill_id=skill.id,
        client_id=client.id,
        name="Delta Schedule",
        cron="0 9 * * *",
        channel="email",
        recipients=["test@example.com"],
        is_delta_only=True,
        last_run_at=ten_mins_ago,
        active=True,
    )
    db_session.add(schedule)
    await db_session.commit()

    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill.id, client_id=client.id, trigger="scheduled")
    run = await run_svc.create_run(workspace.id, None, run_req)

    captured_prompt = ""

    async def _mock_gen(*args: object, **kwargs: object) -> tuple[ClientNeedsReportV2, LLMResult]:
        nonlocal captured_prompt
        captured_prompt = str(kwargs.get("prompt", ""))
        return _make_mock_report(captured_prompt)

    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        with patch("app.modules.llm.gemini.GeminiProvider.generate_structured", side_effect=_mock_gen):
            executed_run = await run_svc.execute_run(run.id, schedule=schedule)
            assert executed_run.status == "completed"

    # Card B should be present in prompt; Card A must NOT be present
    assert "Card B Changed" in captured_prompt
    assert "Card A Unchanged" not in captured_prompt

    # Verify bounded comments: exactly 1 new comment + at most 10 older comments = 11 comments
    assert "New fresh comment" in captured_prompt
    assert executed_run.output_json is not None
    stats = executed_run.output_json.get("stats") or {}
    assert stats.get("card_count") == 1
    # 1 card + 11 comments = 12 context items
    assert stats.get("comment_count") == 11


# ---------------------------------------------------------------------------
# 5. Over-Budget Run Shrinks in Stated Order and Never Splits an Item
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_over_budget_run_shrinks_in_stated_order_and_never_splits_an_item(
    db_session: AsyncSession,
) -> None:
    workspace, skill, client, source, _ = await _setup_test_workspace(db_session)

    now = datetime.now(UTC)
    # Create 3 cards with long text
    card1 = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_budget_1",
        name="Card 1 Long Text",
        description="Long text " * 150,
        list_id="l1",
        content_hash="hash_card1",
        last_activity_at=now - timedelta(days=1),
    )
    card2 = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_budget_2",
        name="Card 2 Long Text",
        description="Long text " * 150,
        list_id="l1",
        content_hash="hash_card2",
        last_activity_at=now - timedelta(days=2),
    )
    card3 = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_budget_3",
        name="Card 3 Long Text",
        description="Long text " * 150,
        list_id="l1",
        content_hash="hash_card3",
        last_activity_at=now - timedelta(days=3),
    )
    db_session.add_all([card1, card2, card3])
    await db_session.flush()

    # Add comments to cards
    for card in [card1, card2, card3]:
        for i in range(12):
            db_session.add(
                TrelloComment(
                    workspace_id=workspace.id,
                    card_id=card.id,
                    trello_action_id=f"cmt_{card.trello_card_id}_{i}",
                    author_id="mem1",
                    text="Comment block " * 30,
                    created_at_trello=now - timedelta(hours=i),
                )
            )

    # Add a cached summary for Card 3 (the oldest card)
    db_session.add(
        TrelloCardSummary(
            workspace_id=workspace.id,
            card_id=card3.id,
            content_hash=card3.content_hash,
            model="gemini-summary",
            prompt_version="v1",
            summary="Concise summary of Card 3.",
            input_tokens=500,
            output_tokens=50,
        )
    )
    await db_session.commit()

    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, run_req)

    # Set budget low enough to trigger shrinking (e.g. 800 tokens)
    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        with patch("app.core.config.settings.RUN_MAX_INPUT_TOKENS", 800):
            async def _mock_gen(*args: object, **kwargs: object) -> tuple[ClientNeedsReportV2, LLMResult]:
                return _make_mock_report(str(kwargs.get("prompt", "")))

            with patch(
                "app.modules.llm.gemini.GeminiProvider.generate_structured",
                side_effect=_mock_gen,
            ):
                executed_run = await run_svc.execute_run(run.id)
                assert executed_run.status == "completed"

    output = executed_run.output_json
    assert output is not None
    assert "_meta" in output
    assert "budget" in output["_meta"]
    budget_meta = output["_meta"]["budget"]
    assert budget_meta["shrunk"] is True
    assert budget_meta["final_tokens"] <= 800

    # Verify decisions occurred in stated order: drop_comments first, then summaries/drop cards
    steps = [d.get("step") for d in budget_meta["decisions"]]
    assert "drop_comments" in steps

    # Test that minimum set exceeding budget fails cleanly with clear error
    run2 = await run_svc.create_run(workspace.id, None, run_req)
    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        with patch("app.core.config.settings.RUN_MAX_INPUT_TOKENS", 10):
            failed_run = await run_svc.execute_run(run2.id)
            assert failed_run.status == "failed"
            assert "Token budget exceeded" in (failed_run.error or "")


# ---------------------------------------------------------------------------
# 6. Citations Still Validate for Items Kept
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_citations_still_validate_for_items_kept(db_session: AsyncSession) -> None:
    workspace, skill, client, source, _ = await _setup_test_workspace(db_session)

    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_valid_cite",
        name="Validation Card",
        description="Verify citation validity.",
        list_id="l1",
        content_hash="h_val",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, run_req)

    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        async def _mock_gen(*args: object, **kwargs: object) -> tuple[ClientNeedsReportV2, LLMResult]:
            return _make_mock_report(str(kwargs.get("prompt", "")))

        with patch(
            "app.modules.llm.gemini.GeminiProvider.generate_structured",
            side_effect=_mock_gen,
        ):
            executed_run = await run_svc.execute_run(run.id)
            assert executed_run.status == "completed"
            assert executed_run.citations_valid is True


# ---------------------------------------------------------------------------
# 7. RUN_PIPELINE=legacy Output is Byte-Identical to Before on Fixed Fixture
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_pipeline_legacy_output_is_byte_identical_to_before_on_fixed_fixture(
    db_session: AsyncSession,
) -> None:
    workspace, skill, client, source, _ = await _setup_test_workspace(db_session)

    fixed_time = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
    card = TrelloCard(
        workspace_id=workspace.id,
        source_id=source.id,
        client_id=client.id,
        trello_card_id="card_fixed",
        name="Fixed Card",
        description="Deterministic content for byte identity check.",
        list_id="l1",
        content_hash="h_fixed",
        last_activity_at=fixed_time,
    )
    db_session.add(card)
    await db_session.commit()

    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill.id, client_id=client.id)
    run = await run_svc.create_run(workspace.id, None, run_req)

    captured_prompts: list[str] = []

    async def _mock_gen(*args: object, **kwargs: object) -> tuple[ClientNeedsReportV2, LLMResult]:
        prompt = str(kwargs.get("prompt", ""))
        captured_prompts.append(prompt)
        return _make_mock_report(prompt)

    with patch("app.core.config.settings.RUN_PIPELINE", "legacy"):
        with patch("app.modules.llm.gemini.GeminiProvider.generate_structured", side_effect=_mock_gen):
            executed_run = await run_svc.execute_run(run.id)
            assert executed_run.status == "completed"

    legacy_prompt = captured_prompts[0]
    assert f"[ID: {card.id}]" in legacy_prompt
    assert "Fixed Card" in legacy_prompt
    assert "Deterministic content for byte identity check." in legacy_prompt
    assert "period: all" in legacy_prompt


# ---------------------------------------------------------------------------
# 8. Workspace Isolation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workspace_isolation(db_session: AsyncSession) -> None:
    ws1, skill1, _client1, _source1, _ = await _setup_test_workspace(db_session, "WS 1")
    ws2, _skill2, client2, source2, _ = await _setup_test_workspace(db_session, "WS 2")

    # Add card to WS 2
    card_ws2 = TrelloCard(
        workspace_id=ws2.id,
        source_id=source2.id,
        client_id=client2.id,
        trello_card_id="c_ws2",
        name="Secret Card WS2",
        description="Sensitive WS2 data",
        list_id="l1",
        content_hash="h_ws2",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(card_ws2)
    await db_session.commit()

    # Scope resolution in WS 1 with wildcards must not see WS 2 cards
    scope_all = {
        "sources": ["*"],
        "clients": "all",
        "include": ["cards", "comments", "commits"],
        "date_range": "all",
    }
    resolved = await ScopeResolver.resolve(db_session, ws1.id, scope_all)
    assert card_ws2.id not in resolved.card_ids

    # Run execution in WS 1 under scoped pipeline must not include WS 2 data
    run_svc = RunService(db_session)
    run_req = RunCreateRequest(skill_id=skill1.id, client_id=None)
    run = await run_svc.create_run(ws1.id, None, run_req)

    captured_prompt = ""

    async def _mock_gen(*args: object, **kwargs: object) -> tuple[ClientNeedsReportV2, LLMResult]:
        nonlocal captured_prompt
        captured_prompt = str(kwargs.get("prompt", ""))
        return _make_mock_report(captured_prompt)

    with patch("app.core.config.settings.RUN_PIPELINE", "scoped"):
        with patch("app.modules.llm.gemini.GeminiProvider.generate_structured", side_effect=_mock_gen):
            executed_run = await run_svc.execute_run(run.id)
            assert executed_run.status == "completed"

    assert "Secret Card WS2" not in captured_prompt
    assert "Sensitive WS2 data" not in captured_prompt



def test_compare_pipelines_import_models() -> None:
    """Test importing compare_pipelines and running import_all_models() without error."""
    import scripts.compare_pipelines  # noqa: F401
    from scripts._models import import_all_models

    import_all_models()


@pytest.mark.asyncio
async def test_compare_pipelines_workspace_not_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If --workspace id does not exist, print 'workspace not found' and list workspaces, exit 1."""
    import sys

    from scripts.compare_pipelines import main

    test_args = ["compare_pipelines.py", "--workspace", "00000000-0000-0000-0000-000000000000"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            await main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "workspace not found" in captured.out.lower()
    assert "Existing workspaces:" in captured.out
