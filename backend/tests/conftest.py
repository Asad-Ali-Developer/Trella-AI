import asyncio
import re
from collections.abc import AsyncGenerator
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, pool, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app import main as main_module
from app.core.config import settings
from app.db import session as db_session_module
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.connections import models as _connections_models  # noqa: F401
from app.modules.context import models as _context_models  # noqa: F401
from app.modules.delivery import models as _delivery_models  # noqa: F401
from app.modules.github import models as _github_models  # noqa: F401
from app.modules.jira import models as _jira_models  # noqa: F401
from app.modules.runs import models as _runs_models  # noqa: F401
from app.modules.scheduler import models as _scheduler_models  # noqa: F401
from app.modules.skills import models as _skills_models  # noqa: F401
from app.modules.skills.service import SkillService
from app.modules.trello import models as _trello_models  # noqa: F401
from app.modules.workspaces import models as _workspaces_models  # noqa: F401
from app.workers import tasks as tasks_module

_SAFE_DB_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_db_identity(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "localhost").lower()
    port = parsed.port or 5432
    dbname = parsed.path.lstrip("/")
    return (host, port, dbname)


def assert_test_database_isolated(
    test_url: str | None = None,
    primary_url: str | None = None,
) -> str:
    """Refuse to run tests if TEST_DATABASE_URL is empty or targets DATABASE_URL."""
    resolved_test = (test_url if test_url is not None else settings.TEST_DATABASE_URL).strip()
    resolved_primary = (primary_url if primary_url is not None else settings.DATABASE_URL).strip()
    if not resolved_test:
        raise RuntimeError("Refusing to run tests: TEST_DATABASE_URL must not be empty.")
    if (
        resolved_test == resolved_primary
        or _normalize_db_identity(resolved_test) == _normalize_db_identity(resolved_primary)
    ):
        raise RuntimeError(
            "Refusing to run tests: TEST_DATABASE_URL must not equal DATABASE_URL "
            f"({resolved_test!r})."
        )
    return resolved_test


async def _ensure_test_database_exists(test_url: str) -> None:
    """Create the target test database if it does not already exist."""
    parsed = urlparse(test_url)
    target_db = parsed.path.lstrip("/")
    if not target_db or not _SAFE_DB_IDENTIFIER.match(target_db):
        raise RuntimeError(f"Invalid test database name in TEST_DATABASE_URL: {target_db!r}")

    admin_url = urlunparse(parsed._replace(path="/postgres"))
    admin_engine = create_async_engine(
        admin_url,
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": target_db},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
    finally:
        await admin_engine.dispose()


async def _truncate_all_tables(engine: AsyncEngine) -> None:
    """Truncate all application tables in the test database."""
    table_names = [f'"{table.name}"' for table in Base.metadata.sorted_tables]
    if not table_names:
        return
    stmt = f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"
    async with engine.begin() as conn:
        await conn.execute(text(stmt))


async def _prepare_test_schema() -> None:
    """Verify isolation, create the vector extension + schema, and clean tables at session start."""
    test_url = assert_test_database_isolated()
    await _ensure_test_database_exists(test_url)

    engine = create_async_engine(test_url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await _truncate_all_tables(engine)
    finally:
        await engine.dispose()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Ensure test database isolation, schema creation, and cleanup before tests execute."""
    del session
    asyncio.run(_prepare_test_schema())


@pytest_asyncio.fixture
async def _test_db(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    test_url = assert_test_database_isolated()
    test_engine = create_async_engine(
        test_url,
        poolclass=pool.NullPool,
    )
    committed = False

    def _on_commit(_conn: object) -> None:
        nonlocal committed
        committed = True

    event.listen(test_engine.sync_engine, "commit", _on_commit)

    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    monkeypatch.setattr(db_session_module, "engine", test_engine)
    monkeypatch.setattr(db_session_module, "worker_engine", test_engine)
    monkeypatch.setattr(db_session_module, "async_session_maker", test_session_maker)
    monkeypatch.setattr(db_session_module, "worker_session_maker", test_session_maker)
    monkeypatch.setattr(main_module, "async_session_maker", test_session_maker)
    monkeypatch.setattr(tasks_module, "worker_session_maker", test_session_maker)

    try:
        yield test_session_maker
    finally:
        event.remove(test_engine.sync_engine, "commit", _on_commit)
        if committed:
            await _truncate_all_tables(test_engine)
        await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    _test_db: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with _test_db() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture
async def async_client(
    _test_db: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    async with _test_db() as seed_session:
        await SkillService(seed_session).seed_builtin_skills()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with _test_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
