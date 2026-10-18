from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from app.core.config import settings
from app.core.logging import SENSITIVE_PATTERN


def scrub_sensitive(value: Any) -> Any:
    """Recursively redact secrets so they are never sent to Sentry."""
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for key, nested in value.items():
            if SENSITIVE_PATTERN.search(str(key)):
                scrubbed[key] = "[REDACTED]"
            else:
                scrubbed[key] = scrub_sensitive(nested)
        return scrubbed
    if isinstance(value, list):
        return [scrub_sensitive(item) for item in value]
    return value


def before_send(event: Event, hint: Hint) -> Event | None:
    """Strip credentials from Sentry events before transport."""
    return cast(Event, scrub_sensitive(event))


def init_sentry() -> None:
    """Initialize Sentry when a DSN is configured. No-op in local/test without DSN."""
    if not settings.SENTRY_DSN:
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        send_default_pii=False,
        before_send=before_send,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
        traces_sample_rate=0.0,
    )
