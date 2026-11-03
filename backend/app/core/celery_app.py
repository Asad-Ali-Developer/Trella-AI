from celery import Celery

# Ensure all SQLAlchemy models are registered in the declarative registry
import app.modules.auth.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.delivery.models  # noqa: F401
import app.modules.github.models  # noqa: F401
import app.modules.jira.models  # noqa: F401
import app.modules.runs.models  # noqa: F401
import app.modules.scheduler.models  # noqa: F401
import app.modules.skills.models  # noqa: F401
import app.modules.trello.models  # noqa: F401
import app.modules.workspaces.models  # noqa: F401
from app.core.config import settings

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
