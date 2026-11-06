import ast
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.repository import WorkspaceScopedRepository
from app.db.base import Base
from app.db.session import build_engine, build_worker_engine, get_connect_args
from app.modules.auth.models import User
from app.modules.workspaces.models import AuditLog, Membership, MembershipRole, Workspace


@pytest.mark.asyncio
async def test_create_user_and_workspace(db_session: AsyncSession) -> None:
    user = User(
        email="test_" + uuid.uuid4().hex[:8] + "@example.com",
        name="Test User",
        hashed_password="hashed_pw_test",
    )
    db_session.add(user)
    await db_session.flush()
    assert user.id is not None
    assert user.is_active is True

    workspace = Workspace(
        name="Test Agency",
        slug="agency-" + uuid.uuid4().hex[:6],
        owner_id=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()
    assert workspace.id is not None

    membership = Membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=MembershipRole.OWNER,
    )
    db_session.add(membership)
    await db_session.flush()
    assert membership.id is not None


@pytest.mark.asyncio
async def test_workspace_scoped_repository_isolation(db_session: AsyncSession) -> None:
    owner = User(
        email="owner_" + uuid.uuid4().hex[:8] + "@example.com",
        name="Owner",
        hashed_password="pw",
    )
    db_session.add(owner)
    await db_session.flush()

    ws_a = Workspace(name="Workspace A", slug="ws-a-" + uuid.uuid4().hex[:6], owner_id=owner.id)
    ws_b = Workspace(name="Workspace B", slug="ws-b-" + uuid.uuid4().hex[:6], owner_id=owner.id)
    db_session.add_all([ws_a, ws_b])
    await db_session.flush()

    repo_a = WorkspaceScopedRepository(AuditLog, db_session, ws_a.id)
    repo_b = WorkspaceScopedRepository(AuditLog, db_session, ws_b.id)

    log_a = await repo_a.create(
        user_id=owner.id,
        action="workspace.created",
        entity_type="workspace",
        entity_id=str(ws_a.id),
        metadata_json={"ip": "127.0.0.1"},
    )
    assert log_a.workspace_id == ws_a.id

    found_a = await repo_a.get_by_id(log_a.id)
    assert found_a is not None
    assert found_a.id == log_a.id

    # Security check: Workspace B must NOT access Workspace A
    found_b = await repo_b.get_by_id(log_a.id)
    assert found_b is None

    count_b = await repo_b.count()
    assert count_b == 0


def test_alembic_env_and_celery_app_import_context_models() -> None:
    """Regression test: alembic/env.py and core/celery_app.py explicitly import app.modules.context.models."""
    backend_root = Path(__file__).resolve().parents[1]
    for rel_path in ("alembic/env.py", "app/core/celery_app.py"):
        source = (backend_root / rel_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "app.modules.context.models" in imported_modules, f"Missing import in {rel_path}"

    assert "card_summaries" in Base.metadata.tables
    assert "card_embeddings" in Base.metadata.tables


def test_db_session_pool_settings_and_pgbouncer_connect_args() -> None:
    """Regression test: db/session.py applies pool settings and DB_PGBOUNCER statement_cache_size=0."""
    cfg_pgbouncer = Settings(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:6432/testdb",
        DB_POOL_SIZE=12,
        DB_MAX_OVERFLOW=24,
        DB_POOL_RECYCLE=900,
        DB_POOL_TIMEOUT=15,
        DB_PGBOUNCER=True,
    )
    assert get_connect_args(cfg_pgbouncer) == {"statement_cache_size": 0}

    with patch("app.db.session.create_async_engine") as mock_create_engine:
        build_engine(cfg_pgbouncer)
        mock_create_engine.assert_called_once_with(
            cfg_pgbouncer.DATABASE_URL,
            echo=cfg_pgbouncer.DEBUG,
            pool_pre_ping=True,
            pool_size=12,
            max_overflow=24,
            pool_recycle=900,
            pool_timeout=15,
            connect_args={"statement_cache_size": 0},
        )

    with patch("app.db.session.create_async_engine") as mock_create_worker:
        build_worker_engine(cfg_pgbouncer)
        assert mock_create_worker.call_args.kwargs["connect_args"] == {"statement_cache_size": 0}

    cfg_direct = Settings(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        DB_PGBOUNCER=False,
    )
    assert get_connect_args(cfg_direct) == {}
