"""Pydantic schemas for Skill execution Runs and Insights."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunCreateRequest(BaseModel):
    """Payload to trigger a new skill run."""

    skill_id: UUID
    client_id: UUID | None = None
    trigger: str = Field(default="manual", pattern="^(manual|scheduled|webhook)$")
    max_tokens: int = Field(default=8000, ge=1000, le=32000)


class InsightResponse(BaseModel):
    """Structured insight generated during a skill run."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    workspace_id: UUID
    client_id: UUID | None
    category: str
    title: str
    detail: str
    severity_or_priority: str | None
    confidence: float
    source_refs: list[dict[str, Any]]
    feedback: str | None
    feedback_notes: str | None
    created_at: datetime


class RunResponse(BaseModel):
    """Summary representation of a skill run."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    skill_id: UUID
    workspace_id: UUID
    user_id: UUID | None
    client_id: UUID | None
    skill_name: str | None = None
    client_name: str | None = None
    status: str
    trigger: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    citations_valid: bool
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class RunDetailResponse(RunResponse):
    """Detailed representation of a skill run with output payload and individual insights."""

    output_json: dict[str, Any] | None
    insights: list[InsightResponse] = Field(default_factory=list)


class InsightFeedbackRequest(BaseModel):
    """Payload to provide quality feedback on an insight."""

    feedback: Literal["thumbs_up", "thumbs_down"]
    feedback_notes: str | None = Field(default=None, max_length=1000)
