import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.encryption import encryption
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.trello.client import TrelloAPIError, TrelloClient
from app.modules.trello.models import (
    TrelloClientMapping,
    TrelloClientRecord,
    TrelloMember,
    TrelloOAuthState,
)
from app.modules.trello.oauth import TrelloOAuthClient, TrelloOAuthError, TrelloOAuthTokens
from app.modules.trello.rate_limiter import trello_rate_limiter
from app.modules.trello.schemas import (
    TrelloBoardResponse,
    TrelloBoardSelectionRequest,
    TrelloConnectionStatus,
    TrelloProviderAccountResponse,
)
from app.modules.workspaces.repository import WorkspaceRepository

AUTH_TYPE_API_KEY = "eb7b400699b7f3bee188ab2a058a11e7"


class TrelloConnectionService:
    """Workspace-scoped Trello connection and board selection workflows."""

    provider = "trello"

    def __init__(self, db: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.connections = ConnectionRepository(db)
        self.workspaces = WorkspaceRepository(db)

    # ------------------------------------------------------------------
    # OAuth 2.0 flow (unchanged)
    # ------------------------------------------------------------------
    async def authorization_url(self) -> str:
        self._require_oauth_config()

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )

        await self.connections.create_oauth_state(
            state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            encrypted_code_verifier=encryption.encrypt(code_verifier),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

        query: dict[str, str] = {
            "client_id": settings.TRELLO_OAUTH_CLIENT_ID,
            "scope": settings.TRELLO_OAUTH_SCOPES,
            "redirect_uri": settings.TRELLO_OAUTH_CALLBACK_URL,
            "response_type": "code",
            "prompt": "consent",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"https://auth.atlassian.com/authorize?{urlencode(query)}"

    async def complete_authorization(
        self,
        *,
        code: str,
        state: str,
    ) -> TrelloConnectionStatus:
        self._require_oauth_config()
        oauth_state = await self._validate_membership_and_consume_state(state)
        code_verifier = encryption.decrypt(oauth_state.encrypted_code_verifier)
        try:
            async with TrelloOAuthClient(
                settings.TRELLO_OAUTH_CLIENT_ID,
                settings.TRELLO_OAUTH_CLIENT_SECRET,
            ) as client:
                tokens = await client.exchange_code(
                    code=code,
                    code_verifier=code_verifier,
                    redirect_uri=settings.TRELLO_OAUTH_CALLBACK_URL,
                )
            async with TrelloClient(
                token=tokens.access_token,
                base_url=settings.TRELLO_API_BASE_URL,
                rate_limiter=trello_rate_limiter,
            ) as trello:
                member = await trello.get_member()
        except TrelloOAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except TrelloAPIError as exc:
            raise self._to_http_exception(exc) from exc

        return await self._save_connection(member, self._encrypt_tokens(tokens))

    # ------------------------------------------------------------------
    # NEW: API key + token flow ("Trello Auth")
    # ------------------------------------------------------------------
    async def token_authorization_url(self) -> str:
        self._require_token_config()

        state = secrets.token_urlsafe(32)
        await self.connections.create_oauth_state(
            state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            # Column is non-null; this flow has no PKCE verifier.
            encrypted_code_verifier=encryption.encrypt("token-flow"),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

        return_url = f"{settings.TRELLO_TOKEN_RETURN_URL}?{urlencode({'state': state})}"
        query: dict[str, str] = {
            "key": settings.TRELLO_API_KEY,
            "name": settings.APP_NAME,
            "scope": settings.TRELLO_TOKEN_SCOPE,
            "expiration": settings.TRELLO_TOKEN_EXPIRATION,
            "response_type": "token",
            "callback_method": "fragment",
            "return_url": return_url,
        }
        return f"https://trello.com/1/authorize?{urlencode(query)}"

    async def complete_token_authorization(
        self,
        *,
        token: str,
        state: str,
    ) -> TrelloConnectionStatus:
        self._require_token_config()
        await self._validate_membership_and_consume_state(state)
        try:
            async with TrelloClient(
                token=token,
                api_key=settings.TRELLO_API_KEY,
                base_url=settings.TRELLO_API_BASE_URL,
                rate_limiter=trello_rate_limiter,
            ) as trello:
                member = await trello.get_member()
        except TrelloAPIError as exc:
            raise self._to_http_exception(exc) from exc

        return await self._save_connection(member, self._encrypt_api_token(token))

    # ------------------------------------------------------------------
    # Shared connection / board workflows
    # ------------------------------------------------------------------
    async def status(self) -> TrelloConnectionStatus:
        connection = await self.connections.get_provider_connection(
            self.workspace_id,
            self.provider,
            self.user_id,
        )
        if not connection:
            return TrelloConnectionStatus(connected=False)
        account = await self.connections.get_provider_account(connection)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The linked Trello account is unavailable. Reconnect it to continue.",
            )
        return TrelloConnectionStatus(
            connected=True,
            username=account.external_username,
            account_id=account.id,
        )

    async def list_accounts(self) -> list[TrelloProviderAccountResponse]:
        accounts = await self.connections.list_provider_accounts(self.provider, self.user_id)
        return [
            TrelloProviderAccountResponse(id=account.id, username=account.external_username)
            for account in accounts
        ]

    async def link_account(self, account_id: UUID) -> TrelloConnectionStatus:
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are no longer a member of this workspace.",
            )
        existing = await self.connections.get_provider_connection(
            self.workspace_id,
            self.provider,
            self.user_id,
        )
        account = await self.connections.get_provider_account_by_id(
            account_id,
            self.provider,
            self.user_id,
        )
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That Trello account is not available to your user.",
            )
        if existing is not None and existing.provider_account_id != account.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Disconnect the current Trello account before switching accounts.",
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
                detail="That Trello account is not available to your user.",
            )
        await self.workspaces.create_audit_log(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            action="connection.linked",
            entity_type="connection",
            entity_id=str(connection.id),
            metadata_json={"provider": self.provider, "account_id": account.external_account_id},
        )
        return TrelloConnectionStatus(
            connected=True,
            username=account.external_username,
            account_id=account.id,
        )

    async def disconnect(self) -> TrelloConnectionStatus:
        connection = await self.connections.get_provider_connection(
            self.workspace_id,
            self.provider,
            self.user_id,
        )
        if connection is None:
            return TrelloConnectionStatus(connected=False)

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
            delete(TrelloOAuthState).where(
                TrelloOAuthState.workspace_id == self.workspace_id,
                TrelloOAuthState.user_id == self.user_id,
            )
        )
        await self._clear_workspace_trello_data_if_unlinked()
        return TrelloConnectionStatus(connected=False)

    async def list_boards(self) -> list[TrelloBoardResponse]:
        connection = await self._get_connection()
        account = await self._get_account(connection)
        try:
            async with await self._open_client(account) as client:
                boards = await client.list_boards()
        except TrelloAPIError as exc:
            raise self._to_http_exception(exc) from exc

        sources = await self.connections.list_sources(self.workspace_id, connection.id)
        saved_exclusions = {source.trello_board_id: source.excluded for source in sources}
        saved_sources = {source.trello_board_id: source for source in sources}
        return [
            TrelloBoardResponse(
                id=str(board["id"]),
                name=str(board.get("name", "")),
                url=str(board.get("url", "")),
                excluded=saved_exclusions.get(str(board["id"]), True),
                sync_status=saved_sources[str(board["id"])].sync_status
                if str(board["id"]) in saved_sources
                else "not_started",
                last_synced_at=saved_sources[str(board["id"])].last_synced_at
                if str(board["id"]) in saved_sources
                else None,
                sync_error=saved_sources[str(board["id"])].sync_error
                if str(board["id"]) in saved_sources
                else None,
            )
            for board in boards
            if isinstance(board.get("id"), str)
        ]

    async def save_board_selections(
        self,
        request: TrelloBoardSelectionRequest,
    ) -> int:
        connection = await self._get_connection()
        account = await self._get_account(connection)
        try:
            async with await self._open_client(account) as client:
                remote_boards = await client.list_boards()
        except TrelloAPIError as exc:
            raise self._to_http_exception(exc) from exc

        requested = {selection.id: selection.excluded for selection in request.boards}
        if len(requested) != len(request.boards):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A board may only appear once in the selection.",
            )
        remote_by_id = {
            str(board["id"]): board for board in remote_boards if isinstance(board.get("id"), str)
        }
        unknown_ids = requested.keys() - remote_by_id.keys()
        if unknown_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="One or more selected boards are not available to this Trello account.",
            )

        existing_sources = await self.connections.list_sources(self.workspace_id, connection.id)
        exclusions = {board_id: requested.get(board_id, True) for board_id in remote_by_id}
        for source in existing_sources:
            if source.trello_board_id not in requested and source.trello_board_id in remote_by_id:
                exclusions[source.trello_board_id] = source.excluded

        source_values: list[dict[str, str | bool]] = [
            {
                "trello_board_id": board_id,
                "name": str(board.get("name", "")),
                "url": str(board.get("url", "")),
                "excluded": exclusions[board_id],
            }
            for board_id, board in remote_by_id.items()
        ]
        await self.connections.upsert_sources(
            workspace_id=self.workspace_id,
            connection_id=connection.id,
            sources=source_values,
        )
        return len(source_values)

    # ------------------------------------------------------------------
    # NEW: shared helpers
    # ------------------------------------------------------------------
    async def _validate_membership_and_consume_state(self, state: str) -> Any:
        membership = await self.workspaces.get_membership(self.workspace_id, self.user_id)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are no longer a member of this workspace.",
            )
        oauth_state = await self.connections.consume_oauth_state(
            state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            now=datetime.now(UTC),
        )
        if not oauth_state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Trello authorization state is invalid or expired. Start again.",
            )
        return oauth_state

    async def _save_connection(
        self,
        member: dict[str, Any],
        encrypted_token: str,
    ) -> TrelloConnectionStatus:
        account_id = member.get("id")
        username = member.get("username")
        if not isinstance(account_id, str) or not isinstance(username, str):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Trello returned incomplete account information.",
            )

        existing = await self.connections.get_provider_connection(
            self.workspace_id,
            self.provider,
            self.user_id,
        )
        existing_account = (
            await self.connections.get_provider_account(existing) if existing is not None else None
        )
        if existing_account is not None and existing_account.external_account_id != account_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Disconnect the current Trello account before switching accounts.",
            )
        connection = await self.connections.upsert_provider_connection(
            workspace_id=self.workspace_id,
            provider=self.provider,
            user_id=self.user_id,
            encrypted_token=encrypted_token,
            external_account_id=account_id,
            external_username=username,
        )
        await self.workspaces.create_audit_log(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            action="connection.created",
            entity_type="connection",
            metadata_json={"provider": self.provider, "account_id": account_id},
        )
        account = await self.connections.get_provider_account(connection)
        return TrelloConnectionStatus(
            connected=True,
            username=username,
            account_id=account.id if account else None,
        )

    async def _open_client(self, account: ProviderAccount) -> TrelloClient:
        """Build a TrelloClient matching how this connection was authorized."""
        credentials = self._read_credentials(account)
        if isinstance(credentials.get("token"), str):
            token = credentials.get("token")
            if not isinstance(token, str) or not token or not settings.TRELLO_API_KEY:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This Trello connection needs to be reauthorized.",
                )
            return TrelloClient(
                token=token,
                api_key=settings.TRELLO_API_KEY,
                base_url=settings.TRELLO_API_BASE_URL,
                rate_limiter=trello_rate_limiter,
            )
        return TrelloClient(
            token=await self._get_access_token(account),
            base_url=settings.TRELLO_API_BASE_URL,
            rate_limiter=trello_rate_limiter,
        )

    @staticmethod
    def _read_credentials(account: ProviderAccount) -> dict[str, Any]:
        try:
            data = json.loads(encryption.decrypt(account.encrypted_token))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Trello connection needs to be reauthorized.",
            ) from exc
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Trello connection needs to be reauthorized.",
            )
        return data

    @staticmethod
    def _encrypt_api_token(token: str) -> str:
        return encryption.encrypt(json.dumps({"auth_type": AUTH_TYPE_API_KEY, "token": token}))

    @staticmethod
    def _require_token_config() -> None:
        if not settings.TRELLO_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Trello API key is not configured.",
            )
        if not settings.TRELLO_TOKEN_RETURN_URL.startswith(("https://", "http://localhost")):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Trello return URL must use HTTPS (except localhost).",
            )

    # ------------------------------------------------------------------
    # Existing helpers (unchanged)
    # ------------------------------------------------------------------
    async def _get_connection(self) -> WorkspaceConnection:
        connection = await self.connections.get_provider_connection(
            self.workspace_id,
            self.provider,
            self.user_id,
        )
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Connect a Trello account before accessing boards.",
            )
        return connection

    async def _get_account(self, connection: WorkspaceConnection) -> ProviderAccount:
        account = await self.connections.get_provider_account(connection)
        if account is None or account.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The linked Trello account is unavailable. Reconnect it to continue.",
            )
        return account

    async def _clear_workspace_trello_data_if_unlinked(self) -> None:
        await self.db.execute(
            delete(TrelloClientRecord).where(
                TrelloClientRecord.workspace_id == self.workspace_id,
                ~exists(
                    select(TrelloClientMapping.id).where(
                        TrelloClientMapping.client_id == TrelloClientRecord.id
                    )
                ),
            )
        )
        other_trello_connections = await self.db.scalar(
            select(
                exists().where(
                    WorkspaceConnection.workspace_id == self.workspace_id,
                    WorkspaceConnection.provider == self.provider,
                    WorkspaceConnection.status == "active",
                )
            )
        )
        if not other_trello_connections:
            await self.db.execute(
                delete(TrelloMember).where(TrelloMember.workspace_id == self.workspace_id)
            )

    @staticmethod
    def _require_oauth_config() -> None:
        if not settings.TRELLO_OAUTH_CLIENT_ID or not settings.TRELLO_OAUTH_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Trello OAuth is not configured.",
            )

        if not settings.TRELLO_OAUTH_CALLBACK_URL.startswith(("https://", "http://localhost")):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Trello OAuth callback URL must use HTTPS (except localhost).",
            )

    async def _get_access_token(self, account: ProviderAccount) -> str:
        locked_account = await self.db.scalar(
            select(ProviderAccount)
            .where(ProviderAccount.id == account.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_account is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The linked Trello account is unavailable. Reconnect it to continue.",
            )
        account = locked_account
        try:
            token_data = json.loads(encryption.decrypt(account.encrypted_token))
            token_bundle = TrelloOAuthTokens.model_validate(token_data)
            expires_at = int(token_data["expires_at"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Trello connection needs to be reauthorized.",
            ) from exc

        now = int(datetime.now(UTC).timestamp())
        if expires_at > now + 60:
            return token_bundle.access_token

        self._require_oauth_config()
        try:
            async with TrelloOAuthClient(
                settings.TRELLO_OAUTH_CLIENT_ID,
                settings.TRELLO_OAUTH_CLIENT_SECRET,
            ) as client:
                refreshed = await client.refresh(token_bundle.refresh_token)
        except TrelloOAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Trello authorization expired. Reconnect your Trello account.",
            ) from exc

        await self.connections.update_encrypted_token(
            account,
            self._encrypt_tokens(refreshed),
        )
        return refreshed.access_token

    @staticmethod
    def _encrypt_tokens(tokens: TrelloOAuthTokens) -> str:
        expires_at = int(datetime.now(UTC).timestamp()) + tokens.expires_in
        payload = tokens.model_dump()
        payload["expires_at"] = expires_at
        return encryption.encrypt(json.dumps(payload))

    @staticmethod
    def _to_http_exception(error: TrelloAPIError) -> HTTPException:
        if error.status_code == 401:
            code = status.HTTP_400_BAD_REQUEST
            detail = "Trello rejected these credentials. Reconnect your account."
        elif error.status_code == 429:
            code = status.HTTP_429_TOO_MANY_REQUESTS
            detail = "Trello rate limit reached. Please retry shortly."
        else:
            code = status.HTTP_502_BAD_GATEWAY
            detail = "Trello is temporarily unavailable. Please retry shortly."
        return HTTPException(status_code=code, detail=detail)
