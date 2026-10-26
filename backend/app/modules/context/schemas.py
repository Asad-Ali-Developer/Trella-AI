from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ContextAccount(BaseModel):
    id: UUID
    provider: str
    account_name: str


class ContextSource(BaseModel):
    id: UUID
    provider: str
    name: str
    url: str
    account_name: str
    sync_status: str
    last_synced_at: datetime | None
    sync_error: str | None = None


class ContextClient(BaseModel):
    id: UUID
    name: str


class ContextMember(BaseModel):
    id: UUID
    external_id: str
    name: str
    username: str
    role_tag: Literal["unknown", "client", "internal"]


class ContextItem(BaseModel):
    item_type: Literal["source", "card", "comment", "person", "commit"]
    source_id: UUID | None = None
    source_name: str | None = None
    client_id: UUID | None = None
    client_name: str | None = None
    card_id: UUID | None = None
    external_id: str | None = None
    title: str | None = None
    text: str
    summary: str | None = None
    url: str | None = None
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextChunk(BaseModel):
    index: int
    estimated_tokens: int
    items: list[ContextItem]


class WorkspaceContextResponse(BaseModel):
    workspace_id: UUID
    workspace_name: str
    generated_at: datetime
    token_budget: int
    estimated_tokens: int
    connected_accounts: list[ContextAccount]
    sources: list[ContextSource]
    clients: list[ContextClient]
    members: list[ContextMember]
    item_count: int
    chunks: list[ContextChunk]


class MemberClassificationRequest(BaseModel):
    role_tag: Literal["unknown", "client", "internal"]


class CardSummaryResponse(BaseModel):
    card_id: UUID
    trello_card_id: str
    title: str
    summary: str
    content_hash: str
    cached: bool


class ContextSummariesRequest(BaseModel):
    client_id: UUID | None = None
    max_cards: int = Field(default=50, ge=1, le=100)


class ContextSummariesResponse(BaseModel):
    processed: int
    generated: int
    cached: int
    summaries: list[CardSummaryResponse]


class ContextIndexRequest(BaseModel):
    client_id: UUID | None = None
    max_cards: int = Field(default=100, ge=1, le=200)


class ContextIndexResponse(BaseModel):
    indexed: int
    already_indexed: int
    remaining: int


class ContextSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    client_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=20)


class SimilarCardResponse(BaseModel):
    card_id: UUID
    trello_card_id: str
    title: str
    description: str
    url: str
    client_id: UUID | None
    client_name: str | None
    similarity: float


class ContextSearchResponse(BaseModel):
    query: str
    workspace_id: UUID
    results: list[SimilarCardResponse]
