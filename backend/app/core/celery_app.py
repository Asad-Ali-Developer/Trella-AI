from celery import Celery

from app.core.config import settings

# Ensure all SQLAlchemy models are registered in the declarative registry
import app.modules.auth.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.github.models  # noqa: F401
import app.modules.jira.models  # noqa: F401
import app.modules.runs.models  # noqa: F401
import app.modules.skills.models  # noqa: F401
import app.modules.trello.models  # noqa: F401
import app.modules.workspaces.models  # noqa: F401

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
)
celery_app.autodiscover_tasks(["app.workers"])

