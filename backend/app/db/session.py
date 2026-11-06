from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings


def get_connect_args(cfg: Settings = settings) -> dict[str, Any]:
    """Build asyncpg connect_args, disabling prepared statement cache for PgBouncer."""
    if cfg.DB_PGBOUNCER:
        return {"statement_cache_size": 0}
    return {}


def build_engine(cfg: Settings = settings) -> AsyncEngine:
    """Create the primary async SQLAlchemy engine using pool settings from Settings."""
    return create_async_engine(
        cfg.DATABASE_URL,
        echo=cfg.DEBUG,
        pool_pre_ping=True,
        pool_size=cfg.DB_POOL_SIZE,
        max_overflow=cfg.DB_MAX_OVERFLOW,
        pool_recycle=cfg.DB_POOL_RECYCLE,
        pool_timeout=cfg.DB_POOL_TIMEOUT,
        connect_args=get_connect_args(cfg),
    )


def build_worker_engine(cfg: Settings = settings) -> AsyncEngine:
    """Create the Celery worker async SQLAlchemy engine using NullPool."""
    return create_async_engine(
        cfg.DATABASE_URL,
        echo=cfg.DEBUG,
        poolclass=NullPool,
        connect_args=get_connect_args(cfg),
    )


engine = build_engine(settings)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

worker_engine = build_worker_engine(settings)

worker_session_maker = async_sessionmaker(
    bind=worker_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a scoped asynchronous database session for FastAPI dependencies."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
