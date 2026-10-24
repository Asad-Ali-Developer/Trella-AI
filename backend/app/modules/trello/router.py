import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_current_workspace
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.trello.models import TrelloSource, TrelloWebhookEvent
from app.modules.trello.schemas import (
    TrelloAuthorizationResponse,
    TrelloBoardResponse,
    TrelloBoardSelectionRequest,
    TrelloBoardSelectionResponse,
    TrelloCallbackRequest,
    TrelloClientMappingRequest,
    TrelloClientMappingResponse,
    TrelloClientMappingSaveResponse,
    TrelloConnectionStatus,
    TrelloProviderAccountLinkRequest,
    TrelloProviderAccountResponse,
    TrelloSyncResponse,
    TrelloTokenCallbackRequest,
    TrelloWebhookResponse,
)
from app.modules.trello.service import TrelloConnectionService
from app.modules.trello.sync import (
    enqueue_source_sync,
    list_mapping_responses,
    replace_client_mappings,
    sources_for_sync,
)
from app.modules.trello.webhooks import verify_trello_webhook_signature
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


@router.post(
    "/token/callback", response_model=TrelloConnectionStatus, status_code=status.HTTP_200_OK
)
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


@router.get("/accounts", response_model=list[TrelloProviderAccountResponse])
async def list_trello_accounts(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[TrelloProviderAccountResponse]:
    return await _service(db, workspace_context).list_accounts()


@router.post("/accounts/link", response_model=TrelloConnectionStatus)
async def link_trello_account(
    payload: TrelloProviderAccountLinkRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloConnectionStatus:
    return await _service(db, workspace_context).link_account(payload.account_id)


@router.delete("", response_model=TrelloConnectionStatus)
async def disconnect_trello(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloConnectionStatus:
    return await _service(db, workspace_context).disconnect()


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
    service = _service(db, workspace_context)
    saved = await service.save_board_selections(payload)
    workspace, _ = workspace_context
    connection = await service._get_connection()
    sources = await sources_for_sync(db, workspace.id, connection.id)
    await db.commit()
    for source in sources:
        await enqueue_source_sync(source.id)
    return TrelloBoardSelectionResponse(saved=saved)


@router.post("/sync", response_model=TrelloSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def sync_boards(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloSyncResponse:
    workspace, _ = workspace_context
    connection = await _service(db, workspace_context)._get_connection()
    sources = await sources_for_sync(db, workspace.id, connection.id)
    for source in sources:
        await enqueue_source_sync(source.id)
    return TrelloSyncResponse(scheduled=len(sources))


@router.get("/clients", response_model=list[TrelloClientMappingResponse])
async def list_client_mappings(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[TrelloClientMappingResponse]:
    workspace, _ = workspace_context
    return [
        TrelloClientMappingResponse.model_validate(item)
        for item in await list_mapping_responses(db, workspace.id)
    ]


@router.put("/clients", response_model=TrelloClientMappingSaveResponse)
async def save_client_mappings(
    payload: TrelloClientMappingRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TrelloClientMappingSaveResponse:
    workspace, _ = workspace_context
    service = _service(db, workspace_context)
    connection = await service._get_connection()
    try:
        saved = await replace_client_mappings(
            db,
            workspace.id,
            connection.id,
            [item.model_dump() for item in payload.mappings],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    sources = await sources_for_sync(db, workspace.id, connection.id)
    await db.commit()
    for source in sources:
        await enqueue_source_sync(source.id)
    return TrelloClientMappingSaveResponse(saved=saved)


@router.head("/webhooks", include_in_schema=False)
@router.get("/webhooks", include_in_schema=False)
async def trello_webhook_handshake() -> None:
    return None


@router.post(
    "/webhooks",
    response_model=TrelloWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_trello_webhook(
    request: Request,
    x_trello_webhook: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> TrelloWebhookResponse:
    if not settings.TRELLO_WEBHOOK_SECRET or not settings.TRELLO_WEBHOOK_CALLBACK_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trello webhook verification is not configured.",
        )
    body = await request.body()
    if not verify_trello_webhook_signature(
        body,
        x_trello_webhook,
        settings.TRELLO_WEBHOOK_SECRET,
        settings.TRELLO_WEBHOOK_CALLBACK_URL,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )
    try:
        event: Any = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook body.",
        ) from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook body.")
    action = event.get("action")
    model = event.get("model")
    webhook = event.get("webhook")
    if not isinstance(action, dict) or not isinstance(model, dict) or not isinstance(webhook, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook event."
        )
    action_id = action.get("id")
    board_id = model.get("id")
    webhook_id = webhook.get("id")
    if not isinstance(action_id, str) or not isinstance(board_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook event."
        )

    result = await db.execute(
        select(TrelloSource).where(
            TrelloSource.trello_board_id == board_id,
            TrelloSource.excluded.is_(False),
            TrelloSource.webhook_id == webhook_id,
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown Trello webhook.")
    inserted = await db.execute(
        insert(TrelloWebhookEvent)
        .values(action_id=action_id, source_id=source.id)
        .on_conflict_do_nothing(index_elements=[TrelloWebhookEvent.action_id])
        .returning(TrelloWebhookEvent.action_id)
    )
    if inserted.scalar_one_or_none() is not None:
        await enqueue_source_sync(source.id)
        await db.commit()
    return TrelloWebhookResponse()
