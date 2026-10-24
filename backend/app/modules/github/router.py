from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_workspace
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.github.schemas import (
    GithubAccountLinkRequest,
    GithubAuthorizationResponse,
    GithubCallbackRequest,
    GithubClientOption,
    GithubConnectionStatus,
    GithubProviderAccountResponse,
    GithubRepositoryResponse,
    GithubRepositorySelectionRequest,
    GithubRepositorySelectionResponse,
    GithubSyncResponse,
)
from app.modules.github.service import GithubConnectionService
from app.modules.github.sync import enqueue_repository_sync, repositories_for_sync
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="/connections/github", tags=["github"])


def _service(
    db: AsyncSession,
    workspace_context: tuple[Workspace, Membership],
) -> GithubConnectionService:
    workspace, membership = workspace_context
    return GithubConnectionService(db, workspace.id, membership.user_id)


@router.get("/authorize", response_model=GithubAuthorizationResponse)
async def authorize(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GithubAuthorizationResponse:
    return GithubAuthorizationResponse(
        authorization_url=await _service(db, workspace_context).authorization_url()
    )


@router.post("/callback", response_model=GithubConnectionStatus)
async def complete_authorization(
    payload: GithubCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GithubConnectionStatus:
    return await GithubConnectionService(
        db, payload.workspace_id, current_user.id
    ).complete_authorization(
        code=payload.code,
        state=payload.state,
    )


@router.get("", response_model=GithubConnectionStatus)
async def connection_status(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GithubConnectionStatus:
    return await _service(db, workspace_context).status()


@router.get("/accounts", response_model=list[GithubProviderAccountResponse])
async def list_accounts(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[GithubProviderAccountResponse]:
    return await _service(db, workspace_context).list_accounts()


@router.get("/clients", response_model=list[GithubClientOption])
async def list_workspace_clients(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[GithubClientOption]:
    return await _service(db, workspace_context).list_clients()


@router.post("/accounts/link", response_model=GithubConnectionStatus)
async def link_account(
    payload: GithubAccountLinkRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GithubConnectionStatus:
    return await _service(db, workspace_context).link_account(payload.account_id)


@router.delete("", response_model=GithubConnectionStatus)
async def disconnect(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GithubConnectionStatus:
    return await _service(db, workspace_context).disconnect()


@router.get("/repositories", response_model=list[GithubRepositoryResponse])
async def list_repositories(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[GithubRepositoryResponse]:
    return await _service(db, workspace_context).list_repositories()


@router.post("/repositories/refresh", response_model=list[GithubRepositoryResponse])
async def refresh_repositories(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[GithubRepositoryResponse]:
    return await _service(db, workspace_context).refresh_repositories()


@router.put("/repositories", response_model=GithubRepositorySelectionResponse)
async def save_repository_selections(
    payload: GithubRepositorySelectionRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GithubRepositorySelectionResponse:
    service = _service(db, workspace_context)
    saved = await service.save_repositories(payload)
    workspace, _ = workspace_context
    connection = await service.connections.get_provider_connection(
        workspace.id, service.provider, service.user_id
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Connect a GitHub account first.")
    repositories = await repositories_for_sync(db, workspace.id, connection.id)
    await db.commit()
    for repository in repositories:
        await enqueue_repository_sync(repository.id)
    return GithubRepositorySelectionResponse(saved=saved)


@router.post("/sync", response_model=GithubSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def sync_repositories(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GithubSyncResponse:
    service = _service(db, workspace_context)
    workspace, _ = workspace_context
    connection = await service.connections.get_provider_connection(
        workspace.id, service.provider, service.user_id
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Connect a GitHub account first.")
    repositories = await repositories_for_sync(db, workspace.id, connection.id)
    for repository in repositories:
        repository.sync_status = "running"
        repository.sync_error = None
    await db.commit()
    for repository in repositories:
        await enqueue_repository_sync(repository.id)
    return GithubSyncResponse(scheduled=len(repositories))
