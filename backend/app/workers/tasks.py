import asyncio
import smtplib
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.email import build_email, is_email_configured, send_email
from app.core.logging import get_logger
from app.core.mailgun import MailgunError
from app.db.session import worker_session_maker
from app.modules.auth.models import User
from app.modules.connections.models import WorkspaceConnection
from app.modules.github.client import GithubAPIError
from app.modules.github.models import GithubRepository
from app.modules.github.sync import sync_github_repository as sync_github_repository_data
from app.modules.trello.client import TrelloAPIError, TrelloRateLimitError, TrelloServerError
from app.modules.trello.models import TrelloSource
from app.modules.trello.sync import sync_source_data
from app.modules.workspaces.models import Workspace

logger = get_logger("app.workers.tasks")

EMAIL_RETRY_ERRORS = (OSError, smtplib.SMTPException, MailgunError, httpx.HTTPError)


def dispatch_task(task_func: Any, *args: Any, **kwargs: Any) -> None:
    """Enqueue a task via Celery, falling back to direct execution if broker is unavailable."""
    try:
        task_func.delay(*args, **kwargs)
    except Exception as exc:
        logger.warning(
            "celery_broker_unavailable_executing_directly",
            task=getattr(task_func, "__name__", str(task_func)),
            error=str(exc),
        )
        try:
            try:
                asyncio.get_running_loop()
                in_running_loop = True
            except RuntimeError:
                in_running_loop = False
            if in_running_loop:
                threading.Thread(
                    target=task_func,
                    args=args,
                    kwargs=kwargs,
                    daemon=True,
                ).start()
            else:
                task_func(*args, **kwargs)
        except Exception as direct_exc:
            logger.exception(
                "direct_task_execution_failed",
                task=getattr(task_func, "__name__", str(task_func)),
                error=str(direct_exc),
            )


@celery_app.task(
    name="app.workers.tasks.send_welcome_email",
    autoretry_for=EMAIL_RETRY_ERRORS,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_welcome_email(recipient: str, name: str) -> None:
    dashboard_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard"
    support_email = settings.MAILGUN_FROM_EMAIL or settings.SMTP_FROM_EMAIL or "support@deepclient.com"
    message = build_email(
        recipient=recipient,
        subject="Welcome to DeepClient!",
        template_name="welcome.html",
        context={
            "name": name,
            "dashboard_url": dashboard_url,
            "support_email": support_email,
        },
        text=(
            f"Hi {name},\n\n"
            f"Welcome to DeepClient! Your shared client context and AI insights hub is ready.\n\n"
            f"Access your dashboard: {dashboard_url}"
        ),
    )
    send_email(message)


@celery_app.task(
    name="app.workers.tasks.send_password_reset_email",
    autoretry_for=EMAIL_RETRY_ERRORS,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_password_reset_email(recipient: str, reset_url: str) -> None:
    support_email = settings.MAILGUN_FROM_EMAIL or settings.SMTP_FROM_EMAIL or "support@deepclient.com"
    message = build_email(
        recipient=recipient,
        subject="Reset your DeepClient password",
        template_name="password_reset.html",
        context={
            "reset_url": reset_url,
            "expires_minutes": str(settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
            "support_email": support_email,
        },
        text=(
            "Use this link to reset your DeepClient password: "
            f"{reset_url}\nThis link expires in "
            f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes."
        ),
    )
    send_email(message)


@celery_app.task(
    name="app.workers.tasks.send_app_connected_email",
    autoretry_for=EMAIL_RETRY_ERRORS,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_app_connected_email(
    recipient: str,
    name: str,
    app_name: str,
    account_username: str,
    workspace_name: str,
    app_color: str = "#4F46E5",
) -> None:
    dashboard_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard/apps"
    support_email = settings.MAILGUN_FROM_EMAIL or settings.SMTP_FROM_EMAIL or "support@deepclient.com"
    message = build_email(
        recipient=recipient,
        subject=f"{app_name} connected to your DeepClient workspace",
        template_name="notifications/app_connected.html",
        context={
            "name": name,
            "app_name": app_name,
            "account_username": account_username,
            "workspace_name": workspace_name,
            "app_color": app_color,
            "dashboard_url": dashboard_url,
            "support_email": support_email,
        },
        text=(
            f"Hi {name},\n\n"
            f"Your {app_name} account ({account_username}) has been successfully connected to "
            f"your DeepClient workspace '{workspace_name}'.\n\n"
            f"Manage your connected apps: {dashboard_url}"
        ),
    )
    send_email(message)


async def notify_app_connected(
    db: AsyncSession,
    user_id: UUID,
    workspace_id: UUID,
    app_name: str,
    account_username: str,
    app_color: str = "#4F46E5",
) -> None:
    """Send an email notification when a third-party app (GitHub, Trello, etc.) is connected."""
    if not is_email_configured():
        return
    user = await db.get(User, user_id)
    workspace = await db.get(Workspace, workspace_id)
    if user is None or workspace is None:
        logger.warning(
            "notify_app_connected_skipped_missing_entity",
            user_id=str(user_id),
            workspace_id=str(workspace_id),
        )
        return
    dispatch_task(
        send_app_connected_email,
        recipient=user.email,
        name=user.name,
        app_name=app_name,
        account_username=account_username,
        workspace_name=workspace.name,
        app_color=app_color,
    )


async def _sync_trello_source(source_id: UUID) -> None:
    async with worker_session_maker() as db:
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
            from app.modules.trello.service import TrelloConnectionService

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
            dispatch_task(index_source_task, str(source_id))
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
    async with worker_session_maker() as db:
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
            dispatch_task(index_repository_task, str(repository_id))
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


async def _execute_skill_run(run_id: UUID) -> None:
    from app.modules.runs.service import RunService

    async with worker_session_maker() as db:
        service = RunService(db)
        await service.execute_run(run_id)


@celery_app.task(
    name="app.workers.tasks.execute_skill_run",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def execute_skill_run_task(run_id: str) -> None:
    asyncio.run(_execute_skill_run(UUID(run_id)))


async def _check_due_schedules() -> None:
    from app.modules.scheduler.service import ScheduleService

    async with worker_session_maker() as db:
        service = ScheduleService(db)
        due_schedules = await service.find_due_schedules()
        for sched in due_schedules:
            logger.info("enqueuing_due_schedule", schedule_id=str(sched.id), name=sched.name)
            dispatch_task(execute_scheduled_run_task, str(sched.id))


@celery_app.task(
    name="app.workers.tasks.check_due_schedules_task",
    autoretry_for=(OSError,),
    retry_backoff=False,
)
def check_due_schedules_task() -> None:
    """Periodic Celery beat task to scan for due report schedules every minute."""
    asyncio.run(_check_due_schedules())


async def _execute_scheduled_run(schedule_id: UUID) -> None:
    from app.modules.scheduler.service import ScheduleService

    async with worker_session_maker() as db:
        service = ScheduleService(db)
        await service.execute_scheduled_run(schedule_id)


@celery_app.task(
    name="app.workers.tasks.execute_scheduled_run_task",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def execute_scheduled_run_task(schedule_id: str) -> None:
    """Execute an automated report run for a scheduled job."""
    asyncio.run(_execute_scheduled_run(UUID(schedule_id)))


async def _deliver_report(delivery_id: UUID) -> None:
    from app.modules.scheduler.service import ScheduleService

    async with worker_session_maker() as db:
        service = ScheduleService(db)
        await service.dispatch_delivery(delivery_id)


@celery_app.task(
    name="app.workers.tasks.deliver_report_task",
    autoretry_for=EMAIL_RETRY_ERRORS,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def deliver_report_task(delivery_id: str) -> None:
    """Deliver a generated report to its configured channel (Slack or Email)."""
    asyncio.run(_deliver_report(UUID(delivery_id)))


INDEX_LOCK_TTL_SECONDS = settings.INDEX_LOCK_TTL_SECONDS

_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_EXTEND_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], tonumber(ARGV[2]))
else
    return 0
end
"""


async def _acquire_index_lock(
    lock_key: str,
    token: str,
    *,
    ttl_seconds: int | None = None,
    redis: Any = None,
) -> bool:
    """Acquire a distributed Redis lock via SET NX EX. Fails closed when Redis is unavailable."""
    from redis.exceptions import RedisError

    from app.modules.trello.rate_limiter import _get_loop_redis

    effective_ttl = (
        ttl_seconds if ttl_seconds is not None else settings.INDEX_LOCK_TTL_SECONDS
    )
    try:
        client = redis if redis is not None else _get_loop_redis()
        acquired = await client.set(lock_key, token, nx=True, ex=effective_ttl)
        return bool(acquired)
    except (RedisError, OSError) as exc:
        logger.warning(
            "index_lock_redis_unavailable",
            lock_key=lock_key,
            error_type=type(exc).__name__,
        )
        return False


async def _release_index_lock(
    lock_key: str,
    token: str,
    *,
    redis: Any = None,
) -> bool:
    """Atomically release the distributed Redis lock via Lua compare-and-delete."""
    from redis.exceptions import RedisError

    from app.modules.trello.rate_limiter import _get_loop_redis

    try:
        client: Any = redis if redis is not None else _get_loop_redis()
        deleted = await client.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
        return bool(int(deleted or 0) > 0)
    except (RedisError, OSError) as exc:
        logger.warning(
            "index_lock_release_failed",
            lock_key=lock_key,
            error_type=type(exc).__name__,
        )
        return False


async def _extend_index_lock(
    lock_key: str,
    token: str,
    *,
    ttl_seconds: int | None = None,
    redis: Any = None,
) -> bool:
    """Atomically extend the distributed Redis lock TTL via Lua compare-and-expire."""
    from redis.exceptions import RedisError

    from app.modules.trello.rate_limiter import _get_loop_redis

    effective_ttl = (
        ttl_seconds if ttl_seconds is not None else settings.INDEX_LOCK_TTL_SECONDS
    )
    try:
        client = redis if redis is not None else _get_loop_redis()
        eval_fn = getattr(client, "eval", None)
        if eval_fn is None:
            return False
        extended = await eval_fn(
            _EXTEND_LOCK_LUA, 1, lock_key, token, str(effective_ttl)
        )
        return bool(int(extended or 0) > 0)
    except (RedisError, OSError) as exc:
        logger.warning(
            "index_lock_extend_failed",
            lock_key=lock_key,
            error_type=type(exc).__name__,
        )
        return False


async def _index_source(
    source_id: UUID,
    *,
    force: bool = False,
    redis: Any = None,
) -> bool:
    from uuid import uuid4

    from app.modules.context.indexer import IndexingService

    lock_key = f"lock:index:source:{source_id}"
    token = uuid4().hex
    acquired = await _acquire_index_lock(lock_key, token, redis=redis)
    if not acquired:
        logger.info("index_source_skipped_locked", source_id=str(source_id))
        return False

    has_more = False

    async def _heartbeat() -> None:
        await _extend_index_lock(lock_key, token, redis=redis)

    try:
        async with worker_session_maker() as db:
            try:
                service = IndexingService(
                    db,
                    redis=redis,
                    on_batch_complete=_heartbeat,
                )
            except TypeError:
                service = IndexingService(db, redis=redis)
            run_result = await service.index_source(source_id, force=force)
            has_more = bool(getattr(run_result, "has_more", False))
        return True
    finally:
        await _release_index_lock(lock_key, token, redis=redis)
        if has_more:
            logger.info("index_source_reenqueued_remaining_work", source_id=str(source_id))
            dispatch_task(index_source_task, str(source_id))


@celery_app.task(
    name="app.workers.tasks.index_source_task",
    queue="ai",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def index_source_task(source_id: str, force: bool = False) -> bool:
    """Index a Trello source's cards, comments, and card summaries into chunks on the ai queue."""
    return asyncio.run(_index_source(UUID(str(source_id)), force=force))


async def _index_repository(
    repo_id: UUID,
    *,
    force: bool = False,
    redis: Any = None,
) -> bool:
    from uuid import uuid4

    from app.modules.context.indexer import IndexingService

    lock_key = f"lock:index:repository:{repo_id}"
    token = uuid4().hex
    acquired = await _acquire_index_lock(lock_key, token, redis=redis)
    if not acquired:
        logger.info("index_repository_skipped_locked", repository_id=str(repo_id))
        return False

    has_more = False

    async def _heartbeat() -> None:
        await _extend_index_lock(lock_key, token, redis=redis)

    try:
        async with worker_session_maker() as db:
            try:
                service = IndexingService(
                    db,
                    redis=redis,
                    on_batch_complete=_heartbeat,
                )
            except TypeError:
                service = IndexingService(db, redis=redis)
            run_result = await service.index_repository(repo_id, force=force)
            has_more = bool(getattr(run_result, "has_more", False))
        return True
    finally:
        await _release_index_lock(lock_key, token, redis=redis)
        if has_more:
            logger.info(
                "index_repository_reenqueued_remaining_work",
                repository_id=str(repo_id),
            )
            dispatch_task(index_repository_task, str(repo_id))


@celery_app.task(
    name="app.workers.tasks.index_repository_task",
    queue="ai",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def index_repository_task(repo_id: str, force: bool = False) -> bool:
    """Index a GitHub repository's commits into daily commit_group chunks on the ai queue."""
    return asyncio.run(_index_repository(UUID(str(repo_id)), force=force))
