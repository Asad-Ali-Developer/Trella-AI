import uuid
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.auth import AuthSecurityError, decode_token
from app.core.security.csrf import validate_csrf_request
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.workspaces.models import Membership, MembershipRole, Workspace
from app.modules.workspaces.repository import WorkspaceRepository

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate a Bearer or HttpOnly-cookie token and return the active User."""
    cookie_token = request.cookies.get("access_token")
    if not token and cookie_token:
        token = cookie_token
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            validate_csrf_request(request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
    except AuthSecurityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token type must be access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject in token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User corresponding to token does not exist.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )

    return user


async def get_current_workspace(
    x_workspace_id: uuid.UUID = Header(alias="X-Workspace-Id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[Workspace, Membership]:
    """Verify workspace membership via X-Workspace-Id header and return context."""
    workspace_repo = WorkspaceRepository(db)
    membership = await workspace_repo.get_membership(
        workspace_id=x_workspace_id,
        user_id=current_user.id,
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You are not a member of this workspace.",
        )

    workspace = await workspace_repo.get_by_id(x_workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )

    return workspace, membership


def require_workspace_role(
    *allowed_roles: MembershipRole,
) -> Callable[..., tuple[Workspace, Membership]]:
    """Dependency factory restricting route access to specified membership roles."""

    def role_checker(
        workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    ) -> tuple[Workspace, Membership]:
        _, membership = workspace_context
        if membership.role not in allowed_roles:
            role_names = [r.value for r in allowed_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires one of the following roles: {', '.join(role_names)}",
            )
        return workspace_context

    return role_checker
