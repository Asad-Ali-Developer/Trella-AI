"""Service layer for Skills management."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.skills.builtin import BUILTIN_SKILLS
from app.modules.skills.models import Skill
from app.modules.skills.schemas import SkillCreate, SkillUpdate

logger = get_logger("app.modules.skills.service")


class SkillService:
    """Service for managing workspace and built-in skills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_skills(self, workspace_id: UUID) -> list[Skill]:
        """List all active skills available to a workspace (built-in + workspace-specific)."""
        result = await self.db.scalars(
            select(Skill)
            .where(
                or_(Skill.workspace_id == workspace_id, Skill.workspace_id.is_(None)),
                Skill.is_active.is_(True),
            )
            .order_by(Skill.name.asc())
        )
        return list(result.all())

    async def get_skill(self, skill_id: UUID, workspace_id: UUID) -> Skill:
        """Retrieve a specific skill by ID, validating workspace scope or built-in status."""
        result = await self.db.scalars(
            select(Skill).where(
                Skill.id == skill_id,
                or_(Skill.workspace_id == workspace_id, Skill.workspace_id.is_(None)),
            )
        )
        skill = result.first()
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Skill not found or access denied.",
            )
        return skill

    async def get_skill_by_slug(self, slug: str, workspace_id: UUID | None = None) -> Skill | None:
        """Find a skill by its slug."""
        query = select(Skill).where(Skill.slug == slug)
        if workspace_id:
            query = query.where(
                or_(Skill.workspace_id == workspace_id, Skill.workspace_id.is_(None))
            )
        else:
            query = query.where(Skill.workspace_id.is_(None))

        result = await self.db.scalars(query)
        return result.first()

    async def create_skill(self, workspace_id: UUID, data: SkillCreate) -> Skill:
        """Create a new custom skill for a workspace."""
        existing = await self.db.scalar(
            select(Skill.id).where(
                Skill.slug == data.slug,
                Skill.workspace_id == workspace_id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A skill with slug '{data.slug}' already exists in this workspace.",
            )

        skill = Skill(
            workspace_id=workspace_id,
            name=data.name,
            slug=data.slug,
            description=data.description,
            prompt_template=data.prompt_template,
            scope_json=data.scope_json,
            output_schema_json=data.output_schema_json,
            model_config_json=data.model_config_json,
            is_active=True,
        )
        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill)
        logger.info("skill_created", skill_id=str(skill.id), slug=skill.slug, workspace_id=str(workspace_id))
        return skill

    async def update_skill(
        self,
        skill_id: UUID,
        workspace_id: UUID,
        data: SkillUpdate,
    ) -> Skill:
        """Update an existing workspace-owned skill."""
        skill = await self.get_skill(skill_id, workspace_id)
        if skill.workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Built-in global skills cannot be modified.",
            )

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(skill, key, value)

        await self.db.commit()
        await self.db.refresh(skill)
        logger.info("skill_updated", skill_id=str(skill.id), workspace_id=str(workspace_id))
        return skill

    async def seed_builtin_skills(self) -> int:
        """Seed or synchronize built-in default skills in the database."""
        seeded_count = 0
        for skill_data in BUILTIN_SKILLS:
            slug = skill_data["slug"]
            result = await self.db.scalars(
                select(Skill).where(
                    Skill.slug == slug,
                    Skill.workspace_id.is_(None),
                )
            )
            existing = result.first()
            if not existing:
                skill = Skill(
                    workspace_id=None,
                    name=skill_data["name"],
                    slug=slug,
                    version=skill_data.get("version", 1),
                    description=skill_data.get("description", ""),
                    prompt_template=skill_data["prompt_template"],
                    scope_json=skill_data.get("scope_json", {}),
                    output_schema_json=skill_data.get("output_schema_json", {}),
                    model_config_json=skill_data.get("model_config_json", {}),
                    is_active=skill_data.get("is_active", True),
                )
                self.db.add(skill)
                seeded_count += 1
            else:
                # Update template, schema, and config if version matches
                existing.name = skill_data["name"]
                existing.description = skill_data.get("description", existing.description)
                existing.prompt_template = skill_data["prompt_template"]
                existing.scope_json = skill_data.get("scope_json", existing.scope_json)
                existing.output_schema_json = skill_data.get("output_schema_json", existing.output_schema_json)
                existing.model_config_json = skill_data.get("model_config_json", existing.model_config_json)
                existing.is_active = skill_data.get("is_active", existing.is_active)

        await self.db.commit()
        logger.info("builtin_skills_seeded", new_count=seeded_count)
        return seeded_count
