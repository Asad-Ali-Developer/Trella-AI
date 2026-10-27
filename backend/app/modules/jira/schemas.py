"""Pydantic schemas for Jira connection and project management."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JiraAuthorizationResponse(BaseModel):
    """Atlassian OAuth redirect payload."""

    authorization_url: str


class JiraCallbackRequest(BaseModel):
    """Payload sent by the frontend OAuth callback page."""

    code: str
    state: str
    workspace_id: UUID | None = None



class JiraConnectionStatus(BaseModel):
    """Current Jira connection status for a workspace."""

    connected: bool
    username: str | None = None
    account_id: UUID | None = None
    site_name: str | None = None
    site_url: str | None = None


class JiraProviderAccountResponse(BaseModel):
    """Reusable Jira account option."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str


class JiraAccountLinkRequest(BaseModel):
    """Request payload to link an existing Jira account."""

    account_id: UUID


class JiraProjectResponse(BaseModel):
    """Jira project representation for client context selection."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    cloud_id: str
    jira_project_id: str
    avatar_url: str | None = None
    included: bool = False
    client_id: UUID | None = None
    sync_status: str = "not_started"
    last_synced_at: datetime | None = None
    sync_error: str | None = None


class JiraProjectSelectionItem(BaseModel):
    """Selection toggle and optional client mapping for a Jira project."""

    project_id: UUID
    included: bool
    client_id: UUID | None = None


class JiraProjectSelectionRequest(BaseModel):
    """Bulk selection update for workspace Jira projects."""

    selections: list[JiraProjectSelectionItem]


class JiraClientOption(BaseModel):
    """Client option for project mapping."""

    id: UUID
    name: str

