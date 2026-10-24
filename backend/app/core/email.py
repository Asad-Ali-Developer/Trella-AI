import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings

TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[1] / "templates" / "email"
templates = Environment(
    loader=FileSystemLoader(TEMPLATE_DIRECTORY),
    autoescape=select_autoescape(["html"]),
)


def build_email(
    *,
    recipient: str,
    subject: str,
    template_name: str,
    context: dict[str, str],
    text: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(text)
    message.add_alternative(
        templates.get_template(template_name).render(**context),
        subtype="html",
    )
    return message


def send_email(message: EmailMessage) -> None:
    """Send an email using configured SMTP, without logging SMTP credentials."""
    smtp_connection: smtplib.SMTP | smtplib.SMTP_SSL
    if settings.SMTP_USE_SSL:
        smtp_connection = smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=20,
            context=ssl.create_default_context(),
        )
    else:
        smtp_connection = smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=20,
        )

    with smtp_connection as server:
        if settings.SMTP_STARTTLS:
            server.starttls(context=ssl.create_default_context())
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)
