"""Pydantic schemas for Slack Integration and Delivery Management."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SlackAuthorizationResponse(BaseModel):
    """Response containing Slack OAuth authorization URL."""

    authorization_url: str


class SlackCallbackRequest(BaseModel):
    """Payload to complete Slack OAuth authorization."""

    code: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    workspace_id: UUID


class SlackConnectionStatus(BaseModel):
    """Status of Slack connection for the active workspace."""

    connected: bool
    workspace_id: UUID | None = None
    team_id: str | None = None
    team_name: str | None = None
    bot_user_id: str | None = None
    status: str = "disconnected"
    updated_at: datetime | None = None


class SlackChannelResponse(BaseModel):
    """Representation of an accessible Slack channel."""

    id: str
    name: str
    is_private: bool = False
    is_channel: bool = True
    num_members: int = 0
    topic: str = ""


class UnsubscribeRequest(BaseModel):
    """Payload to unsubscribe from scheduled digests."""

    email: str = Field(..., min_length=5)
    token: str | None = None


class UnsubscribeResponse(BaseModel):
    """Response message after unsubscribing."""

    success: bool
    message: str
