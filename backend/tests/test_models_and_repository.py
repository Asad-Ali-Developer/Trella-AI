import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import WorkspaceScopedRepository
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
