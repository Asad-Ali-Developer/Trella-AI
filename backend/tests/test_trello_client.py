import base64
import hashlib
import json
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
import respx
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.core.security.encryption import encryption
from app.modules.connections.repository import ConnectionRepository
from app.modules.trello.client import TrelloAPIError, TrelloClient
from app.modules.trello.oauth import TrelloOAuthClient, TrelloOAuthError
from app.modules.trello.service import TrelloConnectionService


@pytest.mark.asyncio
async def test_upsert_connection_compiles_against_unique_model_constraint() -> None:
    result = Mock()
    result.scalar_one.return_value = Mock()
    db = Mock()
    db.execute = AsyncMock(return_value=result)
    repository = ConnectionRepository(db)

    await repository.upsert_provider_connection(
        workspace_id=uuid4(),
        provider="trello",
        user_id=uuid4(),
        encrypted_token="encrypted-token",
        external_account_id="trello-user-id",
        external_username="trello-user",
    )

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_connections_workspace_provider_user" in sql
    assert "constraint" not in statement.compile(dialect=postgresql.dialect()).params


@pytest.mark.asyncio
@respx.mock
async def test_get_member_uses_oauth_bearer_token() -> None:
    route = respx.get("https://api.trello.com/1/members/me").mock(
        return_value=httpx.Response(
            200,
            json={"id": "member-1", "username": "trello-user", "fullName": "Trello User"},
        )
    )

    async with TrelloClient(token="user-token") as client:
        member = await client.get_member()

    assert member["id"] == "member-1"
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer user-token"


@pytest.mark.asyncio
@respx.mock
async def test_list_boards_requests_open_board_fields() -> None:
    route = respx.get("https://api.trello.com/1/members/me/boards").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "board-1", "name": "Client Alpha", "url": "https://trello.com/b/1"}],
        )
    )

    async with TrelloClient(token="user-token") as client:
        boards = await client.list_boards()

    assert boards[0]["id"] == "board-1"
    assert route.calls.last.request.url.params["filter"] == "open"
    assert route.calls.last.request.url.params["fields"] == "id,name,url,closed"


@pytest.mark.asyncio
@respx.mock
async def test_trello_error_does_not_leak_credentials() -> None:
    respx.get("https://api.trello.com/1/members/me").mock(
        return_value=httpx.Response(401, json={"message": "invalid credentials"})
    )

    async with TrelloClient(token="private-token") as client:
        with pytest.raises(TrelloAPIError, match="Trello rejected the request") as error:
            await client.get_member()

    assert error.value.status_code == 401
    assert "private-token" not in str(error.value)


@pytest.mark.asyncio
@respx.mock
async def test_oauth_code_exchange_uses_confidential_client_and_pkce() -> None:
    route = respx.post("https://auth.atlassian.com/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "access-value",
                "refresh_token": "refresh-value",
                "expires_in": 3600,
                "scope": "read:board:trello",
            },
        )
    )

    async with TrelloOAuthClient("client-id", "client-secret") as client:
        tokens = await client.exchange_code(
            code="authorization-code",
            code_verifier="pkce-verifier",
            redirect_uri="http://localhost:3000/dashboard/trello/callback",
        )

    request = json.loads(route.calls.last.request.content)
    assert request["client_id"] == "client-id"
    assert request["client_secret"] == "client-secret"
    assert request["grant_type"] == "authorization_code"
    assert request["code_verifier"] == "pkce-verifier"
    assert tokens.access_token == "access-value"
    assert tokens.refresh_token == "refresh-value"


@pytest.mark.asyncio
async def test_oauth_authorization_url_binds_state_and_pkce_to_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRELLO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "TRELLO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings,
        "TRELLO_OAUTH_CALLBACK_URL",
        "http://localhost:3000/dashboard/trello/callback",
    )
    monkeypatch.setattr(
        settings,
        "TRELLO_OAUTH_SCOPES",
        "read:board:trello offline_access",
    )
    captured: dict[str, object] = {}

    async def capture_state(_repository: ConnectionRepository, **values: object) -> None:
        captured.update(values)

    monkeypatch.setattr(ConnectionRepository, "create_oauth_state", capture_state)
    workspace_id = uuid4()
    user_id = uuid4()
    service = TrelloConnectionService(None, workspace_id, user_id)  # type: ignore[arg-type]

    parsed = urlparse(await service.authorization_url())
    query = parse_qs(parsed.query)
    verifier = encryption.decrypt(str(captured["encrypted_code_verifier"]))
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    assert parsed.netloc == "auth.atlassian.com"
    assert parsed.path == "/authorize"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://localhost:3000/dashboard/trello/callback"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge"] == [expected_challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert captured["workspace_id"] == workspace_id
    assert captured["user_id"] == user_id
    assert captured["state_hash"] == hashlib.sha256(query["state"][0].encode()).hexdigest()


@pytest.mark.asyncio
async def test_token_authorization_url_uses_trello_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRELLO_API_KEY", "trello-api-key")
    monkeypatch.setattr(
        settings,
        "TRELLO_TOKEN_RETURN_URL",
        "http://localhost:3000/dashboard/trello/callback",
    )
    monkeypatch.setattr(settings, "TRELLO_TOKEN_SCOPE", "read")
    monkeypatch.setattr(settings, "TRELLO_TOKEN_EXPIRATION", "never")
    captured: dict[str, object] = {}

    async def capture_state(_repository: ConnectionRepository, **values: object) -> None:
        captured.update(values)

    monkeypatch.setattr(ConnectionRepository, "create_oauth_state", capture_state)
    service = TrelloConnectionService(None, uuid4(), uuid4())  # type: ignore[arg-type]

    parsed = urlparse(await service.token_authorization_url())
    query = parse_qs(parsed.query)
    return_url = urlparse(query["return_url"][0])
    return_query = parse_qs(return_url.query)

    assert parsed.netloc == "trello.com"
    assert parsed.path == "/1/authorize"
    assert query["key"] == ["trello-api-key"]
    assert query["scope"] == ["read"]
    assert query["expiration"] == ["never"]
    assert query["response_type"] == ["token"]
    assert query["callback_method"] == ["fragment"]
    assert return_url.path == "/dashboard/trello/callback"
    assert len(return_query["state"][0]) >= 32
    assert captured["state_hash"] == hashlib.sha256(return_query["state"][0].encode()).hexdigest()


@pytest.mark.asyncio
@respx.mock
async def test_oauth_error_response_does_not_leak_client_secret() -> None:
    respx.post("https://auth.atlassian.com/oauth/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )

    async with TrelloOAuthClient("client-id", "private-client-secret") as client:
        with pytest.raises(TrelloOAuthError) as error:
            await client.refresh("private-refresh-token")

    assert error.value.status_code == 400
    assert "private-client-secret" not in str(error.value)
    assert "private-refresh-token" not in str(error.value)
