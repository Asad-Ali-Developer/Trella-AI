import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_workspace
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.jira.models import JiraOAuthState
from app.modules.jira.schemas import (
    JiraAccountLinkRequest,
    JiraApiTokenConnectRequest,
    JiraAuthorizationResponse,
    JiraCallbackRequest,
    JiraClientOption,
    JiraConnectionStatus,
    JiraConnectionTestRequest,
    JiraConnectionTestResponse,
    JiraProjectResponse,
    JiraProjectSelectionRequest,
    JiraProviderAccountResponse,
    JiraSyncResponse,
)
from app.modules.jira.service import JiraConnectionService
from app.modules.jira.sync import enqueue_jira_project_sync, projects_for_sync
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="/connections/jira", tags=["jira"])


def _service(
    db: AsyncSession,
    workspace_context: tuple[Workspace, Membership],
) -> JiraConnectionService:
    workspace, membership = workspace_context
    return JiraConnectionService(db, workspace.id, membership.user_id)


@router.get("/authorize", response_model=JiraAuthorizationResponse)
async def authorize(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraAuthorizationResponse:
    """Generate Atlassian OAuth 2.0 authorization URL."""
    return JiraAuthorizationResponse(
        authorization_url=await _service(db, workspace_context).authorization_url()
    )


@router.post("/callback", response_model=JiraConnectionStatus)
async def complete_authorization(
    payload: JiraCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectionStatus:
    """Complete Atlassian OAuth authorization using code and anti-CSRF state."""
    workspace_id = payload.workspace_id
    if workspace_id is None:
        state_hash = hashlib.sha256(payload.state.encode("ascii")).hexdigest()
        saved_state = await db.scalar(
            select(JiraOAuthState).where(
                JiraOAuthState.state_hash == state_hash,
                JiraOAuthState.user_id == current_user.id,
            )
        )
        if saved_state is not None:
            workspace_id = saved_state.workspace_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Jira authorization state is invalid or expired. Start the connection again.",
            )

    return await JiraConnectionService(
        db, workspace_id, current_user.id
    ).complete_authorization(
        code=payload.code,
        state=payload.state,
    )


@router.post("", response_model=JiraConnectionStatus)
async def connect_api_token(
    payload: JiraApiTokenConnectRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectionStatus:
    """Save and verify a Jira Cloud API token connection for the active workspace."""
    return await _service(db, workspace_context).connect_api_token(payload)


@router.post("/test", response_model=JiraConnectionTestResponse)
async def test_connection(
    payload: JiraConnectionTestRequest | None = None,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectionTestResponse:
    """Test provided Jira Cloud credentials or the currently saved workspace connection."""
    return await _service(db, workspace_context).test_connection(payload)


@router.get("", response_model=JiraConnectionStatus)
async def connection_status(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectionStatus:
    """Check Jira connection status for the active workspace."""
    return await _service(db, workspace_context).status()


@router.get("/accounts", response_model=list[JiraProviderAccountResponse])
async def list_accounts(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[JiraProviderAccountResponse]:
    """List reusable Jira accounts previously authorized by the user."""
    return await _service(db, workspace_context).list_accounts()


@router.get("/clients", response_model=list[JiraClientOption])
async def list_workspace_clients(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[JiraClientOption]:
    """List clients defined in workspace for project mapping."""
    return await _service(db, workspace_context).list_clients()


@router.post("/accounts/link", response_model=JiraConnectionStatus)
async def link_account(
    payload: JiraAccountLinkRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectionStatus:
    """Link an already-authorized Jira account to the current workspace."""
    return await _service(db, workspace_context).link_account(payload.account_id)


@router.delete("", response_model=JiraConnectionStatus)
async def disconnect(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectionStatus:
    """Disconnect Jira from the active workspace."""
    return await _service(db, workspace_context).disconnect()


@router.get("/projects", response_model=list[JiraProjectResponse])
async def list_projects(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[JiraProjectResponse]:
    """Fetch projects from the linked Jira Cloud site."""
    return await _service(db, workspace_context).list_projects()


@router.put("/projects", response_model=list[JiraProjectResponse])
async def save_project_selections(
    payload: JiraProjectSelectionRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[JiraProjectResponse]:
    """Save inclusion selections and client mapping for Jira projects, then enqueue sync for included projects."""
    service = _service(db, workspace_context)
    responses = await service.save_projects(payload)
    workspace, _ = workspace_context
    connection = await service.connections.get_provider_connection(
        workspace.id, service.provider, service.user_id
    )
    if connection is not None:
        projects = await projects_for_sync(db, workspace.id, connection.id)
        for project in projects:
            await enqueue_jira_project_sync(project.id)
    return responses


@router.post("/sync", response_model=JiraSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def sync_projects(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> JiraSyncResponse:
    """Manually trigger synchronization for all included Jira projects in the workspace."""
    service = _service(db, workspace_context)
    workspace, _ = workspace_context
    connection = await service.connections.get_provider_connection(
        workspace.id, service.provider, service.user_id
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connect a Jira account first.",
        )
    projects = await projects_for_sync(db, workspace.id, connection.id)
    for project in projects:
        project.sync_status = "running"
        project.sync_error = None
    await db.commit()
    for project in projects:
        await enqueue_jira_project_sync(project.id)
    return JiraSyncResponse(scheduled=len(projects))

