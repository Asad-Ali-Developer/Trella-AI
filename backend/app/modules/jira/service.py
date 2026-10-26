"""Workspace-scoped Jira connection and project synchronization service."""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security.encryption import encryption
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.jira.client import JiraAPIError, JiraClient, JiraOAuthClient, JiraOAuthTokens
from app.modules.jira.models import JiraOAuthState, JiraProject
from app.modules.jira.schemas import (
    JiraClientOption,
    JiraConnectionStatus,
    JiraProjectResponse,
    JiraProjectSelectionRequest,
    JiraProviderAccountResponse,
)
from app.modules.trello.models import TrelloClientRecord
from app.modules.workspaces.repository import WorkspaceRepository
from app.workers.tasks import notify_app_connected


logger = get_logger("app.modules.jira.service")


class JiraConnectionService:
    """Manages Atlassian Jira Cloud OAuth 2.0 authorization, site selection, and projects."""

    provider = "jira"

    def __init__(self, db: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.connections = ConnectionRepository(db)
        self.workspaces = WorkspaceRepository(db)

    @staticmethod
    def _require_oauth_config() -> None:
        if not settings.JIRA_CLIENT_ID or not settings.JIRA_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Jira OAuth is not configured. Set JIRA_CLIENT_ID and JIRA_CLIENT_SECRET in .env.",
            )
        if not settings.JIRA_CALLBACK_URL.startswith(("https://", "http://localhost")):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Jira callback URL must use HTTPS (except localhost).",
            )

    async def authorization_url(self) -> str:
        """Construct Atlassian 3LO authorization URL with single-use anti-CSRF state."""
        self._require_oauth_config()
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are no longer a member of this workspace.",
            )

        now = datetime.now(UTC)
        await self.db.execute(
            delete(JiraOAuthState).where(
                JiraOAuthState.user_id == self.user_id,
                JiraOAuthState.workspace_id == self.workspace_id,
                JiraOAuthState.expires_at <= now,
            )
        )
        state = secrets.token_urlsafe(32)
        self.db.add(
            JiraOAuthState(
                state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                expires_at=now + timedelta(minutes=10),
            )
        )
        await self.db.flush()

        oauth_client = JiraOAuthClient()
        return oauth_client.authorization_url(
            state=state,
            redirect_uri=settings.JIRA_CALLBACK_URL,
            scopes=settings.JIRA_SCOPES,
        )

    async def complete_authorization(
        self,
        *,
        code: str,
        state: str,
    ) -> JiraConnectionStatus:
        """Exchange authorization code, register Atlassian user and site, and notify."""
        self._require_oauth_config()
        state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
        oauth_state = await self.db.scalar(
            select(JiraOAuthState)
            .where(
                JiraOAuthState.state_hash == state_hash,
                JiraOAuthState.workspace_id == self.workspace_id,
                JiraOAuthState.user_id == self.user_id,
                JiraOAuthState.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        if oauth_state is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Jira authorization state is invalid or expired. Start the connection again.",
            )
        await self.db.delete(oauth_state)
        await self.db.commit()

        oauth_client = JiraOAuthClient()
        tokens = await oauth_client.exchange_code(
            code=code,
            redirect_uri=settings.JIRA_CALLBACK_URL,
        )

        async with JiraClient(tokens.access_token) as client:
            try:
                sites = await client.get_accessible_resources()
            except JiraAPIError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

            site_id = ""
            site_name = ""
            site_url = ""
            if sites:
                primary_site = sites[0]
                site_id = primary_site.get("id", "")
                site_name = primary_site.get("name", "")
                site_url = primary_site.get("url", "")

            # Try Atlassian /me first, then Jira Cloud /myself with read:jira-user
            me = await client.get_me()
            if not me and site_id:
                me = await client.get_myself(site_id)
            me = me or {}

        account_id = (
            me.get("account_id")
            or me.get("accountId")
            or me.get("email")
            or me.get("emailAddress")
            or site_id
            or "jira_user"
        )
        username = (
            me.get("displayName")
            or me.get("name")
            or me.get("email")
            or me.get("emailAddress")
            or site_name
            or str(account_id)
        )


        token_bundle = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": int(datetime.now(UTC).timestamp()) + tokens.expires_in,
            "cloud_id": site_id,
            "site_name": site_name,
            "site_url": site_url,
        }
        encrypted_token = encryption.encrypt(json.dumps(token_bundle))

        connection = await self.connections.upsert_provider_connection(
            workspace_id=self.workspace_id,
            provider=self.provider,
            user_id=self.user_id,
            encrypted_token=encrypted_token,
            external_account_id=str(account_id),
            external_username=username,
        )

        await self.workspaces.create_audit_log(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            action="connection.linked",
            entity_type="connection",
            entity_id=str(connection.id),
            metadata_json={
                "provider": self.provider,
                "account_id": str(account_id),
                "site_name": site_name,
            },
        )
        await self.db.commit()

        # Send app connected email notification
        await notify_app_connected(
            db=self.db,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            app_name="Jira",
            account_username=username,
            app_color="#1868DB",
        )

        return JiraConnectionStatus(
            connected=True,
            username=username,
            account_id=connection.provider_account_id,
            site_name=site_name,
            site_url=site_url,
        )

    async def status(self) -> JiraConnectionStatus:
        """Return the current Jira connection status for this workspace."""
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is None:
            return JiraConnectionStatus(connected=False)
        account = await self.connections.get_provider_account(connection)
        if account is None:
            return JiraConnectionStatus(connected=False)

        site_name = None
        site_url = None
        try:
            token_data = json.loads(encryption.decrypt(account.encrypted_token))
            site_name = token_data.get("site_name")
            site_url = token_data.get("site_url")
        except Exception:
            pass

        return JiraConnectionStatus(
            connected=True,
            username=account.external_username,
            account_id=account.id,
            site_name=site_name,
            site_url=site_url,
        )

    async def list_accounts(self) -> list[JiraProviderAccountResponse]:
        """List all previously authorized Jira accounts for this user."""
        accounts = await self.connections.list_provider_accounts(self.provider, self.user_id)
        return [
            JiraProviderAccountResponse(id=account.id, username=account.external_username)
            for account in accounts
        ]

    async def link_account(self, account_id: UUID) -> JiraConnectionStatus:
        """Link an existing Jira account to this workspace."""
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are no longer a member of this workspace.",
            )

        existing = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        account = await self.connections.get_provider_account_by_id(
            account_id, self.provider, self.user_id
        )
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That Jira account is not available to your user.",
            )
        if existing and existing.provider_account_id != account.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Disconnect the current Jira account before switching accounts.",
            )

        connection = await self.connections.link_existing_provider_account(
            workspace_id=self.workspace_id,
            provider=self.provider,
            user_id=self.user_id,
            account_id=account_id,
        )
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That Jira account is not available to your user.",
            )

        await self.workspaces.create_audit_log(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            action="connection.linked",
            entity_type="connection",
            entity_id=str(connection.id),
            metadata_json={"provider": self.provider, "account_id": account.external_account_id},
        )
        await self.db.commit()

        await notify_app_connected(
            db=self.db,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            app_name="Jira",
            account_username=account.external_username,
            app_color="#1868DB",
        )

        return JiraConnectionStatus(
            connected=True,
            username=account.external_username,
            account_id=account.id,
        )

    async def disconnect(self) -> JiraConnectionStatus:
        """Disconnect Jira from the active workspace."""
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is not None:
            await self.workspaces.create_audit_log(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                action="connection.unlinked",
                entity_type="connection",
                entity_id=str(connection.id),
                metadata_json={"provider": self.provider},
            )
            await self.connections.delete_provider_connection(
                workspace_id=self.workspace_id,
                provider=self.provider,
                user_id=self.user_id,
            )
            await self.db.commit()

        return JiraConnectionStatus(connected=False)

    async def list_clients(self) -> list[JiraClientOption]:
        """Fetch all clients registered in the workspace for project mapping."""
        result = await self.db.scalars(
            select(TrelloClientRecord)
            .where(TrelloClientRecord.workspace_id == self.workspace_id)
            .order_by(TrelloClientRecord.name)
        )
        return [JiraClientOption(id=client.id, name=client.name) for client in result.all()]

    async def list_projects(self) -> list[JiraProjectResponse]:

        """Fetch Jira projects from the linked Jira Cloud site, caching into database."""
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Connect a Jira account before accessing projects.",
            )
        account = await self.connections.get_provider_account(connection)
        if account is None or account.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The linked Jira account is unavailable. Reconnect it to continue.",
            )

        token_data = json.loads(encryption.decrypt(account.encrypted_token))
        cloud_id = token_data.get("cloud_id")
        access_token = token_data.get("access_token")

        if not cloud_id or not access_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No Jira Cloud site found for this account. Reauthorize to select a site.",
            )

        async with JiraClient(access_token) as client:
            try:
                remote_projects = await client.get_projects(cloud_id)
            except JiraAPIError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        # Upsert fetched projects into database
        for proj in remote_projects:
            proj_id = str(proj.get("id"))
            key = proj.get("key", "")
            name = proj.get("name", "")
            avatar_url = proj.get("avatarUrls", {}).get("48x48")
            project_type = proj.get("projectTypeKey", "software")

            stmt = (
                insert(JiraProject)
                .values(
                    workspace_id=self.workspace_id,
                    connection_id=connection.id,
                    cloud_id=cloud_id,
                    jira_project_id=proj_id,
                    key=key,
                    name=name,
                    project_type_key=project_type,
                    avatar_url=avatar_url,
                )
                .on_conflict_do_update(
                    constraint="uq_jira_projects_workspace_conn_project",
                    set_={
                        "name": name,
                        "key": key,
                        "avatar_url": avatar_url,
                    },
                )
            )
            await self.db.execute(stmt)
        await self.db.commit()

        # Query all projects for this workspace & connection
        result = await self.db.execute(
            select(JiraProject)
            .where(
                JiraProject.workspace_id == self.workspace_id,
                JiraProject.connection_id == connection.id,
            )
            .order_by(JiraProject.name.asc())
        )
        projects = result.scalars().all()
        return [JiraProjectResponse.model_validate(p) for p in projects]

    async def save_projects(
        self, payload: JiraProjectSelectionRequest
    ) -> list[JiraProjectResponse]:
        """Update inclusion toggles and optional client mapping for Jira projects."""
        for item in payload.selections:
            project = await self.db.get(JiraProject, item.project_id)
            if project and project.workspace_id == self.workspace_id:
                project.included = item.included
                project.client_id = item.client_id
        await self.db.commit()
        return await self.list_projects()
