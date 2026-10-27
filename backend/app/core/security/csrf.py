import hmac

from fastapi import HTTPException, Request, status

from app.core.config import settings

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def validate_csrf_request(request: Request) -> None:
    """Validate origin and double-submit token for cookie-authenticated writes."""
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    origin = request.headers.get("Origin")

    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
        or origin not in settings.CORS_ORIGINS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )
