from typing import cast

from sentry_sdk.types import Event

from app.core.sentry import before_send, scrub_sensitive


def test_scrub_sensitive_redacts_nested_secrets() -> None:
    payload = {
        "message": "ok",
        "extra": {
            "password": "hidden",
            "user": "asad",
            "request": {"authorization": "Bearer abc", "path": "/health"},
        },
    }
    scrubbed = scrub_sensitive(payload)
    assert scrubbed["message"] == "ok"
    assert scrubbed["extra"]["password"] == "[REDACTED]"
    assert scrubbed["extra"]["user"] == "asad"
    assert scrubbed["extra"]["request"]["authorization"] == "[REDACTED]"
    assert scrubbed["extra"]["request"]["path"] == "/health"


def test_before_send_scrubs_event() -> None:
    event = cast(Event, {"extra": {"access_token": "tok_123", "safe": True}})
    result = before_send(event, {})
    assert result is not None
    assert result["extra"]["access_token"] == "[REDACTED]"
    assert result["extra"]["safe"] is True
