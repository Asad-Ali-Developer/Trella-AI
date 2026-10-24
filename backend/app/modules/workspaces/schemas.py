import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.workspaces.models import MembershipRole


class WorkspaceCreateRequest(BaseModel):
    """Payload to create a new workspace."""

    name: str = Field(min_length=1, max_length=100, description="Workspace name")
    description: str | None = Field(default=None, max_length=2000)
    client_name: str | None = Field(default=None, max_length=255)
    slug: str | None = Field(
        default=None, max_length=120, description="Optional custom unique slug"
    )


class WorkspaceUpdateRequest(BaseModel):
    """Fields that can be changed after a workspace is created."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    client_name: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Workspace name cannot be blank.")
        return normalized


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
    description: str | None = None
    client_name: str | None = None
    slug: str
    owner_id: uuid.UUID
    role: MembershipRole
    created_at: datetime
