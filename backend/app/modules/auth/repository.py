import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import PasswordResetToken, User


class UserRepository:
    """Data access repository for users."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Fetch user by primary key UUID."""
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Fetch user by unique email address (case-insensitive)."""
        stmt = select(User).where(User.email == email.lower().strip())
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, email: str, name: str, hashed_password: str) -> User:
        """Persist a new user."""
        user = User(
            email=email.lower().strip(),
            name=name.strip(),
            hashed_password=hashed_password,
            is_active=True,
            is_verified=False,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def update(self, user: User, **kwargs: Any) -> User:
        """Update user attributes."""
        for key, value in kwargs.items():
            setattr(user, key, value)
        await self.db.flush()
        return user

    async def create_password_reset_token(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        await self.db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )
        self.db.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        await self.db.flush()

    async def consume_password_reset_token(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> PasswordResetToken | None:
        result = await self.db.execute(
            select(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.expires_at > now,
            )
            .with_for_update()
        )
        token = result.scalar_one_or_none()
        if token is None:
            return None
        await self.db.delete(token)
        await self.db.flush()
        return token
