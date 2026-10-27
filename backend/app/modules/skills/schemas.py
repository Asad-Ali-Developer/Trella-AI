"""Pydantic schemas for Skills and structured insight outputs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CitedSource(BaseModel):
    """Source reference supporting an insight claim."""

    source_id: str
    source_type: Literal["card", "comment", "commit", "project"] = "card"
    title: str | None = None
    url: str | None = None
    valid: bool = True


class NeedInsight(BaseModel):
    """Client need or explicit request."""

    text: str
    priority: Literal["high", "medium", "low"] = "medium"
    sources: list[CitedSource] = Field(default_factory=list)


class PatternInsight(BaseModel):
    """Recurring pattern or behavioral observation."""

    text: str
    sources: list[CitedSource] = Field(default_factory=list)


class StakeholderInsight(BaseModel):
    """Identified stakeholder and their operational role."""

    name: str
    role: str
    sources: list[CitedSource] = Field(default_factory=list)


class RiskInsight(BaseModel):
    """Project risk, blocker, or scope-change flag."""

    text: str
    severity: Literal["high", "medium", "low"] = "medium"
    sources: list[CitedSource] = Field(default_factory=list)


class ClientNeedsReport(BaseModel):
    """Structured report schema for the Client Needs Analyzer skill."""

    client_name: str = "All Clients"
    executive_summary: str = ""
    needs: list[NeedInsight] = Field(default_factory=list)
    patterns: list[PatternInsight] = Field(default_factory=list)
    stakeholders: list[StakeholderInsight] = Field(default_factory=list)
    risks: list[RiskInsight] = Field(default_factory=list)


class SkillBase(BaseModel):
    name: str
    description: str = ""
    prompt_template: str
    scope_json: dict[str, Any] = Field(
        default_factory=lambda: {
            "sources": ["*"],
            "clients": "all",
            "include": ["cards", "comments", "commits"],
        }
    )
    output_schema_json: dict[str, Any] = Field(default_factory=dict)
    model_config_json: dict[str, Any] = Field(
        default_factory=lambda: {
            "provider": "gemini",
            "model": "gemini-3.5-flash",
            "temperature": 0.1,
        }
    )


class SkillCreate(SkillBase):
    slug: str


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_template: str | None = None
    scope_json: dict[str, Any] | None = None
    output_schema_json: dict[str, Any] | None = None
    model_config_json: dict[str, Any] | None = None
    is_active: bool | None = None


class SkillResponse(SkillBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    slug: str
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
