import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

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
from alembic import context
from app.core.config import settings
from app.db.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata

target_metadata = Base.metadata


def resolve_alembic_database_url() -> str:
    """Resolve the database URL for Alembic migrations, honoring overrides before settings.DATABASE_URL."""
    x_args = context.get_x_argument(as_dictionary=True)
    x_url = (x_args.get("db_url") or x_args.get("sqlalchemy.url") or "").strip()
    if x_url:
        return x_url

    env_url = os.environ.get("ALEMBIC_DATABASE_URL", "").strip()
    if env_url:
        return env_url

    cfg_url = (config.get_main_option("sqlalchemy.url") or "").strip()
    if cfg_url and cfg_url != "driver://user:pass@localhost/dbname":
        return cfg_url

    return settings.DATABASE_URL


config.set_main_option("sqlalchemy.url", resolve_alembic_database_url())

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
