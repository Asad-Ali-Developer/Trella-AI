"""Pydantic schemas for Clients, Client Profiles, and Timelines."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.runs.schemas import InsightResponse, RunResponse


class ClientSummaryResponse(BaseModel):
    """Summary of a client in the workspace."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    cards_count: int = Field(default=0)
    insights_count: int = Field(default=0)
    needs_count: int = Field(default=0)
    risks_count: int = Field(default=0)
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ClientCreateRequest(BaseModel):
    """Payload to create a new client in a workspace."""

    name: str = Field(min_length=1, max_length=255)


class TimelineEvent(BaseModel):
    """Chronological event in the client's lifecycle (commits, cards, runs, risks)."""

    id: str
    event_type: Literal[
        "card_activity",
        "commit",
        "skill_run",
        "risk_identified",
        "need_extracted",
    ]
    title: str
    detail: str | None = None
    timestamp: datetime
    source: str = Field(default="system")
    source_url: str | None = None
    severity_or_priority: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientProfileResponse(BaseModel):
    """Detailed profile of a client aggregating needs, recurring patterns, stakeholders, and timeline."""

    client: ClientSummaryResponse
    total_cards: int
    total_insights: int
    needs: list[InsightResponse] = Field(default_factory=list)
    patterns: list[InsightResponse] = Field(default_factory=list)
    stakeholders: list[InsightResponse] = Field(default_factory=list)
    risks: list[InsightResponse] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    recent_runs: list[RunResponse] = Field(default_factory=list)
