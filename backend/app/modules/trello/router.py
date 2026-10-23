from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_workspace
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.trello.schemas import (
    TrelloAuthorizationResponse,
    TrelloBoardResponse,
    TrelloBoardSelectionRequest,
    TrelloBoardSelectionResponse,
    TrelloCallbackRequest,
    TrelloConnectionStatus,
    TrelloTokenCallbackRequest,
)
from app.modules.trello.service import TrelloConnectionService
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="/connections/trello", tags=["trello"])


def _service(
    db: AsyncSession,
    workspace_context: tuple[Workspace, Membership],
) -> TrelloConnectionService:
    workspace, membership = workspace_context
    return TrelloConnectionService(db, workspace.id, membership.user_id)


@router.get("/authorize", response_model=TrelloAuthorizationResponse)
async def authorize(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloAuthorizationResponse:
    service = _service(db, workspace_context)
    return TrelloAuthorizationResponse(authorization_url=await service.authorization_url())

@router.get("/token/authorize", response_model=TrelloAuthorizationResponse)
async def token_authorize(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloAuthorizationResponse:
    service = _service(db, workspace_context)
    return TrelloAuthorizationResponse(authorization_url=await service.token_authorization_url())


@router.post("/token/callback", response_model=TrelloConnectionStatus, status_code=status.HTTP_200_OK)
async def complete_token_authorization(
    payload: TrelloTokenCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrelloConnectionStatus:
    service = TrelloConnectionService(db, payload.workspace_id, current_user.id)
    return await service.complete_token_authorization(token=payload.token, state=payload.state)

@router.post("/callback", response_model=TrelloConnectionStatus, status_code=status.HTTP_200_OK)
async def complete_authorization(
    payload: TrelloCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrelloConnectionStatus:
    service = TrelloConnectionService(db, payload.workspace_id, current_user.id)
    return await service.complete_authorization(code=payload.code, state=payload.state)


@router.get("", response_model=TrelloConnectionStatus)
async def connection_status(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloConnectionStatus:
    return await _service(db, workspace_context).status()


@router.get("/boards", response_model=list[TrelloBoardResponse])
async def list_boards(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[TrelloBoardResponse]:
    return await _service(db, workspace_context).list_boards()


@router.put("/boards", response_model=TrelloBoardSelectionResponse)
async def save_board_selections(
    payload: TrelloBoardSelectionRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloBoardSelectionResponse:
    saved = await _service(db, workspace_context).save_board_selections(payload)
    return TrelloBoardSelectionResponse(saved=saved)
