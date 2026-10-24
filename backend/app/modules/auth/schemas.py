import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserSignupRequest(BaseModel):
    """Payload for user registration."""

    email: EmailStr
    password: str = Field(min_length=8, description="Password must be at least 8 characters")
    name: str = Field(min_length=1, max_length=100, description="User full or display name")


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""

    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    """Payload for token refresh."""

    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=8, description="Password must be at least 8 characters")


class TokenResponse(BaseModel):
    """Standard Bearer token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """User profile response without sensitive fields."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    is_active: bool
    is_verified: bool
    created_at: datetime


class AuthResponse(BaseModel):
    """Authenticated user profile; tokens are sent only as HttpOnly cookies."""

    user: UserResponse
