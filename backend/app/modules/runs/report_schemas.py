"""Extended report schema.

ClientNeedsReportV2 subclasses the existing ClientNeedsReport, so needs,
patterns, stakeholders and risks (and their `sources`) are unchanged. All new
sections are optional with defaults, so older prompts/skills still validate.

NOTE: `sources` on the new models is a plain list of ID strings. The existing
validate_and_enrich_citations() is NOT assumed to cover these; RunService
validates them itself against the input context.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.skills.schemas import ClientNeedsReport

Confidence = Literal["high", "medium", "low", "insufficient_data"]
Level = Literal["high", "medium", "low"]


class HealthDriver(BaseModel):
    text: str
    direction: Literal["positive", "negative"]
    metric_refs: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Health(BaseModel):
    status: Literal["green", "amber", "red", "insufficient_data"] = "insufficient_data"
    confidence: Confidence = "insufficient_data"
    drivers: list[HealthDriver] = Field(default_factory=list)


class ScopeChange(BaseModel):
    classification: Literal["clarification", "addition", "removal", "reversal", "reprioritization"]
    text: str
    before: str | None = None
    after: str | None = None
    impact: Level = "low"
    date: str | None = None
    interpretation: str | None = None
    evidence: str | None = None
    sources: list[str] = Field(default_factory=list)


class WorkChurnCause(BaseModel):
    text: str
    confidence: Level = "low"
    sources: list[str] = Field(default_factory=list)


class WorkChurn(BaseModel):
    observation: str | None = None
    likely_causes: list[WorkChurnCause] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)


class MoodSwing(BaseModel):
    from_sentiment: str = Field(alias="from")
    to_sentiment: str = Field(alias="to")
    date: str | None = None
    trigger: str | None = None
    evidence: str | None = None
    sources: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class TextWithSources(BaseModel):
    text: str
    metric_refs: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Mood(BaseModel):
    trend: Literal["improving", "stable", "declining", "volatile", "insufficient_data"] = (
        "insufficient_data"
    )
    summary: str | None = None
    confidence: Confidence = "insufficient_data"
    limitations: str | None = None
    swings: list[MoodSwing] = Field(default_factory=list)
    positive_signals: list[TextWithSources] = Field(default_factory=list)


class Commitment(BaseModel):
    who: Literal["client", "team", "unknown"] = "unknown"
    text: str
    due: str | None = None
    status: str | None = None
    sources: list[str] = Field(default_factory=list)


class DeliveryPerformance(BaseModel):
    verdict: Literal["on_track", "slipping", "at_risk", "insufficient_data"] = "insufficient_data"
    wins: list[TextWithSources] = Field(default_factory=list)
    slips: list[TextWithSources] = Field(default_factory=list)
    open_commitments: list[Commitment] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    action: str
    why: str
    urgency: Literal["now", "this_week", "this_month"] = "this_week"
    addresses: str | None = None
    sources: list[str] = Field(default_factory=list)


class ClientNeedsReportV2(ClientNeedsReport):
    executive_summary: str | None = None
    health: Health = Field(default_factory=Health)
    scope_changes: list[ScopeChange] = Field(default_factory=list)
    work_churn: WorkChurn = Field(default_factory=WorkChurn)
    mood: Mood = Field(default_factory=Mood)
    delivery_performance: DeliveryPerformance = Field(default_factory=DeliveryPerformance)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    changes_since_last_report: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


# Fields added by V2 (handled separately in RunService, see service.py).
V2_EXTRA_FIELDS: set[str] = {
    "executive_summary",
    "health",
    "scope_changes",
    "work_churn",
    "mood",
    "delivery_performance",
    "recommended_actions",
    "changes_since_last_report",
    "data_gaps",
}