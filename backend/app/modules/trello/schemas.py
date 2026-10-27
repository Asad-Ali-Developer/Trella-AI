from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TrelloAuthorizationResponse(BaseModel):
    authorization_url: str


class TrelloCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=32, max_length=128)
    workspace_id: UUID


class TrelloConnectionStatus(BaseModel):
    connected: bool
    username: str | None = None
    account_id: UUID | None = None


class TrelloProviderAccountResponse(BaseModel):
    id: UUID
    username: str


class TrelloProviderAccountLinkRequest(BaseModel):
    account_id: UUID


class TrelloBoardResponse(BaseModel):
    id: str
    name: str
    url: str
    excluded: bool
    sync_status: str = "not_started"
    last_synced_at: datetime | None = None
    sync_error: str | None = None


class TrelloBoardSelection(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    excluded: bool


class TrelloBoardSelectionRequest(BaseModel):
    boards: list[TrelloBoardSelection]


class TrelloBoardSelectionResponse(BaseModel):
    saved: int


class TrelloTokenCallbackRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    state: str = Field(min_length=32, max_length=128)
    workspace_id: UUID


class TrelloClientMappingInput(BaseModel):
    board_id: str = Field(min_length=1, max_length=255)
    mapping_type: Literal["board", "label", "list"]
    external_ref: str = Field(default="", max_length=255)
    client_name: str = Field(min_length=1, max_length=255)


class TrelloClientMappingRequest(BaseModel):
    mappings: list[TrelloClientMappingInput]


class TrelloClientMappingResponse(BaseModel):
    board_id: str
    board_name: str
    mapping_type: Literal["board", "label", "list"]
    external_ref: str
    client_name: str


class TrelloClientMappingSaveResponse(BaseModel):
    saved: int


class TrelloSyncResponse(BaseModel):
    scheduled: int


class TrelloWebhookResponse(BaseModel):
    accepted: bool = True
