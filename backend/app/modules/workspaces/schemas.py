import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.workspaces.models import MembershipRole


class WorkspaceCreateRequest(BaseModel):
    """Payload to create a new workspace."""

    name: str = Field(min_length=1, max_length=100, description="Workspace name")
    slug: str | None = Field(
        default=None, max_length=120, description="Optional custom unique slug"
    )


class WorkspaceResponse(BaseModel):
    """Workspace representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID
    created_at: datetime


class MembershipResponse(BaseModel):
    """Workspace membership information."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role: MembershipRole
    created_at: datetime


class WorkspaceWithRoleResponse(BaseModel):
    """Workspace details along with requesting user's membership role."""

    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID
    role: MembershipRole
    created_at: datetime
