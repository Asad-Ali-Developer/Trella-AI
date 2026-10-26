import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security.csrf import CSRF_COOKIE_NAME, validate_csrf_request
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AuthResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)
from app.core.email import is_email_configured
from app.modules.auth.service import AuthService
from app.workers.tasks import (
    dispatch_task,
    send_password_reset_email,
    send_welcome_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])
ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"


def _set_auth_cookies(response: Response, tokens: TokenResponse) -> None:
    secure = settings.auth_cookie_secure
    same_site = settings.AUTH_COOKIE_SAMESITE
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        tokens.access_token,
        max_age=tokens.expires_in,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        secrets.token_urlsafe(32),
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=False,
        secure=secure,
        samesite=same_site,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    for cookie_name in (ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(
            cookie_name,
            path="/",
            secure=settings.auth_cookie_secure,
            httponly=cookie_name != CSRF_COOKIE_NAME,
            samesite=settings.AUTH_COOKIE_SAMESITE,
        )


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def signup(
    payload: UserSignupRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Create an account and establish a cookie-based session."""
    service = AuthService(db)
    user, tokens = await service.signup(payload)
    if is_email_configured():
        background_tasks.add_task(dispatch_task, send_welcome_email, user.email, user.name)
    _set_auth_cookies(response, tokens)
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Request a reset link without revealing whether the account exists."""
    if is_email_configured():
        reset = await AuthService(db).request_password_reset(str(payload.email))
        if reset:
            email, token = reset
            reset_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reset-password?token={token}"
            background_tasks.add_task(dispatch_task, send_password_reset_email, email, reset_url)
    return {"message": "If that email belongs to an account, a reset link will be sent."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    await AuthService(db).reset_password(payload)


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user",
)
async def login(
    payload: UserLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Verify credentials and establish a cookie-based session."""
    service = AuthService(db)
    user, tokens = await service.login(payload)
    _set_auth_cookies(response, tokens)
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Refresh access token",
)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Rotate session tokens using the HttpOnly refresh cookie."""
    validate_csrf_request(request)
    refresh_token_value = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie is missing.",
        )
    service = AuthService(db)
    tokens = await service.refresh_tokens(RefreshTokenRequest(refresh_token=refresh_token_value))
    _set_auth_cookies(response, tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
)
async def logout(request: Request, response: Response) -> None:
    """Clear session cookies after validating the CSRF token."""
    validate_csrf_request(request)
    _clear_auth_cookies(response)


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
