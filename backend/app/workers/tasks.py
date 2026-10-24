import asyncio
import smtplib
from datetime import UTC, datetime
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.email import build_email, send_email
from app.core.logging import get_logger
from app.db.session import async_session_maker
from app.modules.connections.models import WorkspaceConnection
from app.modules.github.client import GithubAPIError
from app.modules.github.models import GithubRepository
from app.modules.github.sync import sync_github_repository as sync_github_repository_data
from app.modules.trello.client import TrelloAPIError, TrelloRateLimitError, TrelloServerError
from app.modules.trello.models import TrelloSource
from app.modules.trello.service import TrelloConnectionService
from app.modules.trello.sync import sync_source_data

logger = get_logger("app.workers.trello")


@celery_app.task(
    autoretry_for=(OSError, smtplib.SMTPException),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_welcome_email(recipient: str, name: str) -> None:
    message = build_email(
        recipient=recipient,
        subject="Welcome to Client Insights",
        template_name="welcome.html",
        context={"name": name},
        text=f"Hi {name}, welcome to Client Insights.",
    )
    send_email(message)


@celery_app.task(
    autoretry_for=(OSError, smtplib.SMTPException),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_password_reset_email(recipient: str, reset_url: str) -> None:
    message = build_email(
        recipient=recipient,
        subject="Reset your Client Insights password",
        template_name="password_reset.html",
        context={
            "reset_url": reset_url,
            "expires_minutes": str(settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        },
        text=(
            "Use this link to reset your Client Insights password: "
            f"{reset_url}\nThis link expires in "
            f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes."
        ),
    )
    send_email(message)


async def _sync_trello_source(source_id: UUID) -> None:
    async with async_session_maker() as db:
        source = await db.get(TrelloSource, source_id)
        if source is None or source.excluded:
            return
        source.sync_status = "running"
        source.sync_error = None
        await db.commit()

        connection = await db.get(WorkspaceConnection, source.connection_id)
        if connection is None or connection.status != "active":
            source.sync_status = "failed"
            source.sync_error = "The Trello connection is no longer active."
            await db.commit()
            return

        try:
            service = TrelloConnectionService(db, source.workspace_id, connection.user_id)
            account = await service.connections.get_provider_account(connection)
            if account is None or account.status != "active":
                source.sync_status = "failed"
                source.sync_error = "The Trello account is no longer available."
                await db.commit()
                return
            async with await service._open_client(account) as client:
                await sync_source_data(db, source, client)
            source.sync_status = "completed"
            source.last_synced_at = datetime.now(UTC)
            source.sync_error = None
            await db.commit()
        except Exception as exc:
            sync_error = str(exc) if isinstance(exc, TrelloAPIError) else "Synchronization failed."
            await db.rollback()
            source = await db.get(TrelloSource, source_id)
            if source is not None:
                source.sync_status = "failed"
                source.sync_error = sync_error
            await db.commit()
            logger.exception("trello_source_sync_failed", source_id=str(source_id))
            raise


@celery_app.task(
    name="app.workers.tasks.sync_trello_source",
    autoretry_for=(OSError, TrelloRateLimitError, TrelloServerError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def sync_trello_source(source_id: str) -> None:
    asyncio.run(_sync_trello_source(UUID(source_id)))


async def _sync_github_repository(repository_id: UUID) -> None:
    async with async_session_maker() as db:
        repository = await db.get(GithubRepository, repository_id)
        if repository is None or not repository.included:
            return
        repository.sync_status = "running"
        repository.sync_error = None
        await db.commit()
        try:
            await sync_github_repository_data(db, repository)
            repository.last_synced_at = datetime.now(UTC)
            repository.sync_status = "completed"
            repository.sync_error = None
            await db.commit()
        except Exception as exc:
            message = str(exc) if isinstance(exc, GithubAPIError) else "Synchronization failed."
            await db.rollback()
            repository = await db.get(GithubRepository, repository_id)
            if repository is not None:
                repository.sync_status = "failed"
                repository.sync_error = message
            await db.commit()
            logger.exception("github_repository_sync_failed", repository_id=str(repository_id))
            raise


@celery_app.task(
    name="app.workers.tasks.sync_github_repository",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def sync_github_repository_task(repository_id: str) -> None:
    asyncio.run(_sync_github_repository(UUID(repository_id)))
