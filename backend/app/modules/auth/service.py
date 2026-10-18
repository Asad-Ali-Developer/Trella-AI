import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.auth import (
    AuthSecurityError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserSignupRequest,
)


class AuthService:
    """Business logic for user registration, authentication, and session tokens."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)

    async def signup(self, request: UserSignupRequest) -> tuple[User, TokenResponse]:
        """Register a new user and generate initial tokens."""
        existing = await self.user_repo.get_by_email(request.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email address already exists.",
            )

        hashed = hash_password(request.password)
        user = await self.user_repo.create(
            email=request.email,
            name=request.name,
            hashed_password=hashed,
        )

        tokens = self._generate_tokens(user.id)
        return user, tokens

    async def login(self, request: UserLoginRequest) -> tuple[User, TokenResponse]:
        """Authenticate user credentials and generate tokens."""
        user = await self.user_repo.get_by_email(request.email)
        if not user or not verify_password(request.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        tokens = self._generate_tokens(user.id)
        return user, tokens

    async def refresh_tokens(self, request: RefreshTokenRequest) -> TokenResponse:
        """Issue fresh access token from a valid refresh token."""
        try:
            payload = decode_token(request.refresh_token)
        except AuthSecurityError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token provided is not a refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        sub = payload.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token claims.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            user_id = uuid.UUID(sub)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user reference in token.",
            ) from exc

        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive.",
            )

        return self._generate_tokens(user.id)

    def _generate_tokens(self, user_id: uuid.UUID) -> TokenResponse:
        """Create token response pair."""
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=expires_in,
        )
