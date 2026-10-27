from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.sentry import init_sentry
from app.db.session import async_session_maker
from app.modules.auth.router import router as auth_router
from app.modules.clients.router import router as clients_router
from app.modules.context.router import router as context_router
from app.modules.github.router import router as github_router
from app.modules.jira.router import router as jira_router
from app.modules.runs.router import router as runs_router
from app.modules.skills.router import router as skills_router
from app.modules.skills.service import SkillService
from app.modules.trello.router import router as trello_router
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

    # Seed built-in skills if not yet seeded
    try:
        async with async_session_maker() as db:
            skill_service = SkillService(db)
            await skill_service.seed_builtin_skills()
    except Exception as exc:
        logger.warning("builtin_skills_seed_skipped", error=str(exc))

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
    application.include_router(clients_router, prefix=settings.API_V1_PREFIX)
    application.include_router(context_router, prefix=settings.API_V1_PREFIX)
    application.include_router(github_router, prefix=settings.API_V1_PREFIX)
    application.include_router(jira_router, prefix=settings.API_V1_PREFIX)
    application.include_router(runs_router, prefix=settings.API_V1_PREFIX)
    application.include_router(skills_router, prefix=settings.API_V1_PREFIX)
    application.include_router(trello_router, prefix=settings.API_V1_PREFIX)
    application.include_router(workspaces_router, prefix=settings.API_V1_PREFIX)

    return application


app = create_application()
