"""Business logic service for Client Profiles, Insights Aggregation, and Timelines."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.clients.schemas import (
    ClientProfileResponse,
    ClientSummaryResponse,
    TimelineEvent,
)
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.runs.models import Insight, Run
from app.modules.runs.schemas import InsightResponse, RunResponse
from app.modules.skills.models import Skill
from app.modules.trello.models import TrelloCard, TrelloClientRecord

logger = get_logger("app.modules.clients.service")


class ClientService:
    """Service for managing workspace clients and generating deep client profiles."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_clients(self, workspace_id: UUID) -> list[ClientSummaryResponse]:
        """List all clients in a workspace with computed metrics (cards, insights, risks, last run)."""
        clients_query = (
            select(TrelloClientRecord)
            .where(TrelloClientRecord.workspace_id == workspace_id)
            .order_by(TrelloClientRecord.name.asc())
        )
        clients = list((await self.db.scalars(clients_query)).all())

        results: list[ClientSummaryResponse] = []
        for client in clients:
            # 1. Total cards count
            cards_count = (
                await self.db.scalar(
                    select(func.count(TrelloCard.id)).where(
                        TrelloCard.workspace_id == workspace_id,
                        TrelloCard.client_id == client.id,
                    )
                )
                or 0
            )

            # 2. Total insights count
            insights_count = (
                await self.db.scalar(
                    select(func.count(Insight.id)).where(
                        Insight.workspace_id == workspace_id,
                        Insight.client_id == client.id,
                    )
                )
                or 0
            )

            # 3. Needs count
            needs_count = (
                await self.db.scalar(
                    select(func.count(Insight.id)).where(
                        Insight.workspace_id == workspace_id,
                        Insight.client_id == client.id,
                        Insight.category == "need",
                    )
                )
                or 0
            )

            # 4. Risks count
            risks_count = (
                await self.db.scalar(
                    select(func.count(Insight.id)).where(
                        Insight.workspace_id == workspace_id,
                        Insight.client_id == client.id,
                        Insight.category == "risk",
                    )
                )
                or 0
            )

            # 5. Last run timestamp
            last_run = await self.db.scalar(
                select(func.max(Run.completed_at)).where(
                    Run.workspace_id == workspace_id,
                    Run.client_id == client.id,
                    Run.status == "completed",
                )
            )

            results.append(
                ClientSummaryResponse(
                    id=client.id,
                    workspace_id=client.workspace_id,
                    name=client.name,
                    cards_count=cards_count,
                    insights_count=insights_count,
                    needs_count=needs_count,
                    risks_count=risks_count,
                    last_run_at=last_run,
                    created_at=client.created_at,
                    updated_at=client.updated_at,
                )
            )

        return results

    async def get_client_profile(
        self,
        workspace_id: UUID,
        client_id: UUID,
    ) -> ClientProfileResponse:
        """Build deep client profile with needs, patterns, stakeholders, risks, and timeline."""
        client = await self.db.scalar(
            select(TrelloClientRecord).where(
                TrelloClientRecord.id == client_id,
                TrelloClientRecord.workspace_id == workspace_id,
            )
        )
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client '{client_id}' not found in this workspace.",
            )

        # 1. Fetch all insights for this client (or from runs targeting this client)
        insights_query = (
            select(Insight)
            .where(
                Insight.workspace_id == workspace_id,
                Insight.client_id == client_id,
            )
            .order_by(Insight.created_at.desc())
        )
        all_insights = list((await self.db.scalars(insights_query)).all())

        # Categorize insights
        needs: list[InsightResponse] = []
        patterns: list[InsightResponse] = []
        stakeholders: list[InsightResponse] = []
        risks: list[InsightResponse] = []

        for item in all_insights:
            resp = InsightResponse.model_validate(item)
            if item.category == "need":
                needs.append(resp)
            elif item.category == "pattern":
                patterns.append(resp)
            elif item.category == "stakeholder":
                stakeholders.append(resp)
            elif item.category == "risk":
                risks.append(resp)

        # 2. Fetch recent runs targeting this client (or workspace runs)
        runs_query = (
            select(Run)
            .where(
                Run.workspace_id == workspace_id,
                Run.client_id == client_id,
            )
            .order_by(Run.created_at.desc())
            .limit(10)
        )
        recent_runs_models = list((await self.db.scalars(runs_query)).all())
        recent_runs = [RunResponse.model_validate(r) for r in recent_runs_models]

        # 3. Card counts
        total_cards = (
            await self.db.scalar(
                select(func.count(TrelloCard.id)).where(
                    TrelloCard.workspace_id == workspace_id,
                    TrelloCard.client_id == client_id,
                )
            )
            or 0
        )

        # 4. Generate Chronological Timeline
        timeline = await self.get_timeline(workspace_id=workspace_id, client_id=client_id)

        # 5. Summary Response
        summary = ClientSummaryResponse(
            id=client.id,
            workspace_id=client.workspace_id,
            name=client.name,
            cards_count=total_cards,
            insights_count=len(all_insights),
            needs_count=len(needs),
            risks_count=len(risks),
            last_run_at=recent_runs[0].completed_at if recent_runs else None,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )

        return ClientProfileResponse(
            client=summary,
            total_cards=total_cards,
            total_insights=len(all_insights),
            needs=needs,
            patterns=patterns,
            stakeholders=stakeholders,
            risks=risks,
            timeline=timeline,
            recent_runs=recent_runs,
        )

    async def get_timeline(
        self,
        workspace_id: UUID,
        client_id: UUID,
    ) -> list[TimelineEvent]:
        """Aggregate chronological timeline across cards, git commits, analysis runs, and detected risks."""
        events: list[TimelineEvent] = []

        # 1. Skill Runs Timeline Events
        runs = list(
            (
                await self.db.scalars(
                    select(Run)
                    .where(Run.workspace_id == workspace_id, Run.client_id == client_id)
                    .order_by(Run.created_at.desc())
                    .limit(20)
                )
            ).all()
        )
        for r in runs:
            timestamp = r.completed_at or r.started_at or r.created_at
            events.append(
                TimelineEvent(
                    id=f"run-{r.id}",
                    event_type="skill_run",
                    title=f"AI Skill Run ({r.status.upper()})",
                    detail=f"Tokens: {r.tokens_in + r.tokens_out:,} | Cost: ${r.cost_usd:.5f}",
                    timestamp=timestamp,
                    source="ai_skill",
                    severity_or_priority="high" if r.status == "failed" else None,
                    metadata={"run_id": str(r.id), "status": r.status},
                )
            )

        # 2. Trello Cards Activity Events
        cards = list(
            (
                await self.db.scalars(
                    select(TrelloCard)
                    .where(TrelloCard.workspace_id == workspace_id, TrelloCard.client_id == client_id)
                    .order_by(TrelloCard.last_activity_at.desc().nulls_last())
                    .limit(30)
                )
            ).all()
        )
        for c in cards:
            ts = c.last_activity_at or c.created_at or datetime.now(UTC)
            events.append(
                TimelineEvent(
                    id=f"card-{c.id}",
                    event_type="card_activity",
                    title=f"Card: {c.name}",
                    detail=f"List: {c.list_name or 'Default'} | {c.description[:120] if c.description else 'No description'}",
                    timestamp=ts,
                    source="trello",
                    source_url=c.url,
                    metadata={"card_id": str(c.id), "list_name": c.list_name},
                )
            )

        # 3. Git Commits Events
        repos = list(
            (
                await self.db.scalars(
                    select(GithubRepository).where(
                        GithubRepository.workspace_id == workspace_id,
                        GithubRepository.client_id == client_id,
                    )
                )
            ).all()
        )
        if repos:
            repo_ids = [repo.id for repo in repos]
            commits = list(
                (
                    await self.db.scalars(
                        select(GithubCommit)
                        .where(GithubCommit.workspace_id == workspace_id, GithubCommit.repository_id.in_(repo_ids))
                        .order_by(GithubCommit.committed_at.desc())
                        .limit(20)
                    )
                ).all()
            )
            for cm in commits:
                events.append(
                    TimelineEvent(
                        id=f"commit-{cm.id}",
                        event_type="commit",
                        title=f"Commit: {cm.sha[:7]} - {cm.message.splitlines()[0] if cm.message else ''}",
                        detail=f"Author: {cm.author_name} (+{cm.additions}/-{cm.deletions})",
                        timestamp=cm.committed_at,
                        source="github",
                        source_url=cm.url,
                        metadata={"sha": cm.sha, "author": cm.author_name},
                    )
                )

        # 4. Detected Risks Timeline Events
        risks = list(
            (
                await self.db.scalars(
                    select(Insight)
                    .where(
                        Insight.workspace_id == workspace_id,
                        Insight.client_id == client_id,
                        Insight.category == "risk",
                    )
                    .order_by(Insight.created_at.desc())
                    .limit(15)
                )
            ).all()
        )
        for rk in risks:
            events.append(
                TimelineEvent(
                    id=f"risk-{rk.id}",
                    event_type="risk_identified",
                    title=f"Risk: {rk.title}",
                    detail=rk.detail[:160],
                    timestamp=rk.created_at,
                    source="ai_skill",
                    severity_or_priority=rk.severity_or_priority or "medium",
                    metadata={"insight_id": str(rk.id)},
                )
            )

        # Sort all events chronologically descending
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events

    async def create_client(self, workspace_id: UUID, name: str) -> ClientSummaryResponse:
        """Create a new client entity in the workspace."""
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Client name cannot be empty.",
            )

        existing = await self.db.scalar(
            select(TrelloClientRecord).where(
                TrelloClientRecord.workspace_id == workspace_id,
                TrelloClientRecord.name == clean_name,
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A client named '{clean_name}' already exists in this workspace.",
            )

        client = TrelloClientRecord(
            workspace_id=workspace_id,
            name=clean_name,
        )
        self.db.add(client)
        await self.db.commit()
        await self.db.refresh(client)

        logger.info("client_created", workspace_id=str(workspace_id), client_id=str(client.id), name=clean_name)
        return ClientSummaryResponse(
            id=client.id,
            workspace_id=client.workspace_id,
            name=client.name,
            cards_count=0,
            insights_count=0,
            needs_count=0,
            risks_count=0,
            last_run_at=None,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )
