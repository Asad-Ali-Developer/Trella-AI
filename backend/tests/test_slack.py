"""Automated tests for Slack OAuth Connection and Channel Management."""

import uuid
from unittest.mock import patch

import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


@pytest.mark.asyncio
async def test_slack_oauth_flow_and_channels(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 1. Sign up user & create workspace
    email = f"slackuser_{uuid.uuid4().hex[:6]}@example.com"
    signup_res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Slack Manager", "password": "Password123!"},
    )
    assert signup_res.status_code == 201
    csrf_token = async_client.cookies.get("csrf_token")
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf_token or ""}

    ws_res = await async_client.post(
        "/api/v1/workspaces",
        json={"name": "Slack Test WS", "slug": f"ws-slack-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert ws_res.status_code == 201
    workspace_id = ws_res.json()["id"]
    headers["X-Workspace-ID"] = workspace_id

    # 2. Check initial status -> disconnected
    status_res = await async_client.get("/api/v1/connections/slack", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["connected"] is False

    # 3. Test authorize URL generation
    with patch.object(settings, "SLACK_CLIENT_ID", "test_slack_client_id"), patch.object(
        settings, "SLACK_CLIENT_SECRET", "test_slack_secret"
    ):
        auth_res = await async_client.get("/api/v1/connections/slack/authorize", headers=headers)
        assert auth_res.status_code == 200
        auth_url = auth_res.json()["authorization_url"]
        assert "slack.com/oauth/v2/authorize" in auth_url
        assert "client_id=test_slack_client_id" in auth_url

    # 4. Mock Slack OAuth code exchange
    with respx.mock(assert_all_called=False) as slack_mock:
        slack_mock.post("https://slack.com/api/oauth.v2.access").mock(
            return_value=Response(
                200,
                json={
                    "ok": True,
                    "access_token": "xoxb-dummy-test-token",
                    "bot_user_id": "U123BOT",
                    "team": {"id": "T998877", "name": "Acme Slack Workspace"},
                },
            )
        )
        slack_mock.get("https://slack.com/api/conversations.list").mock(
            return_value=Response(
                200,
                json={
                    "ok": True,
                    "channels": [
                        {"id": "C_CLIENT", "name": "client-updates", "is_private": False, "num_members": 8},
                        {"id": "C_DEV", "name": "dev-team", "is_private": True, "num_members": 5},
                    ],
                },
            )
        )

        # Complete authorization with state from authorize call
        state = auth_url.split("state=")[-1]
        callback_res = await async_client.post(
            "/api/v1/connections/slack/callback",
            json={
                "code": "test_slack_oauth_code",
                "state": state,
                "workspace_id": workspace_id,
            },
            headers=headers,
        )
        assert callback_res.status_code == 200
        conn_data = callback_res.json()
        assert conn_data["connected"] is True
        assert conn_data["team_id"] == "T998877"
        assert conn_data["team_name"] == "Acme Slack Workspace"

        # 5. List channels
        channels_res = await async_client.get("/api/v1/connections/slack/channels", headers=headers)
        assert channels_res.status_code == 200
        channels = channels_res.json()
        assert len(channels) == 2
        assert channels[0]["name"] == "client-updates"

        # 6. Disconnect
        disconnect_res = await async_client.delete("/api/v1/connections/slack", headers=headers)
        assert disconnect_res.status_code == 200
        assert disconnect_res.json()["connected"] is False
