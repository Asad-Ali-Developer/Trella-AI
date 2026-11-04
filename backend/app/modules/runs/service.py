"""Service layer for executing skill runs and managing insights."""

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.modules.context.service import WorkspaceContextService
from app.modules.llm import get_llm_provider
from app.modules.runs.citations import validate_and_enrich_citations
from app.modules.runs.models import Insight, Run
from app.modules.runs.prompts import (
    GENERATION_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_generation_prompt,
    render_skill_template,
)
from app.modules.runs.report_schemas import (
    V2_EXTRA_FIELDS,
    ClientNeedsReportV2,
    build_stats,
    normalize_headline,
)
from app.modules.runs.schemas import RunCreateRequest
from app.modules.skills.models import Skill
from app.modules.workspaces.models import Workspace

logger = get_logger("app.modules.runs.service")

MIN_OUTPUT_TOKENS = 12288


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _clean_sources(sources: list[str], valid_ids: set[str]) -> list[str]:
    """Keep only source IDs that exist in the input context (order preserved, de-duplicated)."""
    return [s for s in dict.fromkeys(str(x).strip() for x in sources) if s in valid_ids]


def _evidence_supported(evidence: str, source_ids: list[str], text_by_id: dict[str, str]) -> bool:
    """An evidence quote must appear verbatim (whitespace/case-insensitive) in a cited item."""
    needle = _norm(evidence)
    return any(needle in text_by_id.get(sid, "") for sid in source_ids)


def _filter_cited(
    items: list[Any],
    valid_ids: set[str],
    text_by_id: dict[str, str],
    stats: dict[str, int],
) -> list[Any]:
    """Drop items without a valid source; blank evidence quotes that are not in the sources."""
    kept: list[Any] = []
    for item in items:
        cleaned = _clean_sources(item.sources, valid_ids)
        if not cleaned:
            stats["dropped_uncited_items"] += 1
            continue
        item.sources = cleaned
        evidence = getattr(item, "evidence", None)
        if evidence and not _evidence_supported(evidence, cleaned, text_by_id):
            item.evidence = None
            stats["evidence_mismatches"] += 1
        kept.append(item)
    return kept


def _sanitize_extras(
    report: Any,
    valid_ids: set[str],
    text_by_id: dict[str, str],
) -> dict[str, int]:
    """Validate citations on the V2-only sections (the legacy validator covers the core four)."""
    stats = {"dropped_uncited_items": 0, "evidence_mismatches": 0}

    def f(items: list[Any] | None) -> list[Any]:
        if not items:
            return []
        return _filter_cited(items, valid_ids, text_by_id, stats)

    health = getattr(report, "health", None)
    if health is not None:
        health.drivers = f(getattr(health, "drivers", []))
    if hasattr(report, "scope_changes") and report.scope_changes is not None:
        report.scope_changes = f(report.scope_changes)
    work_churn = getattr(report, "work_churn", None)
    if work_churn is not None:
        work_churn.likely_causes = f(getattr(work_churn, "likely_causes", []))
    mood = getattr(report, "mood", None)
    if mood is not None:
        mood.swings = f(getattr(mood, "swings", []))
        mood.positive_signals = f(getattr(mood, "positive_signals", []))
    delivery = getattr(report, "delivery_performance", None)
    if delivery is not None:
        delivery.wins = f(getattr(delivery, "wins", []))
        delivery.slips = f(getattr(delivery, "slips", []))
        delivery.open_commitments = f(getattr(delivery, "open_commitments", []))
    if hasattr(report, "recommended_actions") and report.recommended_actions is not None:
        report.recommended_actions = f(report.recommended_actions)
    return stats


def _compute_metrics(items: list[Any]) -> dict[str, Any]:
    """Code-computed facts the LLM may quote. Event metrics arrive with card_events (planned)."""
    roles = [
        getattr(i, "author_role", None)
        or (i.metadata.get("author_role") if hasattr(i, "metadata") and isinstance(i.metadata, dict) else None)
        for i in items
    ]
    return {
        "context_items_total": len(items),
        "items_by_type": dict(Counter(str(i.item_type) for i in items)),
        "client_authored_items": sum(1 for r in roles if r == "client"),
        "internal_authored_items": sum(1 for r in roles if r == "internal"),
        "role_data_available": any(r in ("client", "internal") for r in roles),
        "event_metrics": "unavailable",
    }


def _item_header(item: Any, item_id: str) -> str:
    author = getattr(item, "author_name", None) or (
        item.metadata.get("author_name") if hasattr(item, "metadata") and isinstance(item.metadata, dict) else None
    )
    role = getattr(item, "author_role", None) or (
        item.metadata.get("author_role") if hasattr(item, "metadata") and isinstance(item.metadata, dict) else None
    ) or "unknown"
    created = getattr(item, "created_at", None) or getattr(item, "occurred_at", None)
    meta = []
    if author:
        meta.append(f"Author: {author}")
    meta.append(f"Role: {role}")
    if created:
        meta.append(f"At: {created}")
    return f"[ID: {item_id}] (Type: {item.item_type}) ({' | '.join(meta)}) {item.title or ''}"


class RunService:
    """Service for running skills against workspace context and persisting insights."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(
        self,
        workspace_id: UUID,
        user_id: UUID | None,
        request: RunCreateRequest,
    ) -> Run:
        """Create a new run record in pending state."""
        from app.modules.skills.service import SkillService

        skill_service = SkillService(self.db)
        skill = await skill_service.get_skill(request.skill_id, workspace_id)

        run = Run(
            skill_id=skill.id,
            workspace_id=workspace_id,
            user_id=user_id,
            client_id=request.client_id,
            status="pending",
            trigger=request.trigger,
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("run_created", run_id=str(run.id), skill_id=str(skill.id), workspace_id=str(workspace_id))
        return run

    async def execute_run(self, run_id: UUID) -> Run:
        """Execute a pending or scheduled skill run against workspace context."""
        result = await self.db.scalars(
            select(Run).options(selectinload(Run.insights)).where(Run.id == run_id)
        )
        run = result.first()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found.",
            )

        run.status = "running"
        run.started_at = datetime.now(UTC)
        await self.db.commit()

        try:
            workspace = await self.db.get(Workspace, run.workspace_id)
            if not workspace:
                raise ValueError(f"Workspace {run.workspace_id} not found.")

            skill = await self.db.get(Skill, run.skill_id)
            if not skill:
                raise ValueError(f"Skill {run.skill_id} not found.")

            # 1. Build workspace context snapshot
            context_service = WorkspaceContextService(self.db, workspace)
            context_response = await context_service.build(
                client_id=run.client_id,
                max_tokens=8000,
            )
            all_items = [item for chunk in context_response.chunks for item in chunk.items]

            # 2. Content hashing for provenance
            context_content = "".join(
                f"{item.external_id or item.card_id or item.source_id}:{item.text}"
                for item in all_items
            )
            run.input_context_hash = hashlib.sha256(context_content.encode("utf-8")).hexdigest()

            # 3. Format items; collect valid IDs and per-ID text for citation/evidence checks
            formatted_items: list[str] = []
            valid_ids: set[str] = set()
            text_by_id: dict[str, str] = {}
            ref_index: dict[str, dict[str, Any]] = {}
            for item in all_items:
                item_id = str(item.card_id or item.external_id or item.source_id or "unknown")
                valid_ids.add(item_id)
                text_by_id[item_id] = text_by_id.get(item_id, "") + " " + _norm(
                    f"{item.title or ''} {item.text}"
                )
                ref_index.setdefault(
                    item_id,
                    {
                        "id": item_id,
                        "type": str(item.item_type),
                        "title": item.title,
                        "url": getattr(item, "url", None),
                    },
                )
                formatted_items.append(f"{_item_header(item, item_id)}\n{item.text}\n")

            context_text = "\n---\n".join(formatted_items)
            client_name = "All Clients"
            if run.client_id:
                for c in context_response.clients:
                    if c.id == run.client_id:
                        client_name = c.name
                        break

            scope = getattr(skill, "scope_json", None) or {}
            metrics = _compute_metrics(all_items)
            full_prompt = build_generation_prompt(
                task_instruction=render_skill_template(skill.prompt_template, client_name),
                client_name=client_name,
                period=str(scope.get("date_range", "unspecified")),
                reference_date=datetime.now(UTC).date().isoformat(),
                metrics=metrics,
                context_text=context_text,
            )

            # 4. Invoke LLM provider
            provider_name = skill.model_config_json.get("provider", "gemini")
            model_name = skill.model_config_json.get("model")
            provider = get_llm_provider(provider_name, model=model_name)

            parsed_report, llm_result = await provider.generate_structured(
                prompt=full_prompt,
                response_schema=ClientNeedsReportV2,
                model=model_name,
                system_instruction=GENERATION_SYSTEM_PROMPT,
                temperature=skill.model_config_json.get("temperature", 0.1),
                max_tokens=max(int(skill.model_config_json.get("max_tokens", MIN_OUTPUT_TOKENS)), MIN_OUTPUT_TOKENS),
            )

            # 5a. Core sections: existing validator/enricher (unchanged behavior)
            enriched_report, core_valid = validate_and_enrich_citations(parsed_report, context_response)

            # 5b. V2 sections: validate IDs and evidence quotes against the input context
            extra_stats = _sanitize_extras(parsed_report, valid_ids, text_by_id)
            all_valid = core_valid and extra_stats["dropped_uncited_items"] == 0

            # 6. Persist individual Insight records
            self._persist_core_insights(run, enriched_report)
            self._persist_extra_insights(run, parsed_report, ref_index)

            # 7. Update run record
            normalize_headline(parsed_report)
            output = enriched_report.model_dump()
            output.update(parsed_report.model_dump(include=V2_EXTRA_FIELDS, by_alias=True))
            output["stats"] = build_stats(metrics, parsed_report)
            output["quality"] = {"prompt_version": PROMPT_VERSION, **extra_stats}

            run.tokens_in = llm_result.prompt_tokens
            run.tokens_out = llm_result.completion_tokens
            run.cost_usd = llm_result.cost_usd
            run.output_json = output
            run.citations_valid = all_valid
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            run.error = None

            await self.db.commit()
            await self.db.refresh(run)
            logger.info(
                "run_completed",
                run_id=str(run.id),
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
                cost_usd=run.cost_usd,
                citations_valid=run.citations_valid,
                dropped_uncited_items=extra_stats["dropped_uncited_items"],
                evidence_mismatches=extra_stats["evidence_mismatches"],
            )
            return run

        except Exception as exc:
            err_msg = str(exc).strip() or f"{type(exc).__name__}: Execution failed or timed out"
            logger.error("run_failed", run_id=str(run_id), error=err_msg)
            run.status = "failed"
            run.error = err_msg
            run.completed_at = datetime.now(UTC)
            await self.db.commit()
            return run

    # ------------------------------------------------------------------ persistence

    def _add_insight(
        self,
        run: Run,
        *,
        category: str,
        title: str,
        detail: str,
        source_refs: list[dict[str, Any]],
        severity_or_priority: str | None = None,
    ) -> None:
        self.db.add(
            Insight(
                run_id=run.id,
                workspace_id=run.workspace_id,
                client_id=run.client_id,
                category=category,
                title=title[:200],
                detail=detail,
                severity_or_priority=severity_or_priority,
                source_refs=source_refs,
            )
        )

    def _persist_core_insights(self, run: Run, report: Any) -> None:
        for need in report.needs:
            self._add_insight(
                run, category="need", title=need.text, detail=need.text,
                severity_or_priority=need.priority,
                source_refs=[s.model_dump() for s in need.sources],
            )
        for pattern in report.patterns:
            self._add_insight(
                run, category="pattern", title=pattern.text, detail=pattern.text,
                source_refs=[s.model_dump() for s in pattern.sources],
            )
        for stakeholder in report.stakeholders:
            self._add_insight(
                run, category="stakeholder", title=stakeholder.name,
                detail=f"{stakeholder.name} - {stakeholder.role}",
                source_refs=[s.model_dump() for s in stakeholder.sources],
            )
        for risk in report.risks:
            self._add_insight(
                run, category="risk", title=risk.text, detail=risk.text,
                severity_or_priority=risk.severity,
                source_refs=[s.model_dump() for s in risk.sources],
            )

    def _persist_extra_insights(
        self,
        run: Run,
        report: Any,
        ref_index: dict[str, dict[str, Any]],
    ) -> None:
        def refs(ids: list[str]) -> list[dict[str, Any]]:
            return [ref_index[i] for i in ids if i in ref_index]

        scope_changes = getattr(report, "scope_changes", None) or []
        for sc in scope_changes:
            detail = sc.text
            before = getattr(sc, "before", None)
            after = getattr(sc, "after", None)
            if before or after:
                detail += f" (before: {before or 'n/a'} -> after: {after or 'n/a'})"
            interpretation = getattr(sc, "interpretation", None)
            if interpretation:
                detail += f" Interpretation: {interpretation}"
            self._add_insight(
                run,
                category="scope_change",
                title=f"[{getattr(sc, 'classification', 'scope')}] {sc.text}",
                detail=detail,
                severity_or_priority=getattr(sc, "impact", None),
                source_refs=refs(getattr(sc, "sources", []) or []),
            )

        mood = getattr(report, "mood", None)
        if mood and hasattr(mood, "swings"):
            for swing in getattr(mood, "swings", []) or []:
                evidence = getattr(swing, "evidence", None)
                self._add_insight(
                    run,
                    category="mood_swing",
                    title=f"Tone shift: {getattr(swing, 'from_sentiment', 'unknown')} -> {getattr(swing, 'to_sentiment', 'unknown')}",
                    detail=(getattr(swing, "trigger", None) or "Trigger not evidenced.")
                    + (f' Evidence: "{evidence}"' if evidence else ""),
                    source_refs=refs(getattr(swing, "sources", []) or []),
                )

        delivery = getattr(report, "delivery_performance", None)
        if delivery:
            for win in getattr(delivery, "wins", []) or []:
                self._add_insight(
                    run,
                    category="delivery_win",
                    title=win.text,
                    detail=win.text,
                    source_refs=refs(getattr(win, "sources", []) or []),
                )
            for slip in getattr(delivery, "slips", []) or []:
                self._add_insight(
                    run,
                    category="delivery_slip",
                    title=slip.text,
                    detail=slip.text,
                    source_refs=refs(getattr(slip, "sources", []) or []),
                )

        recommended_actions = getattr(report, "recommended_actions", None) or []
        for act in recommended_actions:
            self._add_insight(
                run,
                category="action",
                title=act.action,
                detail=f"{act.action} Why: {getattr(act, 'why', '')}",
                severity_or_priority=getattr(act, "urgency", None),
                source_refs=refs(getattr(act, "sources", []) or []),
            )

    # ------------------------------------------------------------------ queries

    async def list_runs(
        self,
        workspace_id: UUID,
        client_id: UUID | None = None,
    ) -> list[Run]:
        """List all runs for a workspace with optional client filter."""
        query = select(Run).where(Run.workspace_id == workspace_id)
        if client_id is not None:
            query = query.where(Run.client_id == client_id)
        query = query.order_by(Run.created_at.desc())
        result = await self.db.scalars(query)
        return list(result.all())

    async def get_run(self, run_id: UUID, workspace_id: UUID) -> Run:
        """Fetch a run with insights eagerly loaded, verifying workspace isolation."""
        result = await self.db.scalars(
            select(Run)
            .options(selectinload(Run.insights))
            .where(Run.id == run_id, Run.workspace_id == workspace_id)
        )
        run = result.first()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found in this workspace.",
            )
        return run

    async def delete_run(self, run_id: UUID, workspace_id: UUID) -> None:
        """Delete a run and all associated insights with workspace isolation."""
        run = await self.get_run(run_id=run_id, workspace_id=workspace_id)
        await self.db.delete(run)
        await self.db.commit()
        logger.info("run_deleted", run_id=str(run_id), workspace_id=str(workspace_id))

    async def submit_insight_feedback(
        self,
        insight_id: UUID,
        workspace_id: UUID,
        feedback: str,
        notes: str | None = None,
    ) -> Insight:
        """Record user feedback (thumbs up / down) on an individual insight."""
        result = await self.db.scalars(
            select(Insight).where(
                Insight.id == insight_id,
                Insight.workspace_id == workspace_id,
            )
        )
        insight = result.first()
        if not insight:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Insight not found in this workspace.",
            )

        insight.feedback = feedback
        insight.feedback_notes = notes
        await self.db.commit()
        await self.db.refresh(insight)
        logger.info("insight_feedback_submitted", insight_id=str(insight_id), feedback=feedback)
        return insight


    async def get_daily_activity(
        self,
        workspace_id: UUID,
        user_id: UUID | None = None,
        client_id: UUID | None = None,
        days: int = 365,
    ) -> dict[str, Any]:
        """Aggregate report run counts per day for the workspace/user over the last N days."""
        now = datetime.now(UTC)
        start_date = now - timedelta(days=days)

        date_col = cast(Run.created_at, Date)
        query = (
            select(date_col.label("day"), func.count(Run.id).label("count"))
            .where(
                Run.workspace_id == workspace_id,
                Run.created_at >= start_date,
            )
        )
        if user_id is not None:
            query = query.where(Run.user_id == user_id)
        if client_id is not None:
            query = query.where(Run.client_id == client_id)

        query = query.group_by(date_col).order_by(date_col.asc())

        result = await self.db.execute(query)
        daily_counts = []
        activity_map: dict[str, int] = {}
        total_runs = 0

        for row in result:
            day_val = row.day
            day_str = day_val.isoformat() if hasattr(day_val, "isoformat") else str(day_val)
            c = int(row.count)
            daily_counts.append({"date": day_str, "count": c})
            activity_map[day_str] = c
            total_runs += c

        return {
            "total_runs": total_runs,
            "daily_counts": daily_counts,
            "activity_map": activity_map,
        }
