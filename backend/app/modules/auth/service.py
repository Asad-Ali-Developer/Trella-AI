import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

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
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserProfileUpdateRequest,
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

    async def google_auth(self, email: str, name: str | None = None) -> tuple[User, TokenResponse]:
        """Authenticate or register a user via Google OAuth."""
        clean_email = email.strip().lower()
        user = await self.user_repo.get_by_email(clean_email)
        if not user:
            random_pw = secrets.token_urlsafe(32)
            display_name = name.strip() if name and name.strip() else clean_email.split("@")[0].capitalize()
            user = await self.user_repo.create(
                email=clean_email,
                name=display_name,
                hashed_password=hash_password(random_pw),
            )
        elif not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        tokens = self._generate_tokens(user.id)
        return user, tokens

    async def request_password_reset(self, email: str) -> tuple[str, str] | None:
        """Create a hashed one-time reset token for an existing active account."""
        user = await self.user_repo.get_by_email(email)
        if user is None or not user.is_active:
            return None

        token = secrets.token_urlsafe(32)
        await self.user_repo.create_password_reset_token(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )
        return user.email, token

    async def reset_password(self, request: PasswordResetConfirmRequest) -> None:
        """Consume a valid reset token and replace the user's password."""
        token_hash = hashlib.sha256(request.token.encode("utf-8")).hexdigest()
        reset_token = await self.user_repo.consume_password_reset_token(
            token_hash=token_hash,
            now=datetime.now(UTC),
        )
        if reset_token is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset link is invalid or expired. Request a new one.",
            )

        user = await self.user_repo.get_by_id(reset_token.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset link is invalid or expired. Request a new one.",
            )
        await self.user_repo.update(user, hashed_password=hash_password(request.password))

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

    async def update_profile(self, user: User, request: UserProfileUpdateRequest) -> User:
        """Update current user profile fields."""
        clean_name = request.name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Name cannot be empty.",
            )
        updated_user = await self.user_repo.update(user, name=clean_name)
        return updated_user

    async def change_password(self, user: User, request: PasswordChangeRequest) -> None:
        """Change current user's password after validating existing credentials."""
        if not verify_password(request.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )
        if request.current_password == request.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password.",
            )
        await self.user_repo.update(user, hashed_password=hash_password(request.new_password))
