import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceWithRoleResponse,
)
from app.modules.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post(
    "",
    response_model=WorkspaceWithRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workspace",
)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceWithRoleResponse:
    """Create a new tenant workspace and assign current user as OWNER."""
    service = WorkspaceService(db)
    return await service.create_workspace(payload, current_user)


@router.get(
    "",
    response_model=list[WorkspaceWithRoleResponse],
    status_code=status.HTTP_200_OK,
    summary="List workspaces for current user",
)
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceWithRoleResponse]:
    """Retrieve all workspaces where current user has active membership."""
    service = WorkspaceService(db)
    return await service.list_user_workspaces(current_user)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceWithRoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get workspace details",
)
async def get_workspace(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceWithRoleResponse:
    """Get details for a specific workspace if user is a member."""
    service = WorkspaceService(db)
    return await service.get_workspace_details(workspace_id, current_user)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceWithRoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update workspace details",
)
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceWithRoleResponse:
    service = WorkspaceService(db)
    return await service.update_workspace(workspace_id, payload, current_user)
