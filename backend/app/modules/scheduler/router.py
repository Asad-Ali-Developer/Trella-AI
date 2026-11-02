"""API router for managing Report Schedules and Delivery Audit Logs."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_workspace
from app.db.session import get_db
from app.modules.runs.models import Run
from app.modules.runs.schemas import RunResponse
from app.modules.scheduler.models import Schedule
from app.modules.scheduler.schemas import (
    DeliveryListResponse,
    DeliveryResponse,
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from app.modules.scheduler.service import ScheduleService
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreateRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Schedule:
    """Create a new recurring report schedule for the current workspace."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    return await service.create_schedule(workspace.id, payload)


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[Schedule]:
    """List all configured report schedules for the current workspace."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    return await service.list_schedules(workspace.id)


@router.get("/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> DeliveryListResponse:
    """List historical delivery audit records for the current workspace."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    deliveries, total = await service.list_deliveries(workspace.id, skip=skip, limit=limit)
    return DeliveryListResponse(
        deliveries=[DeliveryResponse.model_validate(d) for d in deliveries],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Schedule:
    """Retrieve details of a specific report schedule."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    return await service.get_schedule(schedule_id, workspace.id)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    payload: ScheduleUpdateRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Schedule:
    """Update settings or timing for an existing report schedule."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    return await service.update_schedule(schedule_id, workspace.id, payload)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a report schedule from the workspace."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    await service.delete_schedule(schedule_id, workspace.id)


@router.post("/{schedule_id}/run-now", response_model=RunResponse | None)
async def run_schedule_now(
    schedule_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Run | None:
    """Immediately trigger a scheduled run and dispatch its report delivery."""
    workspace, _ = workspace_context
    service = ScheduleService(db)
    # Ensure schedule belongs to current workspace
    await service.get_schedule(schedule_id, workspace.id)
    return await service.execute_scheduled_run(schedule_id)
