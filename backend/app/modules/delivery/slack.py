"""Slack API client and Block Kit digest builder."""

from typing import Any, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.modules.delivery.slack")


class SlackAPIError(Exception):
    """Exception raised when a Slack API request fails."""

    def __init__(self, message: str, status_code: int = 400, error_code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class SlackClient:
    """HTTP client for Slack OAuth 2.0 and Web API."""

    def __init__(self, token: str | None = None, base_url: str = "https://slack.com/api") -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange temporary OAuth code for access token and workspace metadata."""
        url = f"{self.base_url}/oauth.v2.access"
        data = {
            "client_id": settings.SLACK_CLIENT_ID,
            "client_secret": settings.SLACK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            payload = response.json()
            if not payload.get("ok"):
                error_code = payload.get("error", "oauth_failed")
                raise SlackAPIError(
                    f"Slack OAuth exchange failed: {error_code}",
                    status_code=400,
                    error_code=error_code,
                )
            return cast(dict[str, Any], payload)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def list_conversations(self, types: str = "public_channel,private_channel") -> list[dict[str, Any]]:
        """List Slack channels accessible to the bot."""
        url = f"{self.base_url}/conversations.list"
        params = {
            "types": types,
            "exclude_archived": "true",
            "limit": "200",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params, headers=self._headers())
            payload = response.json()
            if not payload.get("ok"):
                error_code = payload.get("error", "list_failed")
                raise SlackAPIError(
                    f"Failed to list Slack channels: {error_code}",
                    status_code=400,
                    error_code=error_code,
                )
            channels: list[dict[str, Any]] = payload.get("channels", [])
            return [
                {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "is_private": ch.get("is_private", False),
                    "is_channel": ch.get("is_channel", True),
                    "num_members": ch.get("num_members", 0),
                    "topic": ch.get("topic", {}).get("value", ""),
                }
                for ch in channels
            ]

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def post_message(
        self,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Post a Block Kit message or fallback text to a Slack channel."""
        url = f"{self.base_url}/chat.postMessage"
        body: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if blocks:
            body["blocks"] = blocks

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=body, headers=self._headers())
            payload = response.json()
            if not payload.get("ok"):
                error_code = payload.get("error", "post_failed")
                raise SlackAPIError(
                    f"Failed to post Slack message to channel {channel}: {error_code}",
                    status_code=400,
                    error_code=error_code,
                )
            return cast(dict[str, Any], payload)


def build_slack_block_kit_digest(
    workspace_name: str,
    client_name: str | None,
    report_output: dict[str, Any],
    report_url: str,
) -> list[dict[str, Any]]:
    """Format an AI report run into rich, accessible Slack Block Kit blocks."""
    blocks: list[dict[str, Any]] = []

    # 1. Header Block
    target_name = client_name or "All Clients"
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"📊 DeepClient Digest • {target_name}",
            "emoji": True,
        },
    })

    # 2. Context metadata block
    headline = report_output.get("headline") or "Scheduled Client Insights & Progress Report"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{headline}*\nWorkspace: *{workspace_name}* | Client: *{target_name}*",
        },
    })
    blocks.append({"type": "divider"})

    # 3. Needs Section
    needs = report_output.get("needs", [])[:3]
    if needs:
        need_lines = []
        for n in needs:
            priority = n.get("priority", "med")
            icon = "🔴" if priority == "high" else "🟡" if priority == "med" else "🔵"
            need_lines.append(f"{icon} *{n.get('text')}*")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Key Client Needs:*\n" + "\n".join(need_lines),
            },
        })

    # 4. Risks Section
    risks = report_output.get("risks", [])[:3]
    if risks:
        risk_lines = []
        for r in risks:
            severity = r.get("severity", "med")
            icon = "⚠️" if severity in ("high", "critical") else "⚡"
            risk_lines.append(f"{icon} *{r.get('text')}*")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Identified Risks:*\n" + "\n".join(risk_lines),
            },
        })

    # 5. Patterns Section
    patterns = report_output.get("patterns", [])[:2]
    if patterns:
        pattern_lines = [f"• {p.get('text')}" for p in patterns]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Observed Patterns:*\n" + "\n".join(pattern_lines),
            },
        })

    blocks.append({"type": "divider"})

    # 6. Action button: View Full Report
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View Full Report in DeepClient ↗",
                    "emoji": True,
                },
                "url": report_url,
                "style": "primary",
            }
        ],
    })

    # 7. Privacy warning context footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "🔒 _Delivered securely by DeepClient. Only members of this channel can view this digest._",
            }
        ],
    })

    return blocks
