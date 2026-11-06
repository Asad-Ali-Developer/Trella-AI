"""Delta check service to detect if client workspace context changed since the last run."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.trello.models import TrelloCard, TrelloComment

logger = get_logger("app.modules.scheduler.delta")


async def has_context_changes_since(
    db: AsyncSession,
    workspace_id: UUID,
    since: datetime | None,
    client_id: UUID | None = None,
) -> bool:
    """Check if any cards, comments, or commits have changed or been created since the given timestamp.

    Returns True if:
    - `since` is None (first run ever, full context required)
    - Any card has last_activity_at > since or updated_at > since
    - Any comment has created_at > since
    - Any GitHub commit has committed_at > since or created_at > since
    """
    if since is None:
        return True

    # 1. Check for card changes
    card_query = select(TrelloCard.id).where(
        TrelloCard.workspace_id == workspace_id,
        or_(
            TrelloCard.last_activity_at > since,
            TrelloCard.updated_at > since,
            TrelloCard.created_at > since,
        ),
    )
    if client_id is not None:
        card_query = card_query.where(TrelloCard.client_id == client_id)

    card_query = card_query.limit(1)
    card_result = await db.execute(card_query)
    if card_result.scalar_one_or_none() is not None:
        logger.info("delta_change_detected_in_cards", workspace_id=str(workspace_id), since=since.isoformat())
        return True

    # 2. Check for comment changes linked to cards in this workspace (and client)
    comment_query = (
        select(TrelloComment.id)
        .join(TrelloCard, TrelloComment.card_id == TrelloCard.id)
        .where(
            TrelloCard.workspace_id == workspace_id,
            or_(
                TrelloComment.created_at > since,
                TrelloComment.updated_at > since,
            ),
        )
    )
    if client_id is not None:
        comment_query = comment_query.where(TrelloCard.client_id == client_id)

    comment_query = comment_query.limit(1)
    comment_result = await db.execute(comment_query)
    if comment_result.scalar_one_or_none() is not None:
        logger.info("delta_change_detected_in_comments", workspace_id=str(workspace_id), since=since.isoformat())
        return True

    # 3. Check for GitHub commit changes in this workspace (and client)
    commit_query = (
        select(GithubCommit.id)
        .join(GithubRepository, GithubCommit.repository_id == GithubRepository.id)
        .where(
            GithubCommit.workspace_id == workspace_id,
            or_(
                GithubCommit.committed_at > since,
                GithubCommit.created_at > since,
                GithubCommit.updated_at > since,
            ),
        )
    )
    if client_id is not None:
        commit_query = commit_query.where(GithubRepository.client_id == client_id)

    commit_query = commit_query.limit(1)
    commit_result = await db.execute(commit_query)
    if commit_result.scalar_one_or_none() is not None:
        logger.info("delta_change_detected_in_commits", workspace_id=str(workspace_id), since=since.isoformat())
        return True

    logger.info("delta_no_changes_detected", workspace_id=str(workspace_id), since=since.isoformat())
    return False
