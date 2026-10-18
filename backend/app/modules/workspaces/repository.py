import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workspaces.models import AuditLog, Membership, MembershipRole, Workspace


class WorkspaceRepository:
    """Data access repository for workspaces and memberships."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        """Fetch workspace by ID."""
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Workspace | None:
        """Fetch workspace by unique slug."""
        stmt = select(Workspace).where(Workspace.slug == slug.lower().strip())
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_workspace(self, name: str, slug: str, owner_id: uuid.UUID) -> Workspace:
        """Create and persist a new workspace."""
        workspace = Workspace(
            name=name.strip(),
            slug=slug.lower().strip(),
            owner_id=owner_id,
        )
        self.db.add(workspace)
        await self.db.flush()
        return workspace

    async def get_membership(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Membership | None:
        """Find user membership within a specific workspace."""
        stmt = select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_membership(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        role: MembershipRole,
    ) -> Membership:
        """Create a user membership record for a workspace."""
        membership = Membership(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )
        self.db.add(membership)
        await self.db.flush()
        return membership

    async def get_user_workspaces(
        self,
        user_id: uuid.UUID,
    ) -> list[tuple[Workspace, MembershipRole]]:
        """List all workspaces where user has active membership."""
        stmt = (
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def create_audit_log(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Create an audit log entry for workspace events."""
        log = AuditLog(
            workspace_id=workspace_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata_json or {},
        )
        self.db.add(log)
        await self.db.flush()
        return log
