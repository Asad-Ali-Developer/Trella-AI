"""Pydantic schemas for POST /api/v1/search."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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

