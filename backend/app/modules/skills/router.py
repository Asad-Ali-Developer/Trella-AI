"""FastAPI router for Skills management."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_workspace, require_workspace_role
from app.db.session import get_db
from app.modules.skills.schemas import SkillCreate, SkillResponse, SkillUpdate
from app.modules.skills.service import SkillService
from app.modules.workspaces.models import Membership, MembershipRole, Workspace

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
async def list_skills(
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[SkillResponse]:
    """List all available skills (built-in defaults and custom workspace skills)."""
    workspace, _ = workspace_context
    service = SkillService(db)
    skills = await service.list_skills(workspace.id)
    return [SkillResponse.model_validate(skill) for skill in skills]


@router.post(
    "",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_workspace_role(MembershipRole.OWNER, MembershipRole.ADMIN))],
)
async def create_skill(
    payload: SkillCreate,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """Create a new custom skill for the workspace."""
    workspace, _ = workspace_context
    service = SkillService(db)
    skill = await service.create_skill(workspace.id, payload)
    return SkillResponse.model_validate(skill)


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: UUID,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """Retrieve skill details by ID."""
    workspace, _ = workspace_context
    service = SkillService(db)
    skill = await service.get_skill(skill_id, workspace.id)
    return SkillResponse.model_validate(skill)


@router.patch(
    "/{skill_id}",
    response_model=SkillResponse,
    dependencies=[Depends(require_workspace_role(MembershipRole.OWNER, MembershipRole.ADMIN))],
)
async def update_skill(
    skill_id: UUID,
    payload: SkillUpdate,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """Update a custom workspace-owned skill."""
    workspace, _ = workspace_context
    service = SkillService(db)
    skill = await service.update_skill(skill_id, workspace.id, payload)
    return SkillResponse.model_validate(skill)
