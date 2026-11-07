"""FastAPI router for Skill execution Runs and Insights."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_workspace
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.runs.schemas import (
    DailyActivityResponse,
    InsightFeedbackRequest,
    InsightResponse,
    RunCreateRequest,
    RunDetailResponse,
    RunResponse,
)
from app.modules.runs.service import RunService
from app.modules.workspaces.models import Membership, Workspace
from app.workers.tasks import dispatch_task, execute_skill_run_task

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreateRequest,
    execute_async: bool = Query(default=True, description="Enqueue for background worker execution"),
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Create a new skill run against workspace context, optionally enqueuing it immediately."""
    workspace, _ = workspace_context
    service = RunService(db)
    run = await service.create_run(
        workspace_id=workspace.id,
        user_id=current_user.id,
        request=payload,
    )

    if execute_async:
        await db.commit()
        dispatch_task(execute_skill_run_task, str(run.id))
    else:
        run = await service.execute_run(run.id)

    return RunResponse.model_validate(run)


@router.get("", response_model=list[RunResponse])
async def list_runs(
    client_id: UUID | None = None,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[RunResponse]:
    """List all skill runs for this workspace."""
    workspace, _ = workspace_context
    service = RunService(db)
    runs = await service.list_runs(workspace_id=workspace.id, client_id=client_id)
    return [RunResponse.model_validate(r) for r in runs]



@router.get("/activity", response_model=DailyActivityResponse)
async def get_runs_activity(
    days: int = Query(default=365, ge=7, le=730, description="Number of past days to aggregate activity for"),
    user_only: bool = Query(default=False, description="Filter only to current user's generated reports"),
    client_id: UUID | None = Query(default=None, description="Optional client filter"),
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyActivityResponse:
    """Retrieve daily aggregated run counts for heatmap visualization efficiently."""
    workspace, _ = workspace_context
    service = RunService(db)
    user_id = current_user.id if user_only else None
    data = await service.get_daily_activity(
        workspace_id=workspace.id,
        user_id=user_id,
        client_id=client_id,
        days=days,
    )
    return DailyActivityResponse.model_validate(data)


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> RunDetailResponse:
    """Retrieve full details, report payload, and insights for a specific run."""
    workspace, _ = workspace_context
    service = RunService(db)
    run = await service.get_run(run_id=run_id, workspace_id=workspace.id)
    return RunDetailResponse.model_validate(run)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a specific run and its associated insights."""
    workspace, _ = workspace_context
    service = RunService(db)
    await service.delete_run(run_id=run_id, workspace_id=workspace.id)


@router.post("/{run_id}/execute", response_model=RunResponse)
async def execute_run(
    run_id: UUID,
    execute_async: bool = Query(default=True),
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Trigger or re-trigger execution of a specific run."""
    workspace, _ = workspace_context
    service = RunService(db)
    # Validate run belongs to workspace
    run = await service.get_run(run_id=run_id, workspace_id=workspace.id)

    if execute_async:
        await db.commit()
        dispatch_task(execute_skill_run_task, str(run.id))
        return RunResponse.model_validate(run)
    else:
        executed_run = await service.execute_run(run.id)
        return RunResponse.model_validate(executed_run)


@router.post("/insights/{insight_id}/feedback", response_model=InsightResponse)
async def submit_insight_feedback(
    insight_id: UUID,
    payload: InsightFeedbackRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> InsightResponse:
    """Submit thumbs up / down feedback on an individual insight to feed quality evaluation."""
    workspace, _ = workspace_context
    service = RunService(db)
    insight = await service.submit_insight_feedback(
        insight_id=insight_id,
        workspace_id=workspace.id,
        feedback=payload.feedback,
        notes=payload.feedback_notes,
    )
    return InsightResponse.model_validate(insight)
