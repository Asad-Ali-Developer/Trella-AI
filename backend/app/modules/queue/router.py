import asyncio
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.deps import get_current_workspace
from app.db.session import get_db
from app.modules.context.models import ContextChunkRecord
from app.modules.github.models import GithubRepository
from app.modules.queue.schemas import QueueItem, QueueStatusResponse, RecentRunItem
from app.modules.runs.models import Run
from app.modules.skills.models import Skill
from app.modules.trello.models import TrelloCard, TrelloSource
from app.modules.trello.sync import enqueue_source_sync
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="/queue", tags=["queue"])


async def _check_celery_worker() -> tuple[bool, str | None]:
    """Check whether at least one Celery worker is responsive."""
    try:
        def _ping() -> Any:
            return celery_app.control.ping(timeout=0.6)

        responses = await asyncio.to_thread(_ping)
        if responses and isinstance(responses, list):
            for entry in responses:
                if isinstance(entry, dict):
                    for worker_name, status_dict in entry.items():
                        if isinstance(status_dict, dict) and status_dict.get("ok") == "pong":
                            return True, str(worker_name)
        return False, None
    except Exception:
        return False, None


async def _get_redis_queue_length() -> tuple[bool, int]:
    """Check Redis connection and return Celery queue backlog."""
    try:
        redis_client = Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            length = await redis_client.llen("celery")
            return True, int(length)
        finally:
            await redis_client.aclose()
    except Exception:
        return False, 0


@router.get("/status", response_model=QueueStatusResponse)
async def get_queue_status(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> QueueStatusResponse:
    """Retrieve full background sync & queue health status for current workspace."""
    workspace, _ = workspace_context

    # 1. Inspect worker and Redis health
    worker_online_task = asyncio.create_task(_check_celery_worker())
    redis_queue_task = asyncio.create_task(_get_redis_queue_length())

    # 2. Fetch Trello sources
    sources_query = (
        select(TrelloSource)
        .where(TrelloSource.workspace_id == workspace.id)
        .order_by(TrelloSource.created_at.desc())
    )
    sources = list((await db.scalars(sources_query)).all())

    # 3. Fetch GitHub repositories
    repos_query = (
        select(GithubRepository)
        .where(GithubRepository.workspace_id == workspace.id)
        .order_by(GithubRepository.created_at.desc())
    )
    repos = list((await db.scalars(repos_query)).all())

    # 4. Total Chunks in Workspace
    total_chunks = await db.scalar(
        select(func.count(ContextChunkRecord.id)).where(
            ContextChunkRecord.workspace_id == workspace.id
        )
    ) or 0

    items: list[QueueItem] = []
    syncing_count = 0

    for src in sources:
        card_count = await db.scalar(
            select(func.count(TrelloCard.id)).where(TrelloCard.source_id == src.id)
        ) or 0
        chunk_count = await db.scalar(
            select(func.count(ContextChunkRecord.id)).where(
                ContextChunkRecord.source_id == src.id
            )
        ) or 0

        # Map status
        src_status = src.sync_status
        if src_status == "running":
            syncing_count += 1
        elif src_status not in ("running", "completed", "failed"):
            src_status = "not_started"

        items.append(
            QueueItem(
                id=str(src.id),
                name=src.name,
                source_type="trello",
                status=cast(Any, src_status),
                last_synced_at=src.last_synced_at,
                sync_error=src.sync_error,
                items_count=card_count,
                chunks_count=chunk_count,
            )
        )

    for repo in repos:
        repo_status = repo.sync_status
        if repo_status == "running":
            syncing_count += 1
        elif repo_status not in ("running", "completed", "failed"):
            repo_status = "not_started"

        items.append(
            QueueItem(
                id=str(repo.id),
                name=repo.full_name,
                source_type="github",
                status=cast(Any, repo_status),
                last_synced_at=repo.last_synced_at,
                sync_error=repo.sync_error,
                items_count=0,
                chunks_count=0,
            )
        )

    # 5. Recent Skill Runs
    runs_query = (
        select(Run, Skill.name.label("skill_name"))
        .outerjoin(Skill, Run.skill_id == Skill.id)
        .where(Run.workspace_id == workspace.id)
        .order_by(Run.created_at.desc())
        .limit(8)
    )
    runs_res = (await db.execute(runs_query)).all()
    recent_runs: list[RecentRunItem] = []
    for r, skill_name in runs_res:
        recent_runs.append(
            RecentRunItem(
                id=str(r.id),
                skill_name=skill_name or "Custom Skill",
                status=r.status,
                trigger=r.trigger,
                created_at=r.created_at,
                completed_at=r.completed_at,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                cost_usd=r.cost_usd,
                error=r.error,
            )
        )

    (is_worker_online, worker_name) = await worker_online_task
    (redis_connected, celery_queue_length) = await redis_queue_task

    return QueueStatusResponse(
        is_worker_online=is_worker_online,
        redis_connected=redis_connected,
        celery_queue_length=celery_queue_length,
        syncing_count=syncing_count,
        worker_name=worker_name,
        items=items,
        recent_runs=recent_runs,
        total_chunks=total_chunks,
        last_checked_at=datetime.now(UTC),
    )


@router.post("/sync-all", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync_all(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Trigger background sync for all included workspace sources."""
    workspace, _ = workspace_context
    sources = list(
        (
            await db.scalars(
                select(TrelloSource).where(
                    TrelloSource.workspace_id == workspace.id,
                    TrelloSource.excluded.is_(False),
                )
            )
        ).all()
    )

    scheduled = 0
    for src in sources:
        src.sync_status = "running"
        src.sync_error = None
        scheduled += 1
    await db.commit()

    for src in sources:
        await enqueue_source_sync(src.id)

    return {"scheduled": scheduled}
