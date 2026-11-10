"""Helper to import all SQLAlchemy ORM models, matching alembic/env.py."""

from __future__ import annotations


def import_all_models() -> None:
    """Import every model module so the SQLAlchemy mapper registry is complete."""
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

