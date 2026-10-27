import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.trello.models import TrelloOAuthState, TrelloSource


class ConnectionRepository:
    """Workspace-scoped persistence for provider connections and Trello boards."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_provider_connection(
        self,
        workspace_id: uuid.UUID,
        provider: str,
        user_id: uuid.UUID,
    ) -> WorkspaceConnection | None:
        result = await self.db.execute(
            select(WorkspaceConnection).where(
                WorkspaceConnection.workspace_id == workspace_id,
                WorkspaceConnection.provider == provider,
                WorkspaceConnection.user_id == user_id,
                WorkspaceConnection.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def upsert_provider_connection(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: str,
        user_id: uuid.UUID,
        encrypted_token: str,
        external_account_id: str,
        external_username: str,
    ) -> WorkspaceConnection:
        account_statement = (
            insert(ProviderAccount)
            .values(
                user_id=user_id,
                provider=provider,
                encrypted_token=encrypted_token,
                status="active",
                external_account_id=external_account_id,
                external_username=external_username,
            )
            .on_conflict_do_update(
                constraint="uq_provider_accounts_user_provider_external",
                set_={
                    "encrypted_token": encrypted_token,
                    "status": "active",
                    "external_username": external_username,
                },
            )
            .returning(ProviderAccount)
        )
        account = (await self.db.execute(account_statement)).scalar_one()
        return await self._link_provider_account(
            workspace_id=workspace_id,
            provider=provider,
            user_id=user_id,
            account=account,
        )

    async def link_existing_provider_account(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: str,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> WorkspaceConnection | None:
        result = await self.db.execute(
            select(ProviderAccount).where(
                ProviderAccount.id == account_id,
                ProviderAccount.provider == provider,
                ProviderAccount.user_id == user_id,
                ProviderAccount.status == "active",
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            return None
        return await self._link_provider_account(
            workspace_id=workspace_id,
            provider=provider,
            user_id=user_id,
            account=account,
        )

    async def list_provider_accounts(
        self,
        provider: str,
        user_id: uuid.UUID,
    ) -> list[ProviderAccount]:
        result = await self.db.execute(
            select(ProviderAccount)
            .where(
                ProviderAccount.provider == provider,
                ProviderAccount.user_id == user_id,
                ProviderAccount.status == "active",
            )
            .order_by(ProviderAccount.external_username)
        )
        return list(result.scalars().all())

    async def get_provider_account_by_id(
        self,
        account_id: uuid.UUID,
        provider: str,
        user_id: uuid.UUID,
    ) -> ProviderAccount | None:
        return await self.db.scalar(
            select(ProviderAccount).where(
                ProviderAccount.id == account_id,
                ProviderAccount.provider == provider,
                ProviderAccount.user_id == user_id,
                ProviderAccount.status == "active",
            )
        )

    async def get_provider_account(
        self,
        connection: WorkspaceConnection,
    ) -> ProviderAccount | None:
        return await self.db.get(ProviderAccount, connection.provider_account_id)

    async def _link_provider_account(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: str,
        user_id: uuid.UUID,
        account: ProviderAccount,
    ) -> WorkspaceConnection:
        result = await self.db.execute(
            select(WorkspaceConnection)
            .where(
                WorkspaceConnection.workspace_id == workspace_id,
                WorkspaceConnection.provider == provider,
                WorkspaceConnection.user_id == user_id,
            )
            .with_for_update()
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            if existing.provider_account_id == account.id:
                existing.status = "active"
                await self.db.flush()
                return existing
            await self.db.delete(existing)
            await self.db.flush()

        connection = WorkspaceConnection(
            workspace_id=workspace_id,
            provider=provider,
            user_id=user_id,
            provider_account_id=account.id,
            status="active",
        )
        self.db.add(connection)
        await self.db.flush()
        return connection

    async def update_encrypted_token(
        self,
        account: ProviderAccount,
        encrypted_token: str,
    ) -> None:
        account.encrypted_token = encrypted_token
        await self.db.flush()

    async def delete_provider_connection(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: str,
        user_id: uuid.UUID,
    ) -> bool:
        connection = await self.get_provider_connection(
            workspace_id,
            provider,
            user_id,
        )
        if connection is None:
            return False
        account_id = connection.provider_account_id
        await self.db.delete(connection)
        await self.db.flush()
        account_is_linked = await self.db.scalar(
            select(exists().where(WorkspaceConnection.provider_account_id == account_id))
        )
        if not account_is_linked:
            account = await self.db.get(ProviderAccount, account_id)
            if account is not None:
                await self.db.delete(account)
                await self.db.flush()
        return True

    async def create_oauth_state(
        self,
        *,
        state_hash: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        encrypted_code_verifier: str,
        expires_at: datetime,
    ) -> None:
        self.db.add(
            TrelloOAuthState(
                state_hash=state_hash,
                workspace_id=workspace_id,
                user_id=user_id,
                encrypted_code_verifier=encrypted_code_verifier,
                expires_at=expires_at,
            )
        )
        await self.db.flush()

    async def consume_oauth_state(
        self,
        *,
        state_hash: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        now: datetime,
    ) -> TrelloOAuthState | None:
        result = await self.db.execute(
            select(TrelloOAuthState)
            .where(
                TrelloOAuthState.state_hash == state_hash,
                TrelloOAuthState.workspace_id == workspace_id,
                TrelloOAuthState.user_id == user_id,
                TrelloOAuthState.expires_at > now,
            )
            .with_for_update()
        )
        oauth_state = result.scalar_one_or_none()
        if oauth_state:
            await self.db.delete(oauth_state)
            await self.db.flush()
        return oauth_state

    async def list_sources(
        self,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> list[TrelloSource]:
        result = await self.db.execute(
            select(TrelloSource)
            .where(
                TrelloSource.workspace_id == workspace_id,
                TrelloSource.connection_id == connection_id,
            )
            .order_by(TrelloSource.name)
        )
        return list(result.scalars().all())

    async def upsert_sources(
        self,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        sources: list[dict[str, str | bool]],
    ) -> None:
        if not sources:
            return
        statement = insert(TrelloSource).values(
            [
                {
                    "workspace_id": workspace_id,
                    "connection_id": connection_id,
                    "trello_board_id": source["trello_board_id"],
                    "name": source["name"],
                    "url": source["url"],
                    "excluded": source["excluded"],
                }
                for source in sources
            ]
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_sources_connection_board",
            set_={
                "connection_id": statement.excluded.connection_id,
                "name": statement.excluded.name,
                "url": statement.excluded.url,
                "excluded": statement.excluded.excluded,
            },
        )
        await self.db.execute(statement)
