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


class TrelloBoardResponse(BaseModel):
    id: str
    name: str
    url: str
    excluded: bool


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