import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.workspaces.models import MembershipRole
from app.modules.workspaces.repository import WorkspaceRepository
from app.modules.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceWithRoleResponse,
)


class WorkspaceService:
    """Business logic for workspace lifecycle and membership."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = WorkspaceRepository(db)

    async def create_workspace(
        self,
        request: WorkspaceCreateRequest,
        current_user: User,
    ) -> WorkspaceWithRoleResponse:
        """Create a new workspace, set creator as OWNER, and record audit log."""
        base_slug = self._slugify(request.slug or request.name)
        slug = base_slug

        # Ensure slug uniqueness
        existing = await self.repo.get_by_slug(slug)
        if existing:
            suffix = uuid.uuid4().hex[:6]
            slug = f"{base_slug[:110]}-{suffix}"

        workspace = await self.repo.create_workspace(
            name=request.name,
            slug=slug,
            owner_id=current_user.id,
        )

        # Creator is automatically assigned the OWNER role
        membership = await self.repo.create_membership(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=MembershipRole.OWNER,
        )

        # Audit log creation
        await self.repo.create_audit_log(
            workspace_id=workspace.id,
            user_id=current_user.id,
            action="workspace.created",
            entity_type="workspace",
            entity_id=str(workspace.id),
            metadata_json={"slug": workspace.slug, "name": workspace.name},
        )

        return WorkspaceWithRoleResponse(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            owner_id=workspace.owner_id,
            role=membership.role,
            created_at=workspace.created_at,
        )

    async def list_user_workspaces(
        self,
        current_user: User,
    ) -> list[WorkspaceWithRoleResponse]:
        """Retrieve all workspaces where user is an active member."""
        items = await self.repo.get_user_workspaces(current_user.id)
        return [
            WorkspaceWithRoleResponse(
                id=ws.id,
                name=ws.name,
                slug=ws.slug,
                owner_id=ws.owner_id,
                role=role,
                created_at=ws.created_at,
            )
            for ws, role in items
        ]

    async def get_workspace_details(
        self,
        workspace_id: uuid.UUID,
        current_user: User,
    ) -> WorkspaceWithRoleResponse:
        """Get details for a workspace if user is a member."""
        membership = await self.repo.get_membership(workspace_id, current_user.id)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this workspace.",
            )

        workspace = await self.repo.get_by_id(workspace_id)
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )

        return WorkspaceWithRoleResponse(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            owner_id=workspace.owner_id,
            role=membership.role,
            created_at=workspace.created_at,
        )

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert arbitrary string to URL-safe alphanumeric slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_-]+", "-", text)
        text = text.strip("-")
        return text or "workspace"
