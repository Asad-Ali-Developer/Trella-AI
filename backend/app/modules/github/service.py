import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.encryption import encryption
from app.modules.connections.models import GithubOAuthState, ProviderAccount, WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.github.client import GithubAPIError, GithubClient
from app.modules.github.models import GithubRepository
from app.modules.github.schemas import (
    GithubClientOption,
    GithubConnectionStatus,
    GithubProviderAccountResponse,
    GithubRepositoryResponse,
    GithubRepositorySelectionRequest,
)
from app.modules.trello.models import TrelloClientRecord
from app.modules.workspaces.repository import WorkspaceRepository


class GithubConnectionService:
    """Workspace-linked GitHub accounts, selected repositories, and sync scheduling."""

    provider = "github"

    def __init__(self, db: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.connections = ConnectionRepository(db)
        self.workspaces = WorkspaceRepository(db)

    async def authorization_url(self) -> str:
        self._require_oauth_config()
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if membership is None:
            raise HTTPException(
                status_code=403, detail="You are no longer a member of this workspace."
            )
        now = datetime.now(UTC)
        await self.db.execute(
            delete(GithubOAuthState).where(
                GithubOAuthState.user_id == self.user_id,
                GithubOAuthState.workspace_id == self.workspace_id,
                GithubOAuthState.expires_at <= now,
            )
        )
        state = secrets.token_urlsafe(32)
        self.db.add(
            GithubOAuthState(
                state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                expires_at=now + timedelta(minutes=10),
            )
        )
        await self.db.flush()
        query = urlencode(
            {
                "client_id": settings.GITHUB_CLIENT_ID,
                "redirect_uri": settings.GITHUB_CALLBACK_URL,
                "scope": "read:user repo",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def complete_authorization(self, *, code: str, state: str) -> GithubConnectionStatus:
        self._require_oauth_config()
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if membership is None:
            raise HTTPException(
                status_code=403, detail="You are no longer a member of this workspace."
            )
        state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
        oauth_state = await self.db.scalar(
            select(GithubOAuthState)
            .where(
                GithubOAuthState.state_hash == state_hash,
                GithubOAuthState.workspace_id == self.workspace_id,
                GithubOAuthState.user_id == self.user_id,
                GithubOAuthState.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        if oauth_state is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub authorization state is invalid or expired. Start the connection again.",
            )
        await self.db.delete(oauth_state)
        await self.db.commit()
        try:
            token = await GithubClient.exchange_code(code)
            async with GithubClient(token) as client:
                user = await client.get_user()
        except GithubAPIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        username = user.get("login")
        if not isinstance(username, str) or not username:
            raise HTTPException(
                status_code=502, detail="GitHub returned invalid account information."
            )
        connection = await self.connections.upsert_provider_connection(
            workspace_id=self.workspace_id,
            provider=self.provider,
            user_id=self.user_id,
            encrypted_token=encryption.encrypt(token),
            external_account_id=str(user["id"]),
            external_username=username,
        )
        await self.workspaces.create_audit_log(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            action="connection.linked",
            entity_type="connection",
            entity_id=str(connection.id),
            metadata_json={"provider": self.provider, "account_id": str(user["id"])},
        )
        await self.db.commit()
        return GithubConnectionStatus(
            connected=True,
            username=username,
            account_id=connection.provider_account_id,
        )

    async def status(self) -> GithubConnectionStatus:
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is None:
            return GithubConnectionStatus(connected=False)
        account = await self.connections.get_provider_account(connection)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The linked GitHub account is unavailable. Reconnect it to continue.",
            )
        return GithubConnectionStatus(
            connected=True,
            username=account.external_username,
            account_id=account.id,
        )

    async def list_accounts(self) -> list[GithubProviderAccountResponse]:
        accounts = await self.connections.list_provider_accounts(self.provider, self.user_id)
        return [
            GithubProviderAccountResponse(id=account.id, username=account.external_username)
            for account in accounts
        ]

    async def list_clients(self) -> list[GithubClientOption]:
        result = await self.db.scalars(
            select(TrelloClientRecord)
            .where(TrelloClientRecord.workspace_id == self.workspace_id)
            .order_by(TrelloClientRecord.name)
        )
        return [GithubClientOption(id=client.id, name=client.name) for client in result.all()]

    async def link_account(self, account_id: UUID) -> GithubConnectionStatus:
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if membership is None:
            raise HTTPException(
                status_code=403, detail="You are no longer a member of this workspace."
            )
        existing = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        account = await self.connections.get_provider_account_by_id(
            account_id, self.provider, self.user_id
        )
        if account is None:
            raise HTTPException(
                status_code=404, detail="That GitHub account is not available to your user."
            )
        if existing and existing.provider_account_id != account.id:
            raise HTTPException(
                status_code=409,
                detail="Disconnect the current GitHub account before switching accounts.",
            )
        connection = await self.connections.link_existing_provider_account(
            workspace_id=self.workspace_id,
            provider=self.provider,
            user_id=self.user_id,
            account_id=account_id,
        )
        if connection is None:
            raise HTTPException(
                status_code=404, detail="That GitHub account is not available to your user."
            )
        await self.workspaces.create_audit_log(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            action="connection.linked",
            entity_type="connection",
            entity_id=str(connection.id),
            metadata_json={"provider": self.provider, "account_id": account.external_account_id},
        )
        return GithubConnectionStatus(
            connected=True,
            username=account.external_username,
            account_id=account.id,
        )

    async def disconnect(self) -> GithubConnectionStatus:
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is not None:
            await self.workspaces.create_audit_log(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                action="connection.deleted",
                entity_type="connection",
                entity_id=str(connection.id),
                metadata_json={"provider": self.provider},
            )
            await self.connections.delete_provider_connection(
                workspace_id=self.workspace_id,
                provider=self.provider,
                user_id=self.user_id,
            )
        await self.db.execute(
            delete(GithubOAuthState).where(
                GithubOAuthState.workspace_id == self.workspace_id,
                GithubOAuthState.user_id == self.user_id,
            )
        )
        return GithubConnectionStatus(connected=False)

    async def refresh_repositories(self) -> list[GithubRepositoryResponse]:
        connection, account = await self._get_connection_and_account()
        try:
            async with GithubClient(encryption.decrypt(account.encrypted_token)) as client:
                remote_repositories = await client.list_repositories()
        except GithubAPIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        for repository in remote_repositories:
            full_name = repository.get("full_name")
            if (
                not isinstance(full_name, str)
                or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name) is None
            ):
                raise HTTPException(
                    status_code=502,
                    detail="GitHub returned an invalid repository name.",
                )
            repo_id = str(repository["id"])
            statement = insert(GithubRepository).values(
                workspace_id=self.workspace_id,
                connection_id=connection.id,
                github_repo_id=repo_id,
                full_name=full_name,
                description=(
                    str(repository["description"])
                    if repository.get("description") is not None
                    else None
                ),
                url=str(repository.get("html_url", "")),
                default_branch=str(repository.get("default_branch") or "main"),
                private=bool(repository.get("private", False)),
                included=False,
            )
            await self.db.execute(
                statement.on_conflict_do_update(
                    constraint="uq_github_repositories_workspace_external",
                    set_={
                        "full_name": statement.excluded.full_name,
                        "description": statement.excluded.description,
                        "url": statement.excluded.url,
                        "default_branch": statement.excluded.default_branch,
                        "private": statement.excluded.private,
                    },
                )
            )
        remote_ids = [str(repository["id"]) for repository in remote_repositories]
        await self.db.execute(
            delete(GithubRepository).where(
                GithubRepository.workspace_id == self.workspace_id,
                GithubRepository.connection_id == connection.id,
                GithubRepository.github_repo_id.not_in(remote_ids),
            )
        )
        await self.db.flush()
        return await self._repository_responses(connection.id)

    async def list_repositories(self) -> list[GithubRepositoryResponse]:
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is None:
            raise HTTPException(status_code=404, detail="Connect a GitHub account first.")
        return await self._repository_responses(connection.id)

    async def save_repositories(
        self,
        request: GithubRepositorySelectionRequest,
    ) -> int:
        connection, _ = await self._get_connection_and_account()
        existing = await self._repository_responses(connection.id)
        existing_by_id = {repository.id: repository for repository in existing}
        requested = {repository.id: repository for repository in request.repositories}
        if len(requested) != len(request.repositories):
            raise HTTPException(
                status_code=422,
                detail="A repository may only appear once in the selection.",
            )
        unknown_ids = requested.keys() - existing_by_id.keys()
        if unknown_ids:
            raise HTTPException(
                status_code=422,
                detail="One or more repositories are not available to this GitHub account.",
            )
        for selection_to_validate in requested.values():
            if selection_to_validate.client_id is not None:
                client_exists = await self.db.scalar(
                    select(TrelloClientRecord.id).where(
                        TrelloClientRecord.id == selection_to_validate.client_id,
                        TrelloClientRecord.workspace_id == self.workspace_id,
                    )
                )
                if client_exists is None:
                    raise HTTPException(status_code=422, detail="Client is not in this workspace.")

        repos = await self.db.scalars(
            select(GithubRepository).where(
                GithubRepository.workspace_id == self.workspace_id,
                GithubRepository.connection_id == connection.id,
            )
        )
        updated_count = 0
        for repo in repos:
            saved_selection = requested.get(repo.github_repo_id)
            if saved_selection is None:
                continue
            repo.included = saved_selection.included
            repo.client_id = saved_selection.client_id
            if saved_selection.included:
                repo.sync_status = "not_started"
                repo.sync_error = None
            updated_count += 1
        await self.db.flush()
        return updated_count

    async def selected_repositories(self) -> list[GithubRepository]:
        connection, _ = await self._get_connection_and_account()
        result = await self.db.scalars(
            select(GithubRepository).where(
                GithubRepository.workspace_id == self.workspace_id,
                GithubRepository.connection_id == connection.id,
                GithubRepository.included.is_(True),
            )
        )
        return list(result.all())

    async def _get_connection_and_account(self) -> tuple[WorkspaceConnection, ProviderAccount]:
        connection = await self.connections.get_provider_connection(
            self.workspace_id, self.provider, self.user_id
        )
        if connection is None:
            raise HTTPException(status_code=404, detail="Connect a GitHub account first.")
        account = await self.connections.get_provider_account(connection)
        if account is None or account.status != "active":
            raise HTTPException(
                status_code=409,
                detail="The linked GitHub account is unavailable. Reconnect it to continue.",
            )
        return connection, account

    async def _repository_responses(
        self,
        connection_id: UUID,
    ) -> list[GithubRepositoryResponse]:
        result = await self.db.execute(
            select(GithubRepository, TrelloClientRecord.name)
            .outerjoin(TrelloClientRecord, GithubRepository.client_id == TrelloClientRecord.id)
            .where(
                GithubRepository.workspace_id == self.workspace_id,
                GithubRepository.connection_id == connection_id,
            )
            .order_by(GithubRepository.full_name)
        )
        return [
            GithubRepositoryResponse(
                id=repository.github_repo_id,
                full_name=repository.full_name,
                description=repository.description,
                url=repository.url,
                default_branch=repository.default_branch,
                private=repository.private,
                included=repository.included,
                client_id=repository.client_id,
                sync_status=repository.sync_status,
                last_synced_at=repository.last_synced_at,
                sync_error=repository.sync_error,
            )
            for repository, _ in result.all()
        ]

    @staticmethod
    def _require_oauth_config() -> None:
        if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.",
            )
