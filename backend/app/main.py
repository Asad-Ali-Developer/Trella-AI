from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.sentry import init_sentry
from app.modules.auth.router import router as auth_router
from app.modules.workspaces.router import router as workspaces_router

logger = get_logger("app")


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str
    app: str
    environment: str
    version: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:
    """Lifespan event handler for startup and shutdown procedures."""
    init_sentry()
    setup_logging()
    logger.info("application_started", app_name=settings.APP_NAME, env=settings.APP_ENV)
    yield
    logger.info("application_shutdown")


def create_application() -> FastAPI:
    """Application factory for FastAPI instance."""
    application = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # CORS configuration
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoints
    @application.get("/health", response_model=HealthResponse, tags=["Health"])
    @application.get(
        f"{settings.API_V1_PREFIX}/health", response_model=HealthResponse, tags=["Health"]
    )
    async def health_check() -> HealthResponse:
        """Health check endpoint to verify service availability."""
        return HealthResponse(
            status="ok",
            app=settings.APP_NAME,
            environment=settings.APP_ENV,
            version="0.1.0",
        )

    # Mount API routers
    application.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    application.include_router(workspaces_router, prefix=settings.API_V1_PREFIX)

    return application


app = create_application()
