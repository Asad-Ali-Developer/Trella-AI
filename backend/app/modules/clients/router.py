"""FastAPI router for Workspace Clients, Profiles, and Timelines."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_workspace
from app.db.session import get_db
from app.modules.clients.schemas import (
    ClientCreateRequest,
    ClientProfileResponse,
    ClientSummaryResponse,
    TimelineEvent,
)
from app.modules.clients.service import ClientService
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientSummaryResponse])
async def list_clients(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[ClientSummaryResponse]:
    """List all clients in current workspace with cards, insights, and risk metrics."""
    workspace, _ = workspace_context
    service = ClientService(db)
    return await service.list_clients(workspace_id=workspace.id)


@router.post("", response_model=ClientSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreateRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ClientSummaryResponse:
    """Create a new client entity in the active workspace."""
    workspace, _ = workspace_context
    service = ClientService(db)
    return await service.create_client(workspace_id=workspace.id, name=payload.name)


@router.get("/{client_id}", response_model=ClientProfileResponse)
async def get_client_profile(
    client_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ClientProfileResponse:
    """Fetch complete client profile including needs, patterns, stakeholders, risks, and timeline."""
    workspace, _ = workspace_context
    service = ClientService(db)
    return await service.get_client_profile(workspace_id=workspace.id, client_id=client_id)


@router.get("/{client_id}/timeline", response_model=list[TimelineEvent])
async def get_client_timeline(
    client_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[TimelineEvent]:
    """Fetch chronological event timeline (runs, cards, commits, risks) for a specific client."""
    workspace, _ = workspace_context
    service = ClientService(db)
    return await service.get_timeline(workspace_id=workspace.id, client_id=client_id)
