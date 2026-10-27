"""Mailgun API client for sending transactional emails."""

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.core.mailgun")


class MailgunError(Exception):
    """Exception raised when Mailgun API calls fail."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MailgunClient:
    """HTTP Client for sending emails via the Mailgun v3 Messages REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        domain: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.MAILGUN_API_KEY
        self.domain = domain if domain is not None else settings.MAILGUN_DOMAIN
        self.base_url = (base_url or settings.MAILGUN_API_BASE_URL).rstrip("/")

    @property
    def is_configured(self) -> bool:
        """Return True if both API key and domain are provided."""
        return bool(self.api_key and self.domain)

    def send_message(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: str,
        from_email: str | None = None,
    ) -> dict[str, Any]:
        """Send an email using Mailgun's Messages endpoint."""
        if not self.is_configured:
            raise MailgunError(
                "Mailgun is not configured. Provide MAILGUN_API_KEY and MAILGUN_DOMAIN."
            )

        sender = (
            from_email
            or settings.MAILGUN_FROM_EMAIL
            or settings.SMTP_FROM_EMAIL
            or "DeepClient <no-reply@client-insights.local>"
        )

        # In Mailgun sandbox mode, the sender address domain must match the sandbox domain
        if self.domain.startswith("sandbox") and f"@{self.domain}" not in sender:
            display_name = "DeepClient"
            if "<" in sender:
                display_name = sender.split("<")[0].strip() or "DeepClient"
            sender = f"{display_name} <postmaster@{self.domain}>"

        url = f"{self.base_url}/{self.domain}/messages"

        payload = {
            "from": sender,
            "to": to,
            "subject": subject,
            "text": text,
            "html": html,
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    url,
                    auth=("api", self.api_key),
                    data=payload,
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                logger.info(
                    "mailgun_email_sent",
                    recipient=to,
                    subject=subject,
                    message_id=data.get("id"),
                )
                return data
        except httpx.HTTPStatusError as exc:
            logger.error(
                "mailgun_http_error",
                status_code=exc.response.status_code,
                detail=exc.response.text,
            )
            raise MailgunError(
                f"Mailgun returned HTTP {exc.response.status_code}: {exc.response.text}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            logger.error("mailgun_request_failed", error=str(exc))
            raise MailgunError(f"Failed to communicate with Mailgun API: {exc}") from exc
