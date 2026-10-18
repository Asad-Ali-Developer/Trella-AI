from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AuthResponse,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def signup(
    payload: UserSignupRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Create a new user account and return credentials with JWT tokens."""
    service = AuthService(db)
    user, tokens = await service.signup(payload)
    return AuthResponse(
        user=UserResponse.model_validate(user),
        tokens=tokens,
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user",
)
async def login(
    payload: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Verify user credentials and return new session JWT tokens."""
    service = AuthService(db)
    user, tokens = await service.login(payload)
    return AuthResponse(
        user=UserResponse.model_validate(user),
        tokens=tokens,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access token."""
    service = AuthService(db)
    return await service.refresh_tokens(payload)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Retrieve profile of the currently authenticated user."""
    return UserResponse.model_validate(current_user)
