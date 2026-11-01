"""API router for Slack connection OAuth, channel selection, and unsubscribe."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_workspace
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.delivery.schemas import (
    SlackAuthorizationResponse,
    SlackCallbackRequest,
    SlackChannelResponse,
    SlackConnectionStatus,
    UnsubscribeRequest,
    UnsubscribeResponse,
)
from app.modules.delivery.service import SlackConnectionService
from app.modules.workspaces.models import Membership, Workspace

router = APIRouter(prefix="", tags=["delivery"])


def _service(
    db: AsyncSession,
    workspace_context: tuple[Workspace, Membership],
) -> SlackConnectionService:
    workspace, membership = workspace_context
    return SlackConnectionService(db, workspace.id, membership.user_id)


@router.get("/connections/slack/authorize", response_model=SlackAuthorizationResponse)
async def authorize_slack(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SlackAuthorizationResponse:
    """Initiate Slack OAuth flow and return authorization URL."""
    service = _service(db, workspace_context)
    url = await service.authorization_url()
    return SlackAuthorizationResponse(authorization_url=url)


@router.post("/connections/slack/callback", response_model=SlackConnectionStatus)
async def complete_slack_authorization(
    payload: SlackCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SlackConnectionStatus:
    """Exchange temporary OAuth code for access token and connect Slack."""
    service = SlackConnectionService(db, payload.workspace_id, current_user.id)
    return await service.complete_authorization(code=payload.code, state=payload.state)


@router.get("/connections/slack", response_model=SlackConnectionStatus)
async def get_slack_status(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SlackConnectionStatus:
    """Get the active Slack integration status for this workspace."""
    service = _service(db, workspace_context)
    return await service.status()


@router.get("/connections/slack/channels", response_model=list[SlackChannelResponse])
async def list_slack_channels(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[SlackChannelResponse]:
    """List accessible Slack channels with privacy indicator for digest routing."""
    service = _service(db, workspace_context)
    return await service.list_channels()


@router.delete("/connections/slack", response_model=SlackConnectionStatus)
async def disconnect_slack(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SlackConnectionStatus:
    """Disconnect Slack from the workspace."""
    service = _service(db, workspace_context)
    return await service.disconnect()


@router.post("/delivery/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe(
    payload: UnsubscribeRequest,
    db: AsyncSession = Depends(get_db),
) -> UnsubscribeResponse:
    """Unsubscribe an email address from scheduled report digests."""
    from sqlalchemy import select

    from app.modules.scheduler.models import Schedule

    # Remove email from all schedule recipients
    query = select(Schedule)
    res = await db.execute(query)
    schedules = list(res.scalars().all())

    modified_count = 0
    email_clean = payload.email.strip().lower()
    for s in schedules:
        if email_clean in [r.lower() for r in (s.recipients or [])]:
            s.recipients = [r for r in s.recipients if r.lower() != email_clean]
            modified_count += 1

    if modified_count > 0:
        await db.commit()

    return UnsubscribeResponse(
        success=True,
        message=f"{payload.email} has been unsubscribed from scheduled digests.",
    )
