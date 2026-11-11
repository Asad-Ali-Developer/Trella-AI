"""Compare Legacy and Scoped Skill Run Pipelines.

Runs a skill under RUN_PIPELINE='legacy' and RUN_PIPELINE='scoped' for a given
workspace and client, reporting:
- Items sent
- Estimated input tokens
- Number of insights
- Valid-citation ratio
- Side-by-side insight titles
"""

import argparse
import asyncio
import json
import sys
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.modules.llm.base import LLMResult
from app.modules.runs.models import Run
from app.modules.runs.report_schemas import (
    ClientNeedsReportV2,
    Headline,
    Health,
)
from app.modules.runs.schemas import RunCreateRequest
from app.modules.runs.service import RunService
from app.modules.skills.models import Skill
from app.modules.skills.schemas import CitedSource, NeedInsight
from app.modules.trello.models import TrelloClientRecord
from app.modules.workspaces.models import Workspace
from scripts._models import import_all_models

import_all_models()


def _create_mock_report(context_prompt: str) -> tuple[ClientNeedsReportV2, LLMResult]:
    """Generate a valid mock report citing IDs found in the prompt."""
    import re

    cited_ids = re.findall(r"\[ID:\s*([^\]]+)\]", context_prompt)
    first_id = cited_ids[0] if cited_ids else "card-1"

    report = ClientNeedsReportV2(
        headline=Headline(
            status_word="steady",
            status_word_tone="positive",
            rest=".",
            summary="Client operations are running smoothly without critical blockers.",
        ),
        health=Health(
            status="green",
            confidence="high",
        ),
        needs=[
            NeedInsight(
                text="Streamline weekly deliverables",
                priority="high",
                sources=[CitedSource(source_id=first_id, source_type="card", title="Setup", valid=True)],
            )
        ],
        patterns=[],
        stakeholders=[],
        risks=[],
    )
    res = LLMResult(
        content=report.model_dump_json(),
        prompt_tokens=len(context_prompt) // 4,
        completion_tokens=150,
        total_tokens=(len(context_prompt) // 4) + 150,
        model="mock-gemini",
        provider="gemini",
        cost_usd=0.001,
    )
    return report, res


async def run_pipeline_for_mode(
    db: AsyncSession,
    workspace: Workspace,
    skill: Skill,
    client: TrelloClientRecord | None,
    mode: str,
    mock_llm: bool,
) -> dict[str, Any]:
    """Execute a run under the specified pipeline mode and collect comparison metrics."""
    settings.RUN_PIPELINE = mode  # type: ignore[assignment]

    run_service = RunService(db)
    create_req = RunCreateRequest(
        skill_id=skill.id,
        client_id=client.id if client else None,
        trigger="manual",
    )
    run = await run_service.create_run(workspace.id, None, create_req)

    if mock_llm:
        async def _mock_generate(*args: Any, **kwargs: Any) -> tuple[ClientNeedsReportV2, LLMResult]:
            prompt = kwargs.get("prompt", "")
            return _create_mock_report(prompt)

        with patch("app.modules.llm.gemini.GeminiProvider.generate_structured", new=AsyncMock(side_effect=_mock_generate)):
            executed_run = await run_service.execute_run(run.id)
    else:
        executed_run = await run_service.execute_run(run.id)

    # Re-fetch run with insights
    res = await db.scalars(
        select(Run).options(selectinload(Run.insights)).where(Run.id == executed_run.id)
    )
    full_run = res.first() or executed_run

    output = full_run.output_json or {}
    stats = output.get("stats") or {}
    meta_budget = output.get("_meta", {}).get("budget") or {}

    card_count = stats.get("card_count", 0)
    comment_count = stats.get("comment_count", 0)
    commit_count = stats.get("commit_count", 0)
    items_sent = f"{card_count} cards, {comment_count} comments, {commit_count} commits"
    input_tokens = full_run.tokens_in or meta_budget.get("final_tokens", 0)

    insights = list(full_run.insights)
    insights_count = len(insights)
    valid_citations = sum(1 for i in insights if all(s.get("valid", True) for s in i.source_refs))
    valid_ratio: float | str = (valid_citations / insights_count) if insights_count > 0 else "n/a"
    titles = [f"[{i.category}] {i.title}" for i in insights]

    return {
        "run_id": str(full_run.id),
        "status": full_run.status,
        "items_sent": items_sent,
        "input_tokens": input_tokens,
        "insights_count": insights_count,
        "valid_citation_ratio": valid_ratio,
        "insight_titles": titles,
        "meta_budget": meta_budget,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compare legacy and scoped skill execution pipelines.")
    parser.add_argument("--workspace", required=True, help="Workspace UUID or name")
    parser.add_argument("--client", default="all", help="Client UUID, name, or 'all'")
    parser.add_argument("--skill", default="client-needs-analyzer", help="Skill UUID or slug")
    parser.add_argument("--real", action="store_true", help="Use real LLM API instead of mock")
    args = parser.parse_args()

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        # Resolve Workspace
        ws_query = select(Workspace)
        try:
            ws_id = UUID(args.workspace)
            ws_query = ws_query.where(Workspace.id == ws_id)
        except ValueError:
            ws_query = ws_query.where(Workspace.name == args.workspace)
        ws_res = await db.scalars(ws_query)
        workspace = ws_res.first()
        if not workspace:
            print(f"workspace not found: {args.workspace}")
            all_ws = (await db.scalars(select(Workspace).order_by(Workspace.name))).all()
            print("Existing workspaces:")
            if not all_ws:
                print("  (no workspaces found)")
            else:
                for ws in all_ws:
                    print(f"  - {ws.id}: {ws.name}")
            sys.exit(1)

        # Resolve Skill
        sk_query = select(Skill).where(
            or_(Skill.workspace_id == workspace.id, Skill.workspace_id.is_(None))
        )
        try:
            sk_id = UUID(args.skill)
            sk_query = sk_query.where(Skill.id == sk_id)
        except ValueError:
            sk_query = sk_query.where(Skill.slug == args.skill)
        sk_res = await db.scalars(sk_query)
        skill = sk_res.first()
        if not skill:
            print(f"Error: Skill '{args.skill}' not found.")
            sys.exit(1)

        # Resolve Client
        client: TrelloClientRecord | None = None
        if args.client and args.client.lower() != "all":
            cl_query = select(TrelloClientRecord).where(TrelloClientRecord.workspace_id == workspace.id)
            try:
                cl_id = UUID(args.client)
                cl_query = cl_query.where(TrelloClientRecord.id == cl_id)
            except ValueError:
                cl_query = cl_query.where(TrelloClientRecord.name == args.client)
            cl_res = await db.scalars(cl_query)
            client = cl_res.first()
            if not client:
                print(f"Error: Client '{args.client}' not found in workspace.")
                sys.exit(1)

        client_label = client.name if client else "All Clients"
        print(f"Comparing pipelines for Workspace: '{workspace.name}', Client: '{client_label}', Skill: '{skill.name}'")
        print(f"LLM Mode: {'Real LLM' if args.real else 'Mocked LLM'}\n")

        # 1. Run Legacy
        legacy_res = await run_pipeline_for_mode(db, workspace, skill, client, mode="legacy", mock_llm=not args.real)

        # 2. Run Scoped
        scoped_res = await run_pipeline_for_mode(db, workspace, skill, client, mode="scoped", mock_llm=not args.real)

        def format_ratio(val: Any) -> str:
            if isinstance(val, (int, float)):
                return f"{val:.2%}"
            return str(val)

        # Print comparison table
        print(f"{'Metric':<25} | {'Legacy':<40} | {'Scoped':<40}")
        print("-" * 110)
        print(f"{'Items Sent':<25} | {str(legacy_res['items_sent']):<40} | {str(scoped_res['items_sent']):<40}")
        print(f"{'Estimated Input Tokens':<25} | {str(legacy_res['input_tokens']):<40} | {str(scoped_res['input_tokens']):<40}")
        print(f"{'Number of Insights':<25} | {str(legacy_res['insights_count']):<40} | {str(scoped_res['insights_count']):<40}")
        print(f"{'Valid-Citation Ratio':<25} | {format_ratio(legacy_res['valid_citation_ratio']):<40} | {format_ratio(scoped_res['valid_citation_ratio']):<40}")
        print("-" * 110)

        # Side-by-side insight titles
        print("\nSide-by-side Insight Titles:")
        legacy_titles = legacy_res["insight_titles"]
        scoped_titles = scoped_res["insight_titles"]
        max_len = max(len(legacy_titles), len(scoped_titles), 1)

        print(f"{'#':<4} | {'Legacy Insight Title':<35} | {'Scoped Insight Title':<35}")
        print("-" * 80)
        for i in range(max_len):
            lt = (legacy_titles[i][:32] + "...") if i < len(legacy_titles) and len(legacy_titles[i]) > 35 else (legacy_titles[i] if i < len(legacy_titles) else "-")
            st = (scoped_titles[i][:32] + "...") if i < len(scoped_titles) and len(scoped_titles[i]) > 35 else (scoped_titles[i] if i < len(scoped_titles) else "-")
            print(f"{i+1:<4} | {lt:<35} | {st:<35}")

        print("\nScope Configuration:")
        print(json.dumps(skill.scope_json or {}, indent=2))
        if scoped_res.get("meta_budget"):
            print("\nScoped _meta.budget:")
            print(json.dumps(scoped_res["meta_budget"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
