from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.encryption import encryption
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.github.client import GithubAPIError, GithubClient
from app.modules.github.models import GithubCommit, GithubRepository


async def sync_github_repository(db: AsyncSession, repository: GithubRepository) -> int:
    """Fetch and idempotently upsert up to 500 recent commits for a selected repository."""
    connection = await db.get(WorkspaceConnection, repository.connection_id)
    if connection is None or connection.status != "active":
        raise GithubAPIError("The GitHub connection is no longer active.", 409)
    account = await db.get(ProviderAccount, connection.provider_account_id)
    if account is None or account.status != "active":
        raise GithubAPIError("The GitHub account is no longer available.", 409)

    since = (
        repository.last_synced_at - timedelta(days=1)
        if repository.last_synced_at is not None
        else None
    )
    try:
        async with GithubClient(encryption.decrypt(account.encrypted_token)) as client:
            commits = await client.list_commits(repository.full_name, since=since)
    except GithubAPIError:
        raise

    commit_values: list[dict[str, Any]] = []
    for item in commits:
        commit_data = item.get("commit")
        if not isinstance(commit_data, dict):
            continue
        author_data = commit_data.get("author")
        committer_data = commit_data.get("committer")
        author_data = author_data if isinstance(author_data, dict) else {}
        committer_data = committer_data if isinstance(committer_data, dict) else {}
        date_value = committer_data.get("date") or author_data.get("date")
        committed_at = _parse_datetime(date_value)
        message = commit_data.get("message")
        sha = item.get("sha")
        if committed_at is None or not isinstance(message, str) or not isinstance(sha, str):
            raise GithubAPIError("GitHub returned invalid commit data.")
        github_author = item.get("author")
        github_author = github_author if isinstance(github_author, dict) else {}
        commit_values.append(
            {
                "workspace_id": repository.workspace_id,
                "repository_id": repository.id,
                "sha": sha,
                "message": message[:20000],
                "author_name": str(author_data.get("name", ""))[:255],
                "author_login": (
                    str(github_author["login"])[:255]
                    if isinstance(github_author.get("login"), str)
                    else None
                ),
                "committed_at": committed_at,
                "url": str(item.get("html_url", ""))[:1000],
                "additions": 0,
                "deletions": 0,
                "changed_files": 0,
            }
        )

    if commit_values:
        statement = insert(GithubCommit).values(commit_values)
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_github_commits_repository_sha",
                set_={
                    "message": statement.excluded.message,
                    "author_name": statement.excluded.author_name,
                    "author_login": statement.excluded.author_login,
                    "committed_at": statement.excluded.committed_at,
                    "url": statement.excluded.url,
                },
            )
        )
    return len(commit_values)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


async def repositories_for_sync(
    db: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
) -> list[GithubRepository]:
    result = await db.scalars(
        select(GithubRepository).where(
            GithubRepository.workspace_id == workspace_id,
            GithubRepository.connection_id == connection_id,
            GithubRepository.included.is_(True),
        )
    )
    return list(result.all())


async def enqueue_repository_sync(repository_id: UUID) -> None:
    from app.workers.tasks import sync_github_repository_task

    sync_github_repository_task.delay(str(repository_id))
