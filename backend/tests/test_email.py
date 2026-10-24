from email.message import EmailMessage

from app.workers import tasks


def test_password_reset_email_escapes_url_and_sets_plain_text(
    monkeypatch,
) -> None:
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
    assert "Welcome to Client Insights" in sent[0]["Subject"]
    html_part = next(part for part in sent[0].walk() if part.get_content_type() == "text/html")
    assert "Test User" in html_part.get_content()
