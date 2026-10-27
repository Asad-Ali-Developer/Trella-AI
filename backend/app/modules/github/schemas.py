from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GithubAuthorizationResponse(BaseModel):
    authorization_url: str


class GithubConnectionStatus(BaseModel):
    connected: bool
    username: str | None = None
    account_id: UUID | None = None


class GithubCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=20, max_length=256)
    workspace_id: UUID


class GithubAccountLinkRequest(BaseModel):
    account_id: UUID


class GithubProviderAccountResponse(BaseModel):
    id: UUID
    username: str


class GithubClientOption(BaseModel):
    id: UUID
    name: str


class GithubRepositoryResponse(BaseModel):
    id: str
    full_name: str
    description: str | None
    url: str
    default_branch: str
    private: bool
    included: bool
    client_id: UUID | None
    sync_status: str
    last_synced_at: datetime | None
    sync_error: str | None


class GithubRepositorySelection(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    included: bool
    client_id: UUID | None = None


class GithubRepositorySelectionRequest(BaseModel):
    repositories: list[GithubRepositorySelection] = Field(max_length=10000)


class GithubRepositorySelectionResponse(BaseModel):
    saved: int


class GithubSyncResponse(BaseModel):
    scheduled: int
