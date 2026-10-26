import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.modules.jira.client import JiraOAuthTokens


async def _setup_user_and_workspace(async_client: AsyncClient) -> tuple[str, str]:
    email = f"jira_tester_{uuid.uuid4().hex[:8]}@example.com"
    signup_resp = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Jira Tester", "password": "Password123!"},
    )
    assert signup_resp.status_code == 201
    async_client.headers["Origin"] = "http://localhost:3000"
    csrf_token = async_client.cookies.get("csrf_token")
    if csrf_token is not None:
        async_client.headers["X-CSRF-Token"] = csrf_token


    ws_resp = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Jira Test Workspace"},
    )
    assert ws_resp.status_code == 201
    workspace_id = ws_resp.json()["id"]
    async_client.headers["X-Workspace-Id"] = workspace_id
    return email, workspace_id


@pytest.mark.asyncio
async def test_jira_authorize_without_credentials(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    _, _ = await _setup_user_and_workspace(async_client)
    monkeypatch.setattr(settings, "JIRA_CLIENT_ID", "")
    monkeypatch.setattr(settings, "JIRA_CLIENT_SECRET", "")

    response = await async_client.get("/api/v1/connections/jira/authorize")
    assert response.status_code == 503
    assert "Jira OAuth is not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_jira_authorize_url_generation(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    _, _ = await _setup_user_and_workspace(async_client)
    monkeypatch.setattr(settings, "JIRA_CLIENT_ID", "test-jira-client-id")
    monkeypatch.setattr(settings, "JIRA_CLIENT_SECRET", "test-jira-secret")

    response = await async_client.get("/api/v1/connections/jira/authorize")
    assert response.status_code == 200
    data = response.json()
    assert "authorization_url" in data
    assert "auth.atlassian.com/authorize" in data["authorization_url"]
    assert "client_id=test-jira-client-id" in data["authorization_url"]
    assert "state=" in data["authorization_url"]


@pytest.mark.asyncio
async def test_jira_status_when_not_connected(
    async_client: AsyncClient,
) -> None:
    _, _ = await _setup_user_and_workspace(async_client)
    response = await async_client.get("/api/v1/connections/jira")
    assert response.status_code == 200
    assert response.json()["connected"] is False


@pytest.mark.asyncio
async def test_jira_complete_authorization_success(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    _, workspace_id = await _setup_user_and_workspace(async_client)
    monkeypatch.setattr(settings, "JIRA_CLIENT_ID", "test-jira-client-id")
    monkeypatch.setattr(settings, "JIRA_CLIENT_SECRET", "test-jira-secret")

    # 1. Start authorization to generate state in DB
    auth_resp = await async_client.get("/api/v1/connections/jira/authorize")
    auth_url = auth_resp.json()["authorization_url"]
    state = auth_url.split("state=")[1].split("&")[0]

    # 2. Mock Atlassian token exchange and user/site endpoints
    mock_tokens = JiraOAuthTokens(
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_in=3600,
        scope="read:jira-work read:jira-user offline_access",
    )

    with (
        patch(
            "app.modules.jira.service.JiraOAuthClient.exchange_code",
            new_callable=AsyncMock,
            return_value=mock_tokens,
        ),
        patch(
            "app.modules.jira.service.JiraClient.get_me",
            new_callable=AsyncMock,
            return_value={"account_id": "jira-12345", "name": "Jira Test User", "email": "jira@example.com"},
        ),
        patch(
            "app.modules.jira.service.JiraClient.get_accessible_resources",
            new_callable=AsyncMock,
            return_value=[{"id": "cloud-site-id", "name": "Acme Jira Cloud", "url": "https://acme.atlassian.net"}],
        ),
        patch(
            "app.modules.jira.service.notify_app_connected",
            new_callable=AsyncMock,
        ) as mock_notify,
    ):
        callback_resp = await async_client.post(
            "/api/v1/connections/jira/callback",
            json={
                "code": "test-code",
                "state": state,
                "workspace_id": workspace_id,
            },
        )
        assert callback_resp.status_code == 200
        data = callback_resp.json()
        assert data["connected"] is True
        assert data["username"] == "Jira Test User"
        assert data["site_name"] == "Acme Jira Cloud"
        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args
        assert kwargs["app_name"] == "Jira"
        assert kwargs["app_color"] == "#1868DB"

    # 3. Verify status endpoint shows connected
    status_resp = await async_client.get("/api/v1/connections/jira")
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True
    assert status_resp.json()["username"] == "Jira Test User"
    assert status_resp.json()["site_name"] == "Acme Jira Cloud"

    # 4. Disconnect
    disconnect_resp = await async_client.delete("/api/v1/connections/jira")
    assert disconnect_resp.status_code == 200
    assert disconnect_resp.json()["connected"] is False


@pytest.mark.asyncio
async def test_jira_clients_list(
    async_client: AsyncClient,
) -> None:
    _, _ = await _setup_user_and_workspace(async_client)
    response = await async_client.get("/api/v1/connections/jira/clients")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_jira_callback_falls_back_when_read_me_missing(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    _, workspace_id = await _setup_user_and_workspace(async_client)
    monkeypatch.setattr(settings, "JIRA_CLIENT_ID", "test-jira-client-id")
    monkeypatch.setattr(settings, "JIRA_CLIENT_SECRET", "test-jira-secret")

    auth_resp = await async_client.get("/api/v1/connections/jira/authorize")
    state = auth_resp.json()["authorization_url"].split("state=")[1].split("&")[0]

    mock_tokens = JiraOAuthTokens(
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_in=3600,
        scope="read:jira-work read:jira-user offline_access",
    )

    with (
        patch(
            "app.modules.jira.service.JiraOAuthClient.exchange_code",
            new_callable=AsyncMock,
            return_value=mock_tokens,
        ),
        patch(
            "app.modules.jira.service.JiraClient.get_me",
            new_callable=AsyncMock,
            return_value=None,  # Simulating 403 insufficientScope on /me
        ),
        patch(
            "app.modules.jira.service.JiraClient.get_myself",
            new_callable=AsyncMock,
            return_value={"accountId": "jira-acc-999", "displayName": "Asad Ali", "emailAddress": "asad@example.com"},
        ),
        patch(
            "app.modules.jira.service.JiraClient.get_accessible_resources",
            new_callable=AsyncMock,
            return_value=[{"id": "site-xyz", "name": "Asad Dev Site", "url": "https://asad-dev.atlassian.net"}],
        ),
        patch(
            "app.modules.jira.service.notify_app_connected",
            new_callable=AsyncMock,
        ),
    ):
        callback_resp = await async_client.post(
            "/api/v1/connections/jira/callback",
            json={
                "code": "test-code",
                "state": state,
                "workspace_id": workspace_id,
            },
        )
        assert callback_resp.status_code == 200
        data = callback_resp.json()
        assert data["connected"] is True
        assert data["username"] == "Asad Ali"
        assert data["site_name"] == "Asad Dev Site"


