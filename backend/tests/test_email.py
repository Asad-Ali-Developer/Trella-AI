from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest

from app.core import email
from app.core.config import settings
from app.core.mailgun import MailgunClient, MailgunError
from app.workers import tasks


def test_password_reset_email_escapes_url_and_sets_plain_text(monkeypatch) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(tasks, "send_email", sent.append)
    tasks.send_password_reset_email.run(
        "user@example.com",
        "http://localhost:3000/reset-password?token=a&b",
    )

    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "user@example.com"
    plain_part = message.get_body(preferencelist=("plain",))
    assert plain_part is not None
    assert "a&b" in plain_part.get_content()
    html_part = next(part for part in message.walk() if part.get_content_type() == "text/html")
    assert html_part is not None
    assert "token=a&amp;b" in html_part.get_content()


def test_welcome_email_uses_configured_template(monkeypatch) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(tasks, "send_email", sent.append)
    tasks.send_welcome_email.run("user@example.com", "Test User")

    assert len(sent) == 1
    assert "Welcome to DeepClient" in sent[0]["Subject"]
    html_part = next(part for part in sent[0].walk() if part.get_content_type() == "text/html")
    assert html_part is not None
    content = html_part.get_content()
    assert "Test User" in content
    assert "/dashboard" in content
    assert "Connect Your Tools" in content


def test_app_connected_email(monkeypatch) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(tasks, "send_email", sent.append)
    tasks.send_app_connected_email.run(
        recipient="user@example.com",
        name="Asad Ali",
        app_name="GitHub",
        account_username="asad-dev",
        workspace_name="Acme Workspace",
        app_color="#181717",
    )

    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "user@example.com"
    assert "GitHub connected to your DeepClient workspace" in message["Subject"]
    html_part = next(part for part in message.walk() if part.get_content_type() == "text/html")
    assert html_part is not None
    content = html_part.get_content()
    assert "GitHub" in content
    assert "asad-dev" in content
    assert "Acme Workspace" in content
    assert "/dashboard/apps" in content


def test_mailgun_client_send_message(monkeypatch) -> None:
    client = MailgunClient(api_key="key-test", domain="sandbox123.mailgun.org")
    assert client.is_configured

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "<20261024@mailgun.org>", "message": "Queued."}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response

    monkeypatch.setattr("httpx.Client", lambda *args, **kwargs: mock_client)

    result = client.send_message(
        to="user@example.com",
        subject="Hello",
        text="Plain text",
        html="<p>HTML</p>",
    )
    assert result["id"] == "<20261024@mailgun.org>"
    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    assert kwargs["data"]["to"] == "user@example.com"
    assert kwargs["data"]["subject"] == "Hello"


def test_mailgun_fallback_to_smtp(monkeypatch) -> None:
    smtp_sent: list[EmailMessage] = []
    monkeypatch.setattr(email, "send_smtp_email", smtp_sent.append)
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "sandbox123.mailgun.org")
    monkeypatch.setattr(settings, "SMTP_HOST", "localhost")

    # Force Mailgun to fail
    def _failing_send(*args, **kwargs):
        raise MailgunError("Sandbox domain unverified recipient", status_code=403)

    monkeypatch.setattr(MailgunClient, "send_message", _failing_send)

    msg = email.build_email(
        recipient="user@example.com",
        subject="Test Fallback",
        template_name="welcome.html",
        context={"name": "Fallback User", "dashboard_url": "/dashboard"},
        text="Plain text fallback",
    )

    email.send_email(msg)
    assert len(smtp_sent) == 1
    assert smtp_sent[0]["Subject"] == "Test Fallback"
