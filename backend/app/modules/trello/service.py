import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.encryption import encryption
from app.modules.connections.models import WorkspaceConnection
from app.modules.connections.repository import ConnectionRepository
from app.modules.trello.client import TrelloAPIError, TrelloClient
from app.modules.trello.oauth import TrelloOAuthClient, TrelloOAuthError, TrelloOAuthTokens
from app.modules.trello.schemas import (
    TrelloBoardResponse,
    TrelloBoardSelectionRequest,
    TrelloConnectionStatus,
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
        return TrelloConnectionStatus(connected=True, username=connection.external_username)

    async def list_boards(self) -> list[TrelloBoardResponse]:
        connection = await self._get_connection()
        try:
            async with await self._open_client(connection) as client:  # CHANGED
                boards = await client.list_boards()
        except TrelloAPIError as exc:
            raise self._to_http_exception(exc) from exc

        sources = await self.connections.list_sources(self.workspace_id, connection.id)
        saved_exclusions = {source.trello_board_id: source.excluded for source in sources}
        return [
            TrelloBoardResponse(
                id=str(board["id"]),
                name=str(board.get("name", "")),
                url=str(board.get("url", "")),
                excluded=saved_exclusions.get(str(board["id"]), True),
            )
            for board in boards
            if isinstance(board.get("id"), str)
        ]

    async def save_board_selections(
        self,
        request: TrelloBoardSelectionRequest,
    ) -> int:
        connection = await self._get_connection()
        try:
            async with await self._open_client(connection) as client:  # CHANGED
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

        await self.connections.upsert_provider_connection(
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
        return TrelloConnectionStatus(connected=True, username=username)

    async def _open_client(self, connection: WorkspaceConnection) -> TrelloClient:
        """Build a TrelloClient matching how this connection was authorized."""
        credentials = self._read_credentials(connection)
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
            )
        return TrelloClient(
            token=await self._get_access_token(connection),
            base_url=settings.TRELLO_API_BASE_URL,
        )

    @staticmethod
    def _read_credentials(connection: WorkspaceConnection) -> dict[str, Any]:
        try:
            data = json.loads(encryption.decrypt(connection.encrypted_token))
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

    async def _get_access_token(self, connection: WorkspaceConnection) -> str:
        try:
            token_data = json.loads(encryption.decrypt(connection.encrypted_token))
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
            connection,
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
