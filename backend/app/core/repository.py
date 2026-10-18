import uuid
from collections.abc import Sequence
from typing import Any, TypeVar, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class WorkspaceScopedRepository[ModelType: Base]:
    """Generic base repository enforcing strict workspace_id data isolation."""

    def __init__(
        self,
        model: type[ModelType],
        session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        self.model = model
        self.session = session
        self.workspace_id = workspace_id

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelType | None:
        """Fetch a single entity by ID, strictly scoped to the current workspace."""
        statement = select(self.model).where(
            self.model.id == entity_id,  # type: ignore[attr-defined]
            self.model.workspace_id == self.workspace_id,  # type: ignore[attr-defined]
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Sequence[Any] | None = None,
    ) -> Sequence[ModelType]:
        """List entities scoped to the current workspace with optional pagination and filters."""
        statement = select(self.model).where(
            self.model.workspace_id == self.workspace_id  # type: ignore[attr-defined]
        )
        if filters:
            for f in filters:
                statement = statement.where(f)

        statement = statement.offset(skip).limit(limit)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def count(self, filters: Sequence[Any] | None = None) -> int:
        """Count total entities matching filters within the current workspace."""
        statement = select(func.count(self.model.id)).where(  # type: ignore[attr-defined]
            self.model.workspace_id == self.workspace_id,  # type: ignore[attr-defined]
        )
        if filters:
            for f in filters:
                statement = statement.where(f)

        result = await self.session.execute(statement)
        return result.scalar() or 0

    async def create(self, **kwargs: Any) -> ModelType:
        """Create a new entity, automatically injecting the current workspace_id."""
        kwargs["workspace_id"] = self.workspace_id
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, entity_id: uuid.UUID, **kwargs: Any) -> ModelType | None:
        """Update fields on an entity strictly within the current workspace."""
        kwargs.pop("workspace_id", None)
        statement = (
            update(self.model)
            .where(
                self.model.id == entity_id,  # type: ignore[attr-defined]
                self.model.workspace_id == self.workspace_id,  # type: ignore[attr-defined]
            )
            .values(**kwargs)
            .returning(self.model)
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def delete(self, entity_id: uuid.UUID) -> bool:
        """Delete an entity strictly scoped to the current workspace."""
        statement = delete(self.model).where(
            self.model.id == entity_id,  # type: ignore[attr-defined]
            self.model.workspace_id == self.workspace_id,  # type: ignore[attr-defined]
        )
        result = await self.session.execute(statement)
        cursor_result = cast(CursorResult[Any], result)
        return bool(cursor_result.rowcount and cursor_result.rowcount > 0)
