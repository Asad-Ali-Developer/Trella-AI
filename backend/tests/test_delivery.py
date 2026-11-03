"""Automated tests for Report Delivery (Slack Block Kit, Email Digest, Retries)."""

from typing import Any

from typing import Any

import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import build_email
from app.modules.delivery.slack import (
    SlackClient,
    build_slack_block_kit_digest,
)

# ---------------------------------------------------------------------------
# Unit tests: Slack Block Kit generator
# ---------------------------------------------------------------------------


def test_build_slack_block_kit_digest() -> None:
    report_output: dict[str, Any] = {
        "headline": "Weekly Client Synthesis: ACME Inc",
        "needs": [
            {"text": "Needs Stripe integration", "priority": "high"},
            {"text": "Wants dark mode", "priority": "med"},
        ],
        "risks": [
            {"text": "API rate limits reached", "severity": "high"},
        ],
        "patterns": [
            {"text": "Frequent scope changes in sprint 2"},
        ],
    }
    report_url = "http://localhost:3000/dashboard/reports/123"
    blocks = build_slack_block_kit_digest(
        workspace_name="Design Agency",
        client_name="ACME Inc",
        report_output=report_output,
        report_url=report_url,
    )

    assert len(blocks) >= 6
    # Header block
    assert blocks[0]["type"] == "header"
    assert "ACME Inc" in blocks[0]["text"]["text"]

    # Needs block
    needs_block = next(
        (b for b in blocks if "Key Client Needs" in b.get("text", {}).get("text", "")), None
    )
    assert needs_block is not None
    assert "Needs Stripe integration" in needs_block["text"]["text"]

    # Action block with button
    action_block = next((b for b in blocks if b["type"] == "actions"), None)
    assert action_block is not None
    btn = action_block["elements"][0]
    assert btn["type"] == "button"
    assert btn["url"] == report_url


# ---------------------------------------------------------------------------
# Unit tests: SlackClient with respx mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_slack_client_post_message() -> None:
    client = SlackClient(token="xoxb-test-bot-token")
    respx.post("https://slack.com/api/chat.postMessage").mock(
        return_value=Response(200, json={"ok": True, "channel": "C12345", "ts": "123456.789"})
    )

    result = await client.post_message(
        channel="C12345",
        text="Hello team!",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "Hello team!"}}],
    )
    assert result["ok"] is True
    assert result["channel"] == "C12345"


@pytest.mark.asyncio
@respx.mock
async def test_slack_client_list_conversations() -> None:
    client = SlackClient(token="xoxb-test-bot-token")
    respx.get("https://slack.com/api/conversations.list").mock(
        return_value=Response(
            200,
            json={
                "ok": True,
                "channels": [
                    {"id": "C01", "name": "general", "is_private": False, "num_members": 12},
                    {"id": "C02", "name": "client-acme", "is_private": True, "num_members": 4},
                ],
            },
        )
    )

    channels = await client.list_conversations()
    assert len(channels) == 2
    assert channels[0]["name"] == "general"
    assert channels[1]["is_private"] is True


# ---------------------------------------------------------------------------
# Unit tests: Email digest & Unsubscribe headers
# ---------------------------------------------------------------------------


def test_email_digest_headers() -> None:
    headers: dict[str, str] = {
        "List-Unsubscribe": "<http://localhost:3000/dashboard/schedules?unsubscribe=test@example.com>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    context: dict[str, Any] = {
        "headline": "Synthesis for Test",
        "target_name": "Test Client",
        "workspace_name": "Test WS",
        "needs": [{"text": "More features", "priority": "high"}],
        "risks": [{"text": "Potential delivery delays", "severity": "medium"}],
        "patterns": [{"text": "Consistent weekly velocity"}],
        "report_url": "http://localhost:3000/dashboard/reports/abc",
        "unsubscribe_url": "http://localhost:3000/dashboard/schedules?unsubscribe=test@example.com",
    }
    msg = build_email(
        recipient="user@example.com",
        subject="Your digest",
        template_name="notifications/report_digest.html",
        context=context,
        text="Plain text body",
        headers=headers,
    )
    assert (
        msg["List-Unsubscribe"]
        == "<http://localhost:3000/dashboard/schedules?unsubscribe=test@example.com>"
    )
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg["To"] == "user@example.com"


# ---------------------------------------------------------------------------
# API tests: Unsubscribe endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsubscribe_endpoint(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    res = await async_client.post(
        "/api/v1/delivery/unsubscribe",
        json={"email": "client_optout@example.com"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "unsubscribed" in data["message"]
