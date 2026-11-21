"""Pydantic schemas for POST /api/v1/search."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SearchRequest(BaseModel):
    """Payload for POST /api/v1/search."""

    query: str = Field(min_length=1)
    client_id: UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = Field(default=10, ge=1, le=20)


class SearchResultItem(BaseModel):
    """Single search result chunk with parent identification and signal ranks."""

    chunk_id: UUID
    parent_type: str
    parent_id: UUID
    title: str = ""
    url: str = ""
    text: str
    score: float
    signal_ranks: dict[str, int | None]


class SearchResponse(BaseModel):
    """Response payload for POST /api/v1/search."""

    results: list[SearchResultItem]
    cached: bool
    timings_ms: dict[str, float]


class AskRequest(BaseModel):
    """Payload for POST /api/v1/ask."""

    question: str = Field(min_length=1, max_length=1000)
    client_id: UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class AskSourceMeta(BaseModel):
    """Metadata for a retrieved source chunk alias in the meta SSE event."""

    alias: str
    parent_type: str
    parent_id: UUID | str
    title: str = ""
    url: str = ""


class AskMetaEvent(BaseModel):
    """Payload for the initial 'meta' SSE event."""

    sources: list[AskSourceMeta]


class AskTokenEvent(BaseModel):
    """Payload for 'token' SSE deltas."""

    delta: str
    text: str


class AskCitationItem(BaseModel):
    """Grounding citation item linked to a retrieved source."""

    alias: str
    parent_type: str = "card"
    parent_id: UUID | str
    title: str = ""
    url: str = ""


class AskCitationsEvent(BaseModel):
    """Payload for the 'citations' SSE event."""

    cited: list[AskCitationItem] = Field(default_factory=list)
    valid: list[AskCitationItem] = Field(default_factory=list)
    invalid: list[str] = Field(default_factory=list)
    has_invalid_citations: bool = False


class AskDoneEvent(BaseModel):
    """Payload for the final 'done' SSE event."""

    truncated: bool = False


class AskErrorEvent(BaseModel):
    """Payload for the 'error' SSE event."""

    detail: str
    error: str = ""


