"""Service layer for Slack connection lifecycle and channel retrieval."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security.encryption import decrypt_secret, encrypt_secret
from app.modules.connections.models import ProviderAccount, SlackOAuthState, WorkspaceConnection
from app.modules.delivery.schemas import (
    SlackChannelResponse,
    SlackConnectionStatus,
)
from app.modules.delivery.slack import SlackAPIError, SlackClient

logger = get_logger("app.modules.delivery.service")

STATE_EXPIRES_MINUTES = 15


class SlackConnectionService:
    """Manages workspace-scoped Slack connections and channel listings."""

    def __init__(self, db: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id

    async def authorization_url(self) -> str:
        """Generate single-use OAuth state and return Slack OAuth 2.0 authorization URL."""
        if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Slack OAuth credentials are not configured in environment.",
            )

        raw_state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(raw_state.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(minutes=STATE_EXPIRES_MINUTES)

        oauth_state = SlackOAuthState(
            state_hash=state_hash,
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            expires_at=expires_at,
        )
        self.db.add(oauth_state)
        await self.db.commit()

        redirect_uri = settings.SLACK_CALLBACK_URL
        return (
            f"https://slack.com/oauth/v2/authorize"
            f"?client_id={settings.SLACK_CLIENT_ID}"
            f"&scope={settings.SLACK_SCOPES}"
            f"&redirect_uri={redirect_uri}"
            f"&state={raw_state}"
        )

    async def complete_authorization(self, code: str, state: str) -> SlackConnectionStatus:
        """Validate state, exchange code for bot token, and link workspace connection."""
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        query = select(SlackOAuthState).where(
            SlackOAuthState.state_hash == state_hash,
            SlackOAuthState.workspace_id == self.workspace_id,
            SlackOAuthState.user_id == self.user_id,
        )
        res = await self.db.execute(query)
        stored_state = res.scalar_one_or_none()

        if stored_state is None or stored_state.expires_at < datetime.now(UTC):
            if stored_state is not None:
                await self.db.delete(stored_state)
                await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Slack authorization session is invalid or has expired.",
            )

        await self.db.delete(stored_state)

        # Exchange code with Slack
        slack_client = SlackClient()
        try:
            token_payload = await slack_client.exchange_code(
                code=code,
                redirect_uri=settings.SLACK_CALLBACK_URL,
            )
        except SlackAPIError as exc:
            logger.error("slack_oauth_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slack authorization rejected: {exc}",
            ) from exc

        bot_token = token_payload.get("access_token")
        team = token_payload.get("team", {})
        team_id = team.get("id") or "slack_team"
        team_name = team.get("name") or "Slack Workspace"
        bot_user_id = token_payload.get("bot_user_id") or ""

        if not bot_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No bot access token returned from Slack.",
            )

        encrypted_token = encrypt_secret(bot_token)

        # Find or create ProviderAccount
        account_query = select(ProviderAccount).where(
            ProviderAccount.user_id == self.user_id,
            ProviderAccount.provider == "slack",
            ProviderAccount.external_account_id == team_id,
        )
        account = (await self.db.execute(account_query)).scalar_one_or_none()
        if account is None:
            account = ProviderAccount(
                user_id=self.user_id,
                provider="slack",
                encrypted_token=encrypted_token,
                status="active",
                external_account_id=team_id,
                external_username=team_name,
            )
            self.db.add(account)
            await self.db.flush()
        else:
            account.encrypted_token = encrypted_token
            account.status = "active"
            account.external_username = team_name

        # Find or create WorkspaceConnection
        conn_query = select(WorkspaceConnection).where(
            WorkspaceConnection.workspace_id == self.workspace_id,
            WorkspaceConnection.provider == "slack",
            WorkspaceConnection.user_id == self.user_id,
        )
        conn = (await self.db.execute(conn_query)).scalar_one_or_none()
        if conn is None:
            conn = WorkspaceConnection(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                provider="slack",
                status="active",
                provider_account_id=account.id,
            )
            self.db.add(conn)
        else:
            conn.status = "active"
            conn.provider_account_id = account.id

        await self.db.commit()

        # Send app connected email notification
        from app.workers.tasks import notify_app_connected

        await notify_app_connected(
            db=self.db,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            app_name="Slack",
            account_username=team_name,
            app_color="#4A154B",
        )

        return SlackConnectionStatus(
            connected=True,
            workspace_id=self.workspace_id,
            team_id=team_id,
            team_name=team_name,
            bot_user_id=bot_user_id,
            status="active",
            updated_at=datetime.now(UTC),
        )

    async def status(self) -> SlackConnectionStatus:
        """Return current status of Slack integration for this workspace."""
        query = (
            select(WorkspaceConnection, ProviderAccount)
            .join(ProviderAccount, WorkspaceConnection.provider_account_id == ProviderAccount.id)
            .where(
                WorkspaceConnection.workspace_id == self.workspace_id,
                WorkspaceConnection.provider == "slack",
                WorkspaceConnection.status == "active",
            )
        )
        res = await self.db.execute(query)
        row = res.first()

        if not row:
            return SlackConnectionStatus(connected=False, status="disconnected")

        conn, account = row
        return SlackConnectionStatus(
            connected=True,
            workspace_id=self.workspace_id,
            team_id=account.external_account_id,
            team_name=account.external_username,
            status=conn.status,
            updated_at=conn.updated_at,
        )

    async def list_channels(self) -> list[SlackChannelResponse]:
        """Fetch list of public and private Slack channels accessible to the bot."""
        query = (
            select(WorkspaceConnection, ProviderAccount)
            .join(ProviderAccount, WorkspaceConnection.provider_account_id == ProviderAccount.id)
            .where(
                WorkspaceConnection.workspace_id == self.workspace_id,
                WorkspaceConnection.provider == "slack",
                WorkspaceConnection.status == "active",
            )
        )
        res = await self.db.execute(query)
        row = res.first()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slack is not connected to this workspace.",
            )

        _, account = row
        bot_token = decrypt_secret(account.encrypted_token)
        client = SlackClient(token=bot_token)

        try:
            channels_raw = await client.list_conversations()
            return [
                SlackChannelResponse(
                    id=ch["id"],
                    name=ch["name"],
                    is_private=ch.get("is_private", False),
                    is_channel=ch.get("is_channel", True),
                    num_members=ch.get("num_members", 0),
                    topic=ch.get("topic", ""),
                )
                for ch in channels_raw
            ]
        except SlackAPIError as exc:
            logger.error("slack_list_channels_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch channels from Slack: {exc}",
            ) from exc

    async def disconnect(self) -> SlackConnectionStatus:
        """Disconnect Slack integration from the workspace."""
        query = select(WorkspaceConnection).where(
            WorkspaceConnection.workspace_id == self.workspace_id,
            WorkspaceConnection.provider == "slack",
        )
        res = await self.db.execute(query)
        conn = res.scalar_one_or_none()
        if conn:
            conn.status = "disconnected"
            await self.db.commit()

        return SlackConnectionStatus(
            connected=False,
            workspace_id=self.workspace_id,
            status="disconnected",
        )
