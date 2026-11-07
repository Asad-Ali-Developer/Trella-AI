"""Backfill CLI to enqueue indexing for all active sources and repositories in a workspace.

Usage:
    python -m app.scripts.reindex --workspace <uuid> [--force]
"""

import argparse
import asyncio
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import worker_session_maker
from app.modules.connections.models import WorkspaceConnection
from app.modules.context.indexer import increment_workspace_data_version
from app.modules.context.models import ContextChunkRecord
from app.modules.github.models import GithubRepository
from app.modules.trello.models import TrelloSource
from app.workers.tasks import (
    dispatch_task,
    index_repository_task,
    index_source_task,
)


async def reindex_workspace(
    workspace_id: UUID,
    *,
    force: bool = False,
    db: AsyncSession | None = None,
) -> dict[str, int]:
    """Clear embeddings when `force=True` and enqueue index tasks for active workspace sources and repositories."""
    if db is not None:
        return await _reindex_with_session(db, workspace_id, force=force, commit=False)

    async with worker_session_maker() as session:
        return await _reindex_with_session(session, workspace_id, force=force, commit=True)


async def _reindex_with_session(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    force: bool,
    commit: bool,
) -> dict[str, int]:
    cleared_embeddings = 0
    if force:
        upd = await session.execute(
            update(ContextChunkRecord)
            .where(
                ContextChunkRecord.workspace_id == workspace_id,
                ContextChunkRecord.embedding.is_not(None),
            )
            .values(embedding=None, embedding_model=None)
        )
        cleared_embeddings = int(getattr(upd, "rowcount", 0) or 0)
        await session.flush()
        if cleared_embeddings > 0:
            await increment_workspace_data_version(workspace_id)

    source_ids = list(
        (
            await session.scalars(
                select(TrelloSource.id)
                .join(
                    WorkspaceConnection,
                    WorkspaceConnection.id == TrelloSource.connection_id,
                )
                .where(
                    TrelloSource.workspace_id == workspace_id,
                    TrelloSource.excluded.is_(False),
                    WorkspaceConnection.workspace_id == workspace_id,
                    WorkspaceConnection.status == "active",
                )
                .order_by(TrelloSource.id)
            )
        ).all()
    )

    repository_ids = list(
        (
            await session.scalars(
                select(GithubRepository.id)
                .join(
                    WorkspaceConnection,
                    WorkspaceConnection.id == GithubRepository.connection_id,
                )
                .where(
                    GithubRepository.workspace_id == workspace_id,
                    GithubRepository.included.is_(True),
                    WorkspaceConnection.workspace_id == workspace_id,
                    WorkspaceConnection.status == "active",
                )
                .order_by(GithubRepository.id)
            )
        ).all()
    )

    if commit:
        await session.commit()

    for source_id in source_ids:
        dispatch_task(index_source_task, str(source_id), force)
    for repo_id in repository_ids:
        dispatch_task(index_repository_task, str(repo_id), force)

    return {
        "sources": len(source_ids),
        "repositories": len(repository_ids),
        "cleared_embeddings": cleared_embeddings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enqueue indexing tasks for all active sources and repositories of a workspace."
    )
    parser.add_argument(
        "--workspace",
        required=True,
        type=UUID,
        help="Target workspace UUID.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear existing chunk embeddings and rebuild.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = asyncio.run(reindex_workspace(args.workspace, force=args.force))
    print(
        f"Enqueued {summary['sources']} source(s) and {summary['repositories']} repository(ies) "
        f"for workspace {args.workspace} (cleared_embeddings={summary['cleared_embeddings']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

