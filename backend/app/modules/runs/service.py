"""Service layer for executing skill runs and managing insights."""

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.context.models import TrelloCardSummary
from app.modules.context.schemas import (
    ContextChunk,
    ContextClient,
    ContextItem,
    ContextSource,
    WorkspaceContextResponse,
)
from app.modules.context.scope import ScopeResolver, ScopeValidationError
from app.modules.context.service import WorkspaceContextService
from app.modules.github.models import GithubCommit
from app.modules.llm import get_llm_provider
from app.modules.llm.base import LLMResult
from app.modules.runs.budget import (
    _card_activity_timestamp,
    _comment_activity_timestamp,
    _format_card_raw_text,
    assemble_and_budget_prompt,
)
from app.modules.runs.citations import validate_and_enrich_citations
from app.modules.runs.models import ClientDigest, Insight, Run
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
from app.modules.scheduler.models import Schedule
from app.modules.skills.models import Skill
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientRecord,
    TrelloComment,
    TrelloMember,
    TrelloSource,
)
from app.modules.workspaces.models import Workspace

logger = get_logger("app.modules.runs.service")

MIN_OUTPUT_TOKENS = 12288


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _clean_sources(sources: list[str], valid_ids: set[str]) -> list[str]:
    """Keep only source IDs that exist in the input context (case-insensitive, order preserved, de-duplicated)."""
    canonical_by_lower: dict[str, str] = {}
    for vid in valid_ids:
        cleaned_vid = str(vid).strip()
        canonical_by_lower.setdefault(cleaned_vid.lower(), cleaned_vid)

    cleaned: list[str] = []
    seen_lower: set[str] = set()
    for raw in sources:
        candidate = str(raw).strip()
        key = candidate.lower()
        if key in canonical_by_lower and key not in seen_lower:
            seen_lower.add(key)
            cleaned.append(canonical_by_lower[key])
    return cleaned


def _evidence_supported(evidence: str, source_ids: list[str], text_by_id: dict[str, str]) -> bool:
    """An evidence quote must appear verbatim (whitespace/case-insensitive) in a cited item."""
    needle = _norm(evidence)
    lower_text_by_id = {k.strip().lower(): v for k, v in text_by_id.items()}
    return any(needle in lower_text_by_id.get(sid.strip().lower(), "") for sid in source_ids)


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


def _compute_core_citation_stats(
    report: Any,
    valid_ids: set[str],
) -> tuple[float, int, int]:
    """Compute (invalid_ratio, invalid_citations, total_citations) across the core 4 sections.
    Core sections: needs, patterns, stakeholders, risks.
    """
    total_citations = 0
    invalid_citations = 0
    lower_valid_ids = {vid.strip().lower() for vid in valid_ids}

    for section_name in ("needs", "patterns", "stakeholders", "risks"):
        items = getattr(report, section_name, []) or []
        for item in items:
            sources = getattr(item, "sources", []) or []
            if not sources:
                total_citations += 1
                invalid_citations += 1
                continue
            for src in sources:
                total_citations += 1
                sid = getattr(src, "source_id", "")
                if not sid or str(sid).strip().lower() not in lower_valid_ids:
                    invalid_citations += 1

    ratio = (invalid_citations / total_citations) if total_citations > 0 else 0.0
    return ratio, invalid_citations, total_citations


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
        "card_count": sum(1 for i in items if str(i.item_type) == "card"),
        "comment_count": sum(1 for i in items if str(i.item_type) == "comment"),
        "commit_count": sum(1 for i in items if str(i.item_type) == "commit"),
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

    async def execute_run(self, run_id: UUID, schedule: Schedule | None = None) -> Run:
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

            if settings.RUN_PIPELINE == "scoped":
                return await self._execute_run_scoped(run, workspace, skill, schedule=schedule)
            return await self._execute_run_legacy(run, workspace, skill)

        except Exception as exc:
            err_msg = str(exc).strip() or f"{type(exc).__name__}: Execution failed or timed out"
            logger.error("run_failed", run_id=str(run_id), error=err_msg)
            run.status = "failed"
            run.error = err_msg
            run.completed_at = datetime.now(UTC)
            await self.db.commit()
            return run

    async def _execute_run_legacy(
        self,
        run: Run,
        workspace: Workspace,
        skill: Skill,
    ) -> Run:
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
            item_id = str(item.card_id or item.external_id or item.source_id or "unknown").strip()
            item_text = _norm(f"{item.title or ''} {item.text}")
            item_ref = {
                "id": item_id,
                "type": str(item.item_type),
                "title": item.title,
                "url": getattr(item, "url", None),
            }
            for candidate_id in (item.card_id, item.external_id, item.source_id):
                if candidate_id:
                    cid = str(candidate_id).strip()
                    valid_ids.add(cid)
                    text_by_id[cid] = text_by_id.get(cid, "") + " " + item_text
                    ref_index.setdefault(cid, item_ref)
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

        # 5a. Core sections: validate, enrich, and strip items with zero valid citations
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
        stats_dict = build_stats(metrics, parsed_report)
        stats_dict["card_count"] = metrics.get("card_count", 0)
        stats_dict["comment_count"] = metrics.get("comment_count", 0)
        stats_dict["commit_count"] = metrics.get("commit_count", 0)
        output["stats"] = stats_dict
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

    async def _execute_run_scoped(
        self,
        run: Run,
        workspace: Workspace,
        skill: Skill,
        schedule: Schedule | None = None,
    ) -> Run:
        # 1. Resolve skill scope in SQL
        try:
            resolved_scope = await ScopeResolver.resolve(
                self.db,
                workspace_id=run.workspace_id,
                scope_json=skill.scope_json,
                client_id_override=run.client_id,
            )
        except ScopeValidationError as exc:
            err_msg = f"Scope validation failed: {exc}"
            logger.error("run_failed_scope_validation", run_id=str(run.id), error=err_msg)
            run.status = "failed"
            run.error = err_msg
            run.completed_at = datetime.now(UTC)
            await self.db.commit()
            return run

        # 2. Check Delta Mode
        sched = schedule
        if sched is None and run.trigger == "scheduled":
            sched_res = await self.db.scalars(
                select(Schedule).where(
                    Schedule.workspace_id == run.workspace_id,
                    Schedule.skill_id == run.skill_id,
                    Schedule.active,
                )
            )
            sched = sched_res.first()

        is_delta = sched is not None and getattr(sched, "is_delta_only", True)
        last_run_at = sched.last_run_at if (sched and is_delta) else None

        target_card_ids: set[UUID] = set(resolved_scope.card_ids)
        target_commit_ids: set[UUID] = set(resolved_scope.commit_ids)
        older_comments_by_card: dict[UUID, list[TrelloComment]] = {}
        new_comments_by_card: dict[UUID, list[TrelloComment]] = {}

        if is_delta and last_run_at is not None:
            changed_cards: set[UUID] = set()
            if resolved_scope.card_ids:
                q_cards = select(TrelloCard.id).where(
                    TrelloCard.id.in_(resolved_scope.card_ids),
                    TrelloCard.workspace_id == run.workspace_id,
                    or_(
                        TrelloCard.last_activity_at > last_run_at,
                        (TrelloCard.last_activity_at.is_(None) & (TrelloCard.updated_at > last_run_at)),
                    ),
                )
                res_cards = await self.db.scalars(q_cards)
                changed_cards.update(res_cards.all())

            if resolved_scope.comment_ids:
                q_cmts = select(TrelloComment.id, TrelloComment.card_id).where(
                    TrelloComment.id.in_(resolved_scope.comment_ids),
                    TrelloComment.workspace_id == run.workspace_id,
                    or_(
                        TrelloComment.created_at_trello > last_run_at,
                        (TrelloComment.created_at_trello.is_(None) & (TrelloComment.created_at > last_run_at)),
                    ),
                )
                res_cmts = await self.db.execute(q_cmts)
                for _c_id, card_id in res_cmts.all():
                    if card_id in resolved_scope.card_ids:
                        changed_cards.add(card_id)

            new_commits: set[UUID] = set()
            if resolved_scope.commit_ids:
                q_commits = select(GithubCommit.id).where(
                    GithubCommit.id.in_(resolved_scope.commit_ids),
                    GithubCommit.workspace_id == run.workspace_id,
                    or_(
                        GithubCommit.committed_at > last_run_at,
                        (GithubCommit.committed_at.is_(None) & (GithubCommit.created_at > last_run_at)),
                    ),
                )
                res_commits = await self.db.scalars(q_commits)
                new_commits.update(res_commits.all())

            if not changed_cards and not new_commits:
                logger.info(
                    "run_skipped_delta_unchanged",
                    run_id=str(run.id),
                    workspace_id=str(run.workspace_id),
                    last_run_at=last_run_at.isoformat(),
                )
                run.status = "skipped"
                run.error = "Skipped: No new cards or comment changes detected since last run."
                run.completed_at = datetime.now(UTC)
                await self.db.commit()
                return run

            target_card_ids = changed_cards
            target_commit_ids = new_commits

        # 3. Load DB entities for the scoped target IDs
        loaded_cards: list[TrelloCard] = []
        if target_card_ids:
            c_res = await self.db.scalars(
                select(TrelloCard).where(
                    TrelloCard.id.in_(target_card_ids),
                    TrelloCard.workspace_id == run.workspace_id,
                )
            )
            loaded_cards = list(c_res.all())

        comments_by_card: dict[UUID, list[TrelloComment]] = {}
        if target_card_ids and resolved_scope.include_comments:
            cmt_res = await self.db.scalars(
                select(TrelloComment).where(
                    TrelloComment.card_id.in_(target_card_ids),
                    TrelloComment.workspace_id == run.workspace_id,
                )
            )
            all_card_comments = list(cmt_res.all())
            for cmt in all_card_comments:
                if cmt.id not in resolved_scope.comment_ids:
                    continue
                if is_delta and last_run_at is not None:
                    c_date = cmt.created_at_trello or cmt.created_at
                    if c_date.tzinfo is None:
                        c_date = c_date.replace(tzinfo=UTC)
                    l_date = (
                        last_run_at
                        if last_run_at.tzinfo is not None
                        else last_run_at.replace(tzinfo=UTC)
                    )
                    if c_date > l_date:
                        new_comments_by_card.setdefault(cmt.card_id, []).append(cmt)
                    else:
                        older_comments_by_card.setdefault(cmt.card_id, []).append(cmt)
                else:
                    comments_by_card.setdefault(cmt.card_id, []).append(cmt)

            if is_delta and last_run_at is not None:
                for card_id in target_card_ids:
                    new_c = new_comments_by_card.get(card_id, [])
                    older_c = older_comments_by_card.get(card_id, [])
                    older_c_sorted = sorted(
                        older_c,
                        key=lambda x: x.created_at_trello or x.created_at,
                        reverse=True,
                    )[:10]  # Bounded, newest 10 older comments
                    comments_by_card[card_id] = new_c + older_c_sorted

        loaded_commits: list[GithubCommit] = []
        if target_commit_ids and resolved_scope.include_commits:
            co_res = await self.db.scalars(
                select(GithubCommit).where(
                    GithubCommit.id.in_(target_commit_ids),
                    GithubCommit.workspace_id == run.workspace_id,
                )
            )
            loaded_commits = list(co_res.all())

        summaries_by_card_id: dict[UUID, TrelloCardSummary] = {}
        if target_card_ids:
            s_res = await self.db.scalars(
                select(TrelloCardSummary).where(
                    TrelloCardSummary.card_id.in_(target_card_ids),
                    TrelloCardSummary.workspace_id == run.workspace_id,
                )
            )
            for s in s_res.all():
                summaries_by_card_id[s.card_id] = s

        used_member_ids = {m for card in loaded_cards for m in card.member_ids}
        for cmts in comments_by_card.values():
            used_member_ids.update(c.author_id for c in cmts if c.author_id)
        members_by_id: dict[str, TrelloMember] = {}
        if used_member_ids:
            m_res = await self.db.scalars(
                select(TrelloMember).where(
                    TrelloMember.workspace_id == run.workspace_id,
                    TrelloMember.trello_member_id.in_(used_member_ids),
                )
            )
            members_by_id = {m.trello_member_id: m for m in m_res.all()}

        cl_res = await self.db.scalars(
            select(TrelloClientRecord).where(TrelloClientRecord.workspace_id == run.workspace_id)
        )
        clients_by_id = {c.id: c for c in cl_res.all()}

        client_name = "All Clients"
        if run.client_id and run.client_id in clients_by_id:
            client_name = clients_by_id[run.client_id].name

        # 4. Assemble prompt with hard token budget & progressive shrinking
        budget_result = assemble_and_budget_prompt(
            cards=loaded_cards,
            comments_by_card=comments_by_card,
            commits=loaded_commits,
            summaries_by_card_id=summaries_by_card_id,
            max_input_tokens=settings.RUN_MAX_INPUT_TOKENS,
            prompt_template=skill.prompt_template,
            client_name=client_name,
            period_label=resolved_scope.period_label,
            reference_date=datetime.now(UTC).date().isoformat(),
            include_labels=resolved_scope.include_labels,
            members_by_id=members_by_id,
            clients_by_id=clients_by_id,
        )

        # Check if scoped input exceeds Settings.RUN_DIGEST_THRESHOLD_TOKENS
        use_digest = (
            budget_result.initial_tokens > settings.RUN_DIGEST_THRESHOLD_TOKENS
            and len(clients_by_id) > 0
        )

        provider_name = skill.model_config_json.get("provider", "gemini")
        model_name = skill.model_config_json.get("model")
        provider = get_llm_provider(provider_name, model=model_name)

        digest_cache_hits = 0
        digest_cache_misses = 0
        digest_tokens_in = 0
        digest_tokens_out = 0
        digest_cost = 0.0

        if use_digest:
            # Map-Reduce Digests per client
            target_clients: list[TrelloClientRecord] = []
            if run.client_id and run.client_id in clients_by_id:
                target_clients = [clients_by_id[run.client_id]]
            else:
                cids_in_cards = {c.client_id for c in loaded_cards if c.client_id is not None}
                target_clients = [clients_by_id[cid] for cid in cids_in_cards if cid in clients_by_id]
                if not target_clients and clients_by_id:
                    target_clients = list(clients_by_id.values())

            client_digests_map: dict[UUID, str] = {}
            for cl in target_clients:
                cl_cards = [c for c in loaded_cards if c.client_id == cl.id]
                cl_cards_sorted = sorted(cl_cards, key=_card_activity_timestamp, reverse=True)
                cl_blocks: list[str] = []
                for card in cl_cards_sorted:
                    card_summary = summaries_by_card_id.get(card.id)
                    if card_summary:
                        summary_text = card_summary.summary
                    else:
                        summary_text = card.description.strip() if card.description else card.name
                    cmts = comments_by_card.get(card.id, [])
                    cmts_snippet = " ".join(c.text for c in cmts[:5])
                    cl_blocks.append(f"Card '{card.name}' (List: {card.list_name}): {summary_text}\nComments: {cmts_snippet}")

                cl_input_text = "\n---\n".join(cl_blocks) if cl_blocks else f"Client {cl.name} work activity."
                input_hash = hashlib.sha256(cl_input_text.encode("utf-8")).hexdigest()

                # Check client_digests cache
                q_cd = select(ClientDigest).where(
                    ClientDigest.workspace_id == run.workspace_id,
                    ClientDigest.client_id == cl.id,
                    ClientDigest.period_start == resolved_scope.date_from,
                    ClientDigest.period_end == resolved_scope.date_to,
                    ClientDigest.input_hash == input_hash,
                    ClientDigest.model == (model_name or "gemini"),
                    ClientDigest.prompt_version == PROMPT_VERSION,
                )
                cd_res = await self.db.scalars(q_cd)
                cached_cd = cd_res.first()

                if cached_cd is not None:
                    digest_cache_hits += 1
                    client_digests_map[cl.id] = cached_cd.digest
                else:
                    digest_cache_misses += 1
                    digest_prompt = (
                        f"Summarize work, recurring patterns, and progress for client '{cl.name}' concisely and dense with facts:\n\n"
                        f"{cl_input_text}"
                    )
                    d_res = await provider.generate(
                        prompt=digest_prompt,
                        model=model_name,
                        system_instruction="You are a senior technical project analyst. Summarize client project status faithfully.",
                        temperature=0.1,
                        max_tokens=1500,
                    )
                    digest_tokens_in += d_res.prompt_tokens
                    digest_tokens_out += d_res.completion_tokens
                    digest_cost += d_res.cost_usd
                    client_digests_map[cl.id] = d_res.content

                    new_cd = ClientDigest(
                        workspace_id=run.workspace_id,
                        client_id=cl.id,
                        period_start=resolved_scope.date_from,
                        period_end=resolved_scope.date_to,
                        input_hash=input_hash,
                        model=(model_name or "gemini"),
                        prompt_version=PROMPT_VERSION,
                        digest=d_res.content,
                        input_tokens=d_res.prompt_tokens,
                        output_tokens=d_res.completion_tokens,
                    )
                    self.db.add(new_cd)
                    await self.db.flush()

            # Bounded raw excerpts from most active cards
            BOUNDED_EXCERPTS = 10
            sorted_all_cards = sorted(loaded_cards, key=_card_activity_timestamp, reverse=True)
            excerpt_cards = sorted_all_cards[:BOUNDED_EXCERPTS]

            excerpt_items: list[ContextItem] = []
            for card in excerpt_cards:
                cl_record = clients_by_id.get(card.client_id) if card.client_id else None
                m_names = [
                    members_by_id[mid].full_name or members_by_id[mid].username
                    for mid in card.member_ids if mid in members_by_id
                ]
                card_raw = _format_card_raw_text(card, resolved_scope.include_labels, m_names)
                c_item = ContextItem(
                    item_type="card",
                    source_id=card.source_id,
                    client_id=cl_record.id if cl_record else None,
                    client_name=cl_record.name if cl_record else None,
                    card_id=card.id,
                    external_id=card.trello_card_id,
                    title=card.name,
                    text=card_raw,
                    url=card.url,
                    occurred_at=card.last_activity_at,
                    metadata={
                        "list_id": card.list_id,
                        "list_name": card.list_name,
                        "labels": card.labels,
                        "member_ids": card.member_ids,
                        "closed": card.closed,
                    },
                )
                excerpt_items.append(c_item)

                cmts = comments_by_card.get(card.id, [])
                sorted_cmts = sorted(cmts, key=_comment_activity_timestamp, reverse=True)[:5]
                for cmt in sorted_cmts:
                    author = members_by_id.get(cmt.author_id)
                    author_name = author.full_name or author.username if author else "Unknown member"
                    role_tag: Literal["client", "internal", "unknown"] = (
                        "client"
                        if (author and author.role_tag == "client")
                        else ("internal" if (author and author.role_tag == "internal") else "unknown")
                    )
                    cm_item = ContextItem(
                        item_type="comment",
                        source_id=card.source_id,
                        client_id=cl_record.id if cl_record else None,
                        client_name=cl_record.name if cl_record else None,
                        card_id=card.id,
                        external_id=cmt.trello_action_id,
                        title=card.name,
                        text=cmt.text,
                        url=card.url,
                        occurred_at=cmt.created_at_trello,
                        author_name=author_name,
                        author_role=role_tag,
                        metadata={"author_id": cmt.author_id, "author_name": author_name, "author_role": role_tag},
                    )
                    excerpt_items.append(cm_item)

            digest_text_blocks = [
                f"### Client Activity Digest: {clients_by_id[cid].name}\n{dtext}"
                for cid, dtext in client_digests_map.items()
                if cid in clients_by_id
            ]
            excerpt_blocks = [
                f"{_item_header(it, str(it.card_id or it.external_id or it.source_id or 'unknown').strip())}\n{it.text}\n"
                for it in excerpt_items
            ]
            combined_ctx_text = (
                "=== CLIENT ACTIVITY DIGESTS ===\n"
                + "\n\n".join(digest_text_blocks)
                + "\n\n=== RAW WORK EXCERPTS (MOST ACTIVE CARDS) ===\n"
                + "\n---\n".join(excerpt_blocks)
            )
            comp_metrics = _compute_metrics(excerpt_items)
            task_instruction = render_skill_template(skill.prompt_template, client_name)
            prompt_to_send = build_generation_prompt(
                task_instruction=task_instruction,
                client_name=client_name,
                period=resolved_scope.period_label,
                reference_date=datetime.now(UTC).date().isoformat(),
                metrics=comp_metrics,
                context_text=combined_ctx_text,
            )
            items_for_citations = excerpt_items
            final_metrics = comp_metrics
        else:
            prompt_to_send = budget_result.full_prompt
            items_for_citations = budget_result.items_sent
            final_metrics = budget_result.metrics

        # 5. Provenance hashing
        context_content = "".join(
            f"{item.external_id or item.card_id or item.source_id}:{item.text}"
            for item in items_for_citations
        )
        run.input_context_hash = hashlib.sha256(context_content.encode("utf-8")).hexdigest()

        # 6. Format index and ContextResponse for citation checks
        valid_ids: set[str] = set()
        text_by_id: dict[str, str] = {}
        ref_index: dict[str, dict[str, Any]] = {}
        for item in items_for_citations:
            item_id = str(item.card_id or item.external_id or item.source_id or "unknown").strip()
            item_text = _norm(f"{item.title or ''} {item.text}")
            item_ref = {
                "id": item_id,
                "type": str(item.item_type),
                "title": item.title,
                "url": getattr(item, "url", None),
            }
            for candidate_id in (item.card_id, item.external_id, item.source_id):
                if candidate_id:
                    cid = str(candidate_id).strip()
                    valid_ids.add(cid)
                    text_by_id[cid] = text_by_id.get(cid, "") + " " + item_text
                    ref_index.setdefault(cid, item_ref)

        src_res = await self.db.scalars(
            select(TrelloSource).where(TrelloSource.workspace_id == run.workspace_id)
        )
        context_sources = [
            ContextSource(
                id=source.id,
                provider="trello",
                name=source.name,
                url=source.url,
                account_name="Trello",
                sync_status=source.sync_status,
                last_synced_at=source.last_synced_at,
                sync_error=source.sync_error,
            )
            for source in src_res.all()
        ]
        context_clients = [
            ContextClient(id=client.id, name=client.name)
            for client in clients_by_id.values()
        ]
        context_response = WorkspaceContextResponse(
            workspace_id=run.workspace_id,
            workspace_name=workspace.name,
            generated_at=datetime.now(UTC),
            token_budget=settings.RUN_MAX_INPUT_TOKENS,
            estimated_tokens=budget_result.final_tokens,
            connected_accounts=[],
            sources=context_sources,
            clients=context_clients,
            members=[],
            item_count=len(items_for_citations),
            chunks=[
                ContextChunk(
                    index=0,
                    estimated_tokens=budget_result.final_tokens,
                    items=items_for_citations,
                )
            ],
        )

        # 7. Invoke LLM provider
        parsed_report, llm_result = await provider.generate_structured(
            prompt=prompt_to_send,
            response_schema=ClientNeedsReportV2,
            model=model_name,
            system_instruction=GENERATION_SYSTEM_PROMPT,
            temperature=skill.model_config_json.get("temperature", 0.1),
            max_tokens=max(int(skill.model_config_json.get("max_tokens", MIN_OUTPUT_TOKENS)), MIN_OUTPUT_TOKENS),
        )

        # Citation validation and retry if needed
        initial_invalid_ratio, _, _ = _compute_core_citation_stats(parsed_report, valid_ids)
        retry_count = 0
        final_report = parsed_report
        final_llm_result = llm_result

        if valid_ids and initial_invalid_ratio > settings.RUN_CITATION_INVALID_RATIO:
            retry_count = 1
            corrective_instruction = (
                f"\n\nCORRECTIVE INSTRUCTION: In your previous draft, {initial_invalid_ratio:.1%} of citations in core sections "
                f"were invalid (exceeding maximum allowed ratio of {settings.RUN_CITATION_INVALID_RATIO:.1%}). "
                "You MUST ground all claims. Every cited source_id MUST match one of the following valid IDs:\n"
                + "\n".join(f"- {vid}" for vid in sorted(valid_ids))
                + "\nDo not invent or alter any ID. Re-generate the entire report strictly adhering to these valid IDs."
            )
            retry_prompt = prompt_to_send + corrective_instruction
            parsed_report_retry, llm_result_retry = await provider.generate_structured(
                prompt=retry_prompt,
                response_schema=ClientNeedsReportV2,
                model=model_name,
                system_instruction=GENERATION_SYSTEM_PROMPT,
                temperature=skill.model_config_json.get("temperature", 0.1),
                max_tokens=max(int(skill.model_config_json.get("max_tokens", MIN_OUTPUT_TOKENS)), MIN_OUTPUT_TOKENS),
            )
            final_report = parsed_report_retry
            final_llm_result = LLMResult(
                content=llm_result_retry.content,
                parsed=llm_result_retry.parsed,
                prompt_tokens=llm_result.prompt_tokens + llm_result_retry.prompt_tokens,
                completion_tokens=llm_result.completion_tokens + llm_result_retry.completion_tokens,
                total_tokens=llm_result.total_tokens + llm_result_retry.total_tokens,
                cost_usd=round(llm_result.cost_usd + llm_result_retry.cost_usd, 6),
                model=llm_result_retry.model,
                provider=llm_result_retry.provider,
                raw_response=llm_result_retry.raw_response,
            )

        final_invalid_ratio, _, _ = _compute_core_citation_stats(final_report, valid_ids)

        if retry_count > 0 and final_invalid_ratio > settings.RUN_CITATION_INVALID_RATIO:
            run.status = "failed"
            err = (
                f"Citation validation failed: {final_invalid_ratio:.1%} invalid citations in core sections "
                f"exceeded threshold of {settings.RUN_CITATION_INVALID_RATIO:.1%} after corrective retry."
            )
            run.error = err
            run.completed_at = datetime.now(UTC)
            run.tokens_in = final_llm_result.prompt_tokens + digest_tokens_in
            run.tokens_out = final_llm_result.completion_tokens + digest_tokens_out
            run.cost_usd = round(final_llm_result.cost_usd + digest_cost, 6)
            run.output_json = {
                "_meta": {
                    "citation_retry": {
                        "retried": True,
                        "retry_count": 1,
                        "stripped_count": 0,
                        "initial_invalid_ratio": initial_invalid_ratio,
                        "final_invalid_ratio": final_invalid_ratio,
                    },
                    "retry_count": 1,
                    "stripped_count": 0,
                    "digest_path": use_digest,
                    "budget": {
                        "initial_tokens": budget_result.initial_tokens,
                        "final_tokens": budget_result.final_tokens,
                        "max_budget": budget_result.max_budget,
                        "shrunk": budget_result.shrunk,
                        "decisions": budget_result.decisions,
                    },
                }
            }
            await self.db.commit()
            logger.error("run_failed_citation_ratio_exceeded", run_id=str(run.id), error=err)
            return run

        initial_core_count = sum(len(getattr(final_report, s, []) or []) for s in ("needs", "patterns", "stakeholders", "risks"))

        # 8. Citations & Insights
        enriched_report, core_valid = validate_and_enrich_citations(final_report, context_response)
        extra_stats = _sanitize_extras(final_report, valid_ids, text_by_id)
        all_valid = core_valid and extra_stats["dropped_uncited_items"] == 0

        kept_core_count = sum(len(getattr(enriched_report, s, []) or []) for s in ("needs", "patterns", "stakeholders", "risks"))
        stripped_count = (initial_core_count - kept_core_count) + extra_stats["dropped_uncited_items"]

        self._persist_core_insights(run, enriched_report)
        self._persist_extra_insights(run, final_report, ref_index)

        normalize_headline(final_report)
        output = enriched_report.model_dump()
        output.update(final_report.model_dump(include=V2_EXTRA_FIELDS, by_alias=True))
        stats_dict = build_stats(final_metrics, final_report)
        stats_dict["card_count"] = final_metrics.get("card_count", 0)
        stats_dict["comment_count"] = final_metrics.get("comment_count", 0)
        stats_dict["commit_count"] = final_metrics.get("commit_count", 0)
        output["stats"] = stats_dict
        output["quality"] = {"prompt_version": PROMPT_VERSION, **extra_stats}
        output["_meta"] = {
            "budget": {
                "initial_tokens": budget_result.initial_tokens,
                "final_tokens": budget_result.final_tokens,
                "max_budget": budget_result.max_budget,
                "shrunk": budget_result.shrunk,
                "decisions": budget_result.decisions,
            },
            "citation_retry": {
                "retried": retry_count > 0,
                "retry_count": retry_count,
                "stripped_count": stripped_count,
                "initial_invalid_ratio": initial_invalid_ratio,
                "final_invalid_ratio": final_invalid_ratio,
            },
            "retry_count": retry_count,
            "stripped_count": stripped_count,
            "digest_path": use_digest,
        }
        if use_digest:
            output["_meta"]["digest_cache_hits"] = digest_cache_hits
            output["_meta"]["digest_cache_misses"] = digest_cache_misses

        run.tokens_in = final_llm_result.prompt_tokens + digest_tokens_in
        run.tokens_out = final_llm_result.completion_tokens + digest_tokens_out
        run.cost_usd = round(final_llm_result.cost_usd + digest_cost, 6)
        run.output_json = output
        run.citations_valid = all_valid
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.error = None

        await self.db.commit()
        await self.db.refresh(run)
        logger.info(
            "run_completed_scoped",
            run_id=str(run.id),
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            citations_valid=run.citations_valid,
            shrunk=budget_result.shrunk,
            items_sent_count=len(items_for_citations),
            digest_path=use_digest,
            retry_count=retry_count,
            stripped_count=stripped_count,
        )
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
        lower_ref_index = {k.strip().lower(): v for k, v in ref_index.items()}

        def refs(ids: list[str]) -> list[dict[str, Any]]:
            return [
                lower_ref_index[i.strip().lower()]
                for i in ids
                if i.strip().lower() in lower_ref_index
            ]

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
        daily_counts: list[dict[str, Any]] = []
        activity_map: dict[str, int] = {}
        total_runs = 0

        rows = result.all() if hasattr(result, "all") else result
        for row in rows:
            if isinstance(row, (tuple, list)):
                day_val, run_count = row[0], row[1]
            else:
                day_val = getattr(row, "day", row[0] if hasattr(row, "__getitem__") else row)
                run_count = getattr(row, "count", row[1] if hasattr(row, "__getitem__") else 0)
            day_str = day_val.isoformat() if hasattr(day_val, "isoformat") else str(day_val)
            c = int(run_count)
            daily_counts.append({"date": day_str, "count": c})
            activity_map[day_str] = c
            total_runs += c

        return {
            "total_runs": total_runs,
            "daily_counts": daily_counts,
            "activity_map": activity_map,
        }
