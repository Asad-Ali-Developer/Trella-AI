from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_workspace, require_workspace_role
from app.db.session import get_db
from app.modules.context.schemas import (
    ContextIndexRequest,
    ContextIndexResponse,
    ContextMember,
    ContextSearchRequest,
    ContextSearchResponse,
    ContextSummariesRequest,
    ContextSummariesResponse,
    MemberClassificationRequest,
    WorkspaceContextResponse,
)
from app.modules.context.service import WorkspaceContextService
from app.modules.workspaces.models import Membership, MembershipRole, Workspace

router = APIRouter(prefix="/context", tags=["context"])


@router.get("", response_model=WorkspaceContextResponse)
async def build_workspace_context(
    client_id: UUID | None = None,
    max_tokens: int = Query(default=4000, ge=256, le=12000),
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceContextResponse:
    """Build an ordered context snapshot from the connected sources in this workspace."""
    workspace, _ = workspace_context
    return await WorkspaceContextService(db, workspace).build(
        client_id=client_id,
        max_tokens=max_tokens,
    )


@router.patch(
    "/members/{member_id}",
    response_model=ContextMember,
    dependencies=[Depends(require_workspace_role(MembershipRole.OWNER, MembershipRole.ADMIN))],
)
async def classify_workspace_member(
    member_id: UUID,
    payload: MemberClassificationRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContextMember:
    workspace, _ = workspace_context
    return await WorkspaceContextService(db, workspace).classify_member(
        member_id,
        payload.role_tag,
    )


@router.post("/summaries", response_model=ContextSummariesResponse)
async def summarize_workspace_cards(
    payload: ContextSummariesRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContextSummariesResponse:
    workspace, _ = workspace_context
    return await WorkspaceContextService(db, workspace).summarize_cards(
        client_id=payload.client_id,
        max_cards=payload.max_cards,
    )


@router.post("/index", response_model=ContextIndexResponse)
async def index_workspace_cards(
    payload: ContextIndexRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContextIndexResponse:
    workspace, _ = workspace_context
    return await WorkspaceContextService(db, workspace).index_cards(
        client_id=payload.client_id,
        max_cards=payload.max_cards,
    )


@router.post("/search", response_model=ContextSearchResponse)
async def search_workspace_context(
    payload: ContextSearchRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContextSearchResponse:
    workspace, _ = workspace_context
    return await WorkspaceContextService(db, workspace).search_similar(
        query=payload.query,
        client_id=payload.client_id,
        limit=payload.limit,
    )
