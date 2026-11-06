import base64
import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.encryption import encryption
from app.modules.auth.models import User
from app.modules.connections.models import ProviderAccount
from app.modules.connections.repository import ConnectionRepository
from app.modules.trello.client import TrelloAPIError, TrelloClient
from app.modules.trello.models import TrelloComment, TrelloSource
from app.modules.trello.oauth import TrelloOAuthClient, TrelloOAuthError
from app.modules.trello.service import TrelloConnectionService
from app.modules.trello.sync import sync_source_data
from app.modules.trello.webhooks import (
    trello_webhook_signature,
    verify_trello_webhook_signature,
)
from app.modules.workspaces.models import Workspace


@pytest.mark.asyncio
async def test_upsert_connection_compiles_against_unique_model_constraint() -> None:
    account_result = Mock()
    account_result.scalar_one.return_value = ProviderAccount(
        user_id=uuid4(),
        provider="trello",
        encrypted_token="encrypted-token",
        status="active",
        external_account_id="trello-user-id",
        external_username="trello-user",
    )
    link_result = Mock()
    link_result.scalar_one_or_none.return_value = None
    db = Mock()
    db.execute = AsyncMock(side_effect=[account_result, link_result])
    db.flush = AsyncMock()
    repository = ConnectionRepository(db)

    await repository.upsert_provider_connection(
        workspace_id=uuid4(),
        provider="trello",
        user_id=uuid4(),
        encrypted_token="encrypted-token",
        external_account_id="trello-user-id",
        external_username="trello-user",
    )

    statement = db.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_provider_accounts_user_provider_external" in sql
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
    assert route.calls.last.request.headers["Authorization"].lower().startswith("bearer ")
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
async def test_list_board_cards_paginates_by_last_activity() -> None:
    page = [
        {"id": f"card-{index}", "dateLastActivity": "2026-01-01T00:00:00.000Z"}
        for index in range(1000)
    ]
    route = respx.get("https://api.trello.com/1/boards/board-1/cards").mock(
        side_effect=[
            httpx.Response(200, json=page),
            httpx.Response(200, json=[{"id": "card-last"}]),
        ]
    )

    async with TrelloClient(token="user-token") as client:
        cards = await client.list_board_cards("board-1")

    assert len(cards) == 1001
    assert route.call_count == 2
    assert route.calls[1].request.url.params["before"] == "2026-01-01T00:00:00.000Z"


@pytest.mark.asyncio
@respx.mock
async def test_list_board_comments_paginates_by_page_number() -> None:
    page = [{"id": f"action-{index}"} for index in range(1000)]
    route = respx.get("https://api.trello.com/1/boards/board-1/actions").mock(
        side_effect=[
            httpx.Response(200, json=page),
            httpx.Response(200, json=[{"id": "action-last"}]),
        ]
    )

    async with TrelloClient(token="user-token") as client:
        actions = await client.list_board_comments("board-1")

    assert len(actions) == 1001
    assert route.calls[0].request.url.params["page"] == "0"
    assert route.calls[1].request.url.params["page"] == "1"


def test_trello_webhook_signature_requires_exact_body_and_callback_url() -> None:
    body = b'{"action":{"id":"action-1"}}'
    callback_url = "https://example.test/api/v1/connections/trello/webhooks"
    signature = trello_webhook_signature(body, "application-secret", callback_url)

    assert verify_trello_webhook_signature(body, signature, "application-secret", callback_url)
    assert not verify_trello_webhook_signature(
        body + b" ", signature, "application-secret", callback_url
    )
    assert not verify_trello_webhook_signature(body, None, "application-secret", callback_url)


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


def test_rate_limiter_multiple_event_loops() -> None:
    """Ensure TrelloRateLimiter can be called across multiple sequential event loops without loop mismatch."""
    import asyncio

    from app.modules.trello.rate_limiter import TrelloRateLimiter

    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(return_value=[1, 1000])
    limiter = TrelloRateLimiter(redis=mock_redis)

    async def run_once() -> None:
        await limiter.acquire("api-key", "token", "/boards/123")

    asyncio.run(run_once())
    asyncio.run(run_once())


@pytest.mark.asyncio
async def test_rate_limiter_graceful_fallback_when_redis_unavailable() -> None:
    """Ensure TrelloRateLimiter does not crash when Redis is unreachable (e.g. on Render without Redis)."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    from app.modules.trello.rate_limiter import TrelloRateLimiter

    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(side_effect=RedisConnectionError("Connection refused"))
    limiter = TrelloRateLimiter(redis=mock_redis)

    # Should log warning and return without raising
    await limiter.acquire("api-key", "token", "/members/me")


def test_redis_rate_limiter_reuses_pool_per_loop_and_rotates_across_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure RedisRateLimiter reuses one ConnectionPool per event loop and replaces it across loops."""
    import asyncio

    from redis.asyncio import ConnectionPool

    from app.modules.trello.rate_limiter import RedisRateLimiter

    created_pools: list[ConnectionPool] = []
    real_from_url = ConnectionPool.from_url

    def spy_from_url(url: str, **kwargs: Any) -> ConnectionPool:
        pool = real_from_url(url, **kwargs)
        created_pools.append(pool)
        return pool

    monkeypatch.setattr(ConnectionPool, "from_url", spy_from_url)

    async def check_within_loop() -> tuple[ConnectionPool, ConnectionPool]:
        first = RedisRateLimiter()
        second = RedisRateLimiter()
        return first.connection_pool, second.connection_pool

    loop1_p1, loop1_p2 = asyncio.run(check_within_loop())
    assert loop1_p1 is loop1_p2
    assert len(created_pools) == 1

    loop2_p1, loop2_p2 = asyncio.run(check_within_loop())
    assert loop2_p1 is loop2_p2
    assert loop2_p1 is not loop1_p1
    assert len(created_pools) == 2


@pytest.mark.asyncio
async def test_sync_source_data_deletes_removed_comments_and_preserves_on_failed_fetch(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: comments deleted in Trello are pruned locally, but preserved on partial/failed comment fetch."""
    monkeypatch.setattr(settings, "TRELLO_WEBHOOK_CALLBACK_URL", "")
    user = User(
        email=f"trello_sync_{uuid4().hex[:6]}@example.com",
        name="Sync Tester",
        hashed_password="hashed_pw_test",
    )
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(
        name="Trello Sync WS",
        slug=f"ws-sync-{uuid4().hex[:6]}",
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()

    conn = await ConnectionRepository(db_session).upsert_provider_connection(
        workspace_id=workspace.id,
        provider="trello",
        user_id=user.id,
        encrypted_token="enc",
        external_account_id=f"acc-{uuid4().hex[:6]}",
        external_username="tester",
    )
    board_ext_id = f"board_{uuid4().hex[:6]}"
    source = TrelloSource(
        workspace_id=workspace.id,
        connection_id=conn.id,
        trello_board_id=board_ext_id,
        name="Board 1",
        url="https://trello.com/b/1",
        excluded=False,
    )
    db_session.add(source)
    await db_session.flush()

    card_ext_id = f"card_{uuid4().hex[:6]}"
    mock_client = AsyncMock(spec=TrelloClient)
    mock_client.get_board.return_value = {"id": board_ext_id, "name": "Board 1"}
    mock_client.list_board_lists.return_value = [{"id": "list-1", "name": "To Do", "closed": False}]
    mock_client.list_board_cards.return_value = [
        {"id": card_ext_id, "idList": "list-1", "name": "Card 1", "desc": "", "closed": False}
    ]
    empty_members: list[dict[str, Any]] = []
    mock_client.list_board_members.return_value = empty_members

    def _make_action(action_id: str, text: str) -> dict[str, Any]:
        return {
            "id": action_id,
            "idMemberCreator": "member-1",
            "date": "2026-10-01T10:00:00.000Z",
            "data": {"text": text, "card": {"id": card_ext_id}},
        }

    # 1. Initial sync with two comments
    act_1 = f"act_1_{uuid4().hex[:6]}"
    act_2 = f"act_2_{uuid4().hex[:6]}"
    mock_client.list_board_comments.return_value = [
        _make_action(act_1, "First comment"),
        _make_action(act_2, "Second comment"),
    ]
    await sync_source_data(db_session, source, mock_client)
    await db_session.flush()

    comments = list(
        (
            await db_session.scalars(
                select(TrelloComment).where(TrelloComment.workspace_id == workspace.id)
            )
        ).all()
    )
    assert {c.trello_action_id for c in comments} == {act_1, act_2}

    # 2. Second comment deleted in Trello -> removed locally
    mock_client.list_board_comments.return_value = [_make_action(act_1, "First comment")]
    await sync_source_data(db_session, source, mock_client)
    await db_session.flush()

    comments_after_delete = list(
        (
            await db_session.scalars(
                select(TrelloComment).where(TrelloComment.workspace_id == workspace.id)
            )
        ).all()
    )
    assert {c.trello_action_id for c in comments_after_delete} == {act_1}

    # 3. Partial / malformed comment payload for the card -> existing comment is preserved
    mock_client.list_board_comments.return_value = [
        {"id": None, "data": {"card": {"id": card_ext_id}, "text": "broken"}}
    ]
    await sync_source_data(db_session, source, mock_client)
    await db_session.flush()

    comments_after_partial = list(
        (
            await db_session.scalars(
                select(TrelloComment).where(TrelloComment.workspace_id == workspace.id)
            )
        ).all()
    )
    assert {c.trello_action_id for c in comments_after_partial} == {act_1}

    # 4. Failed comment fetch -> raises error and preserves existing comment
    mock_client.list_board_comments.side_effect = TrelloAPIError(502, "Comment fetch failed")
    with pytest.raises(TrelloAPIError):
        await sync_source_data(db_session, source, mock_client)

    comments_after_fail = list(
        (
            await db_session.scalars(
                select(TrelloComment).where(TrelloComment.workspace_id == workspace.id)
            )
        ).all()
    )
    assert {c.trello_action_id for c in comments_after_fail} == {act_1}
