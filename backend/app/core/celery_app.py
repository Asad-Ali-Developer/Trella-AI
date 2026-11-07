from celery import Celery
from kombu import Queue  # type: ignore[import-untyped]

# Ensure all SQLAlchemy models are registered in the declarative registry
import app.modules.auth.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.context.models  # noqa: F401
import app.modules.delivery.models  # noqa: F401
import app.modules.github.models  # noqa: F401
import app.modules.jira.models  # noqa: F401
import app.modules.runs.models  # noqa: F401
import app.modules.scheduler.models  # noqa: F401
import app.modules.skills.models  # noqa: F401
import app.modules.trello.models  # noqa: F401
import app.modules.workspaces.models  # noqa: F401
from app.core.config import settings

TASK_QUEUES = (
    Queue("critical"),
    Queue("sync"),
    Queue("ai"),
    Queue("delivery"),
)

TASK_ROUTES: dict[str, dict[str, str]] = {
    "app.workers.tasks.send_welcome_email": {"queue": "critical"},
    "app.workers.tasks.send_password_reset_email": {"queue": "critical"},
    "app.workers.tasks.send_app_connected_email": {"queue": "delivery"},
    "app.workers.tasks.deliver_report_task": {"queue": "delivery"},
    "app.workers.tasks.sync_trello_source": {"queue": "sync"},
    "app.workers.tasks.sync_github_repository": {"queue": "sync"},
    "app.workers.tasks.check_due_schedules_task": {"queue": "sync"},
    "app.workers.tasks.execute_skill_run": {"queue": "ai"},
    "app.workers.tasks.execute_scheduled_run_task": {"queue": "ai"},
    "app.workers.tasks.index_source_task": {"queue": "ai"},
    "app.workers.tasks.index_repository_task": {"queue": "ai"},
}

celery_app = Celery(
    "client_insights",
    broker=settings.REDIS_URL,
)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue="sync",
    task_queues=TASK_QUEUES,
    task_routes=TASK_ROUTES,
    broker_connection_timeout=2,
    broker_connection_retry_on_startup=True,
    task_publish_retry=False,
    broker_transport_options={
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "max_retries": 0,
    },
    beat_schedule={
        "check-due-schedules-every-minute": {
            "task": "app.workers.tasks.check_due_schedules_task",
            "schedule": 60.0,
        },
    },
)
celery_app.autodiscover_tasks(["app.workers"])
