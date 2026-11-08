"""Dedicated benchmark database safety checks, creation, and Alembic migration helper."""

import argparse
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, settings

_SAFE_DB_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BACKEND_DIR = Path(__file__).resolve().parents[1]


def normalize_db_identity(url: str) -> tuple[str, int, str]:
    """Return normalized (host, port, dbname) tuple for a PostgreSQL URL."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "localhost").lower()
    if host in ("127.0.0.1", "::1"):
        host = "localhost"
    port = parsed.port or 5432
    dbname = parsed.path.lstrip("/")
    return (host, port, dbname)


def assert_bench_database_isolated(
    bench_url: str | None = None,
    dev_url: str | None = None,
    test_url: str | None = None,
) -> str:
    """Refuse to run if BENCH_DATABASE_URL is empty or matches DATABASE_URL or TEST_DATABASE_URL."""
    raw_bench = (bench_url if bench_url is not None else settings.BENCH_DATABASE_URL).strip()
    if not raw_bench:
        raise RuntimeError("Refusing to run benchmark script: BENCH_DATABASE_URL must not be empty.")

    resolved_bench = Settings.assemble_db_connection(raw_bench)
    resolved_dev = Settings.assemble_db_connection(
        (dev_url if dev_url is not None else settings.DATABASE_URL).strip()
    )
    resolved_test = Settings.assemble_db_connection(
        (test_url if test_url is not None else settings.TEST_DATABASE_URL).strip()
    )

    bench_id = normalize_db_identity(resolved_bench)
    if not bench_id[2] or not _SAFE_DB_IDENTIFIER.match(bench_id[2]):
        raise RuntimeError(
            f"Refusing to run benchmark script: invalid database name {bench_id[2]!r}."
        )

    if resolved_bench == resolved_dev or bench_id == normalize_db_identity(resolved_dev):
        raise RuntimeError(
            "Refusing to run benchmark script: BENCH_DATABASE_URL must not equal DATABASE_URL "
            f"({resolved_bench!r})."
        )

    if resolved_bench == resolved_test or bench_id == normalize_db_identity(resolved_test):
        raise RuntimeError(
            "Refusing to run benchmark script: BENCH_DATABASE_URL must not equal TEST_DATABASE_URL "
            f"({resolved_bench!r})."
        )

    return resolved_bench


async def ensure_bench_database_exists(bench_url: str | None = None) -> str:
    """Create the benchmark database and install the pgvector extension if not already present."""
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    parsed = urlparse(isolated_url)
    target_db = parsed.path.lstrip("/")

    admin_url = urlunparse(parsed._replace(path="/postgres"))
    admin_engine = create_async_engine(
        admin_url,
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": target_db},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
    finally:
        await admin_engine.dispose()

    bench_engine = create_async_engine(isolated_url, poolclass=pool.NullPool)
    try:
        async with bench_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        await bench_engine.dispose()

    return isolated_url


def upgrade_bench_database_head(bench_url: str | None = None) -> str:
    """Run `alembic upgrade head` against the isolated benchmark database."""
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    env = os.environ.copy()
    env["DATABASE_URL"] = isolated_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=env,
        check=True,
    )
    return isolated_url


async def prepare_bench_database(bench_url: str | None = None) -> str:
    """Ensure the benchmark database exists, has pgvector installed, and is migrated to head."""
    isolated_url = await ensure_bench_database_exists(bench_url=bench_url)
    await asyncio.to_thread(upgrade_bench_database_head, isolated_url)
    return isolated_url


def create_bench_engine(bench_url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine connected to the isolated benchmark database."""
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    return create_async_engine(isolated_url, poolclass=pool.NullPool)


def create_bench_session_maker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session maker bound to the benchmark engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def _async_main(db_url: str | None) -> None:
    resolved = await prepare_bench_database(bench_url=db_url)
    host, port, dbname = normalize_db_identity(resolved)
    print(f"Benchmark database ready: {host}:{port}/{dbname} (vector extension + alembic head)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create client_insights_bench, install vector extension, and run alembic upgrade head."
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Optional override for BENCH_DATABASE_URL.",
    )
    args = parser.parse_args()
    asyncio.run(_async_main(args.db_url))


if __name__ == "__main__":
    main()
