from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueueItem(BaseModel):
    id: str
    name: str
    source_type: Literal["trello", "github", "run"]
    status: Literal["not_started", "queued", "running", "completed", "failed"]
    last_synced_at: datetime | None = None
    sync_error: str | None = None
    items_count: int = 0
    chunks_count: int = 0


class RecentRunItem(BaseModel):
    id: str
    skill_name: str
    status: str
    trigger: str
    created_at: datetime
    completed_at: datetime | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error: str | None = None


class QueueStatusResponse(BaseModel):
    is_worker_online: bool
    redis_connected: bool
    celery_queue_length: int
    syncing_count: int
    worker_name: str | None = None
    items: list[QueueItem] = Field(default_factory=list)
    recent_runs: list[RecentRunItem] = Field(default_factory=list)
    total_chunks: int = 0
    last_checked_at: datetime

