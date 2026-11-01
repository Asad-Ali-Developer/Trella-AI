"""Pydantic schemas for Report Schedules and Deliveries."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreateRequest(BaseModel):
    """Payload to create a new report schedule."""

    skill_id: UUID
    client_id: UUID | None = None
    name: str = Field(..., min_length=2, max_length=120)
    cron: str = Field(..., min_length=5, max_length=100)
    timezone: str = Field(default="UTC", max_length=64)
    channel: str = Field(default="email", pattern="^(slack|email|both)$")
    recipients: list[str] = Field(default_factory=list)
    slack_channel_id: str | None = None
    slack_channel_name: str | None = None
    is_delta_only: bool = True
    active: bool = True


class ScheduleUpdateRequest(BaseModel):
    """Payload to update an existing report schedule."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    cron: str | None = Field(default=None, min_length=5, max_length=100)
    timezone: str | None = Field(default=None, max_length=64)
    channel: str | None = Field(default=None, pattern="^(slack|email|both)$")
    recipients: list[str] | None = None
    slack_channel_id: str | None = None
    slack_channel_name: str | None = None
    is_delta_only: bool | None = None
    active: bool | None = None


class ScheduleResponse(BaseModel):
    """Response schema for a report schedule."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    skill_id: UUID
    client_id: UUID | None
    name: str
    cron: str
    timezone: str
    channel: str
    recipients: list[str]
    slack_channel_id: str | None
    slack_channel_name: str | None
    is_delta_only: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    active: bool
    created_at: datetime
    updated_at: datetime


class DeliveryResponse(BaseModel):
    """Response schema for an individual delivery log record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    run_id: UUID
    schedule_id: UUID | None
    channel: str
    recipient: str
    status: str
    attempts: int
    error: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeliveryListResponse(BaseModel):
    """Paginated response of report delivery history."""

    deliveries: list[DeliveryResponse]
    total: int
    skip: int
    limit: int
