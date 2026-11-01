"""Extended report schema.

ClientNeedsReportV2 subclasses the existing ClientNeedsReport, so needs,
patterns, stakeholders and risks (and their `sources`) are unchanged. All new
sections are optional with defaults, so older prompts/skills still validate.

NOTE: `sources` on the new models is a plain list of ID strings. The existing
validate_and_enrich_citations() is NOT assumed to cover these; RunService
validates them itself against the input context.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.modules.skills.schemas import ClientNeedsReport

Confidence = Literal["high", "medium", "low", "insufficient_data"]
Level = Literal["high", "medium", "low"]


def _coerce_none_to_list(v: Any) -> Any:
    if v is None:
        empty: list[Any] = []
        return empty
    return v


class HealthDriver(BaseModel):
    text: str
    direction: Literal["positive", "negative"]
    metric_refs: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @field_validator("metric_refs", "sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class Health(BaseModel):
    status: Literal["green", "amber", "red", "insufficient_data"] = "insufficient_data"
    confidence: Confidence = "insufficient_data"
    drivers: list[HealthDriver] = Field(default_factory=list)

    @field_validator("drivers", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


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

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class WorkChurnCause(BaseModel):
    text: str
    confidence: Level = "low"
    sources: list[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class WorkChurn(BaseModel):
    observation: str | None = None
    likely_causes: list[WorkChurnCause] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)

    @field_validator("likely_causes", "metric_refs", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class MoodSwing(BaseModel):
    from_sentiment: str = Field(alias="from")
    to_sentiment: str = Field(alias="to")
    date: str | None = None
    trigger: str | None = None
    evidence: str | None = None
    sources: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class TextWithSources(BaseModel):
    text: str
    metric_refs: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @field_validator("metric_refs", "sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class WeekTone(BaseModel):
    week: str
    sentiment: Literal["negative", "neutral", "positive", "no_data"] = "no_data"
    sources: list[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class Headline(BaseModel):
    status_word: str
    status_word_tone: Literal["positive", "neutral", "negative"] = "neutral"
    rest: str = "."
    summary: str


class Mood(BaseModel):
    trend: Literal["improving", "stable", "declining", "volatile", "insufficient_data"] = (
        "insufficient_data"
    )
    summary: str | None = None
    confidence: Confidence = "insufficient_data"
    limitations: str | None = None
    weekly: list[WeekTone] = Field(default_factory=list)
    swings: list[MoodSwing] = Field(default_factory=list)
    positive_signals: list[TextWithSources] = Field(default_factory=list)

    @field_validator("weekly", "swings", "positive_signals", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class Commitment(BaseModel):
    who: Literal["client", "team", "unknown"] = "unknown"
    text: str
    due: str | None = None
    status: str | None = None
    sources: list[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class DeliveryPerformance(BaseModel):
    verdict: Literal["on_track", "slipping", "at_risk", "insufficient_data"] = "insufficient_data"
    wins: list[TextWithSources] = Field(default_factory=list)
    slips: list[TextWithSources] = Field(default_factory=list)
    open_commitments: list[Commitment] = Field(default_factory=list)

    @field_validator("wins", "slips", "open_commitments", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class RecommendedAction(BaseModel):
    action: str
    why: str
    urgency: Literal["now", "this_week", "this_month"] = "this_week"
    addresses: str | None = None
    sources: list[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


class ClientNeedsReportV2(ClientNeedsReport):
    headline: Headline | None = None
    executive_summary: str = ""
    health: Health = Field(default_factory=Health)
    scope_changes: list[ScopeChange] = Field(default_factory=list)
    work_churn: WorkChurn = Field(default_factory=WorkChurn)
    mood: Mood = Field(default_factory=Mood)
    delivery_performance: DeliveryPerformance = Field(default_factory=DeliveryPerformance)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    changes_since_last_report: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)

    @field_validator("health", "work_churn", "mood", "delivery_performance", mode="before")
    @classmethod
    def _coerce_none_objects(cls, v: Any, info: ValidationInfo) -> Any:
        if v is None and info.field_name:
            defaults = {
                "health": Health,
                "work_churn": WorkChurn,
                "mood": Mood,
                "delivery_performance": DeliveryPerformance,
            }
            factory = defaults.get(info.field_name)
            if factory:
                return factory()
        return v

    @field_validator(
        "scope_changes",
        "recommended_actions",
        "changes_since_last_report",
        "data_gaps",
        "needs",
        "patterns",
        "stakeholders",
        "risks",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _coerce_none_lists(cls, v: Any) -> Any:
        return _coerce_none_to_list(v)


# Fields added by V2 (handled separately in RunService, see service.py).
V2_EXTRA_FIELDS: set[str] = {
    "headline",
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


# ---------------------------------------------------------------------------
# Headline word: must agree with health, so the highlight reflects the client's
# actual condition and never contradicts the health badge.
# ---------------------------------------------------------------------------
_BAND_WORDS: dict[str, tuple[set[str], str, Literal["positive", "neutral", "negative"]]] = {
    "red": ({"slipping", "escalating", "deteriorating", "at risk", "overdue"}, "slipping", "negative"),
    "amber": ({"drifting", "volatile", "stalled", "stretching", "uncertain"}, "drifting", "neutral"),
    "green": ({"steady", "on track", "aligned", "thriving", "warm"}, "steady", "positive"),
    "insufficient_data": ({"unclear"}, "unclear", "neutral"),
}


def normalize_headline(report: Any) -> bool:
    """Force the headline to match health.status. Returns True if it was adjusted."""
    health = getattr(report, "health", None)
    status = getattr(health, "status", "insufficient_data") if health else "insufficient_data"
    band = _BAND_WORDS.get(status, _BAND_WORDS["insufficient_data"])
    allowed, fallback, tone = band
    if getattr(report, "headline", None) is None:
        return False
    word = report.headline.status_word.strip().lower().rstrip(".,")
    changed = False
    if word not in allowed:
        word, changed = fallback, True
    report.headline.status_word = word
    report.headline.status_word_tone = tone
    rest = report.headline.rest.strip()
    if not rest or rest[0] not in ", .":
        rest = "." if not rest else f", {rest}"
    if not rest.endswith("."):
        rest += "."
    report.headline.rest = rest
    if getattr(report, "executive_summary", None) is None:
        report.executive_summary = report.headline.summary
    return changed


def build_stats(metrics: dict[str, Any], report: Any) -> dict[str, Any]:
    """Stat strip, filled from code-computed metrics (None renders as n/a)."""
    scope = metrics.get("scope_changes")
    scope_changes = getattr(report, "scope_changes", []) or []
    if not isinstance(scope, (int, float)):
        scope = sum(
            1 for s in scope_changes if getattr(s, "classification", None) != "clarification"
        )
    health = getattr(report, "health", None)
    health_status = getattr(health, "status", "insufficient_data") if health else "insufficient_data"
    confidence = getattr(health, "confidence", "insufficient_data") if health else "insufficient_data"
    return {
        "health": health_status,
        "confidence": confidence,
        "scope_changes": scope,
        "deadlines_moved": metrics.get("deadlines_moved"),
        "our_reply_gap_days": metrics.get("our_reply_gap_days"),
        "client_comments": metrics.get("client_authored_items"),
    }