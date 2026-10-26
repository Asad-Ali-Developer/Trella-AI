import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings
from app.core.logging import get_logger
from app.core.mailgun import MailgunClient, MailgunError

logger = get_logger("app.core.email")

TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[1] / "templates" / "email"
templates = Environment(
    loader=FileSystemLoader(TEMPLATE_DIRECTORY),
    autoescape=select_autoescape(["html"]),
)


def is_email_configured() -> bool:
    """Return True if any email delivery channel (Mailgun API or SMTP) is configured."""
    has_mailgun = bool(settings.MAILGUN_API_KEY and settings.MAILGUN_DOMAIN)
    has_smtp = bool(settings.SMTP_HOST)
    return has_mailgun or has_smtp


def get_from_email() -> str:
    """Return the resolved default sender address."""
    return (
        settings.MAILGUN_FROM_EMAIL
        or settings.SMTP_FROM_EMAIL
        or "DeepClient <no-reply@client-insights.local>"
    )


def render_email_template(template_name: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template, falling back to structured subdirectories if needed."""
    candidate_paths = [
        template_name,
        f"auth/{template_name}",
        f"notifications/{template_name}",
    ]
    for path in candidate_paths:
        try:
            return templates.get_template(path).render(**context)
        except Exception:
            continue
    return templates.get_template(template_name).render(**context)


def build_email(
    *,
    recipient: str,
    subject: str,
    template_name: str,
    context: dict[str, Any],
    text: str,
) -> EmailMessage:
    """Build a multi-part EmailMessage with plain text and rendered HTML."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = get_from_email()
    message["To"] = recipient
    message.set_content(text)
    html_content = render_email_template(template_name, context)
    message.add_alternative(html_content, subtype="html")
    return message


def send_email(message: EmailMessage) -> None:
    """Send an email using Mailgun API when configured, falling back to SMTP."""
    # 1. Prefer Mailgun API if API key and domain are provided
    if settings.MAILGUN_API_KEY and settings.MAILGUN_DOMAIN:
        plain_body = message.get_body(preferencelist=("plain",))
        plain_text = plain_body.get_content() if plain_body else ""
        html_part = next(
            (part for part in message.walk() if part.get_content_type() == "text/html"),
            None,
        )
        html_content = html_part.get_content() if html_part else ""

        mailgun = MailgunClient()
        try:
            mailgun.send_message(
                to=message["To"],
                subject=message["Subject"],
                text=plain_text,
                html=html_content,
                from_email=message["From"],
            )
            return
        except MailgunError as exc:
            logger.warning(
                "mailgun_delivery_failed",
                to=message["To"],
                subject=message["Subject"],
                error=str(exc),
            )
            if settings.SMTP_HOST:
                logger.info(
                    "falling_back_to_smtp",
                    to=message["To"],
                    smtp_host=settings.SMTP_HOST,
                )
                send_smtp_email(message)
                return
            raise

    # 2. SMTP fallback (e.g. Mailpit locally, or SMTP relay)
    if settings.SMTP_HOST:
        send_smtp_email(message)
        return

    logger.warning(
        "email_delivery_skipped",
        to=message["To"],
        subject=message["Subject"],
        reason="Neither Mailgun nor SMTP is configured",
    )


def send_smtp_email(message: EmailMessage) -> None:
    """Send an email using configured SMTP, without logging credentials."""
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
