"""Synchronization and reconciliation logic for Jira projects, issues, comments, and changelogs."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.jira.adf import adf_to_text
from app.modules.jira.client import JiraAPIError, JiraClient
from app.modules.jira.models import JiraChangelogItem, JiraComment, JiraIssue, JiraProject
from app.modules.trello.rate_limiter import _get_loop_redis

logger = get_logger("app.modules.jira.sync")

_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

JIRA_SYNC_LOOKBACK_MINUTES = 10


def compute_jira_issue_content_hash(
    *,
    key: str,
    summary: str,
    description: str,
    status: str,
    issue_type: str,
    priority: str | None,
    assignee: str | None,
    reporter: str | None,
    labels: list[str],
    created_at_jira: datetime | None,
    updated_at_jira: datetime | None,
    url: str,
) -> str:
    """Compute deterministic SHA-256 content_hash over exact JiraIssue fields."""
    payload = {
        "key": key,
        "summary": summary,
        "description": description,
        "status": status,
        "issue_type": issue_type,
        "priority": priority,
        "assignee": assignee,
        "reporter": reporter,
        "labels": sorted(labels),
        "created_at_jira": created_at_jira.astimezone(UTC).isoformat()
        if created_at_jira is not None
        else None,
        "updated_at_jira": updated_at_jira.astimezone(UTC).isoformat()
        if updated_at_jira is not None
        else None,
        "url": url,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def compute_jira_comment_content_hash(
    *,
    jira_comment_id: str,
    author: str,
    body: str,
    created_at_jira: datetime,
    updated_at_jira: datetime | None,
) -> str:
    """Compute deterministic SHA-256 content_hash over exact JiraComment fields."""
    payload = {
        "jira_comment_id": jira_comment_id,
        "author": author,
        "body": body,
        "created_at_jira": created_at_jira.astimezone(UTC).isoformat(),
        "updated_at_jira": updated_at_jira.astimezone(UTC).isoformat()
        if updated_at_jira is not None
        else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def format_jql_datetime(dt: datetime, user_timezone: str | None) -> str:
    """Format a UTC datetime for JQL in the authenticated Jira user's timezone ('YYYY-MM-DD HH:mm')."""
    aware_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    tz: Any = UTC
    if isinstance(user_timezone, str) and user_timezone.strip():
        try:
            tz = ZoneInfo(user_timezone.strip())
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            tz = UTC
    localized = aware_dt.astimezone(tz)
    return localized.strftime("%Y-%m-%d %H:%M")


def parse_jira_datetime(value: Any) -> datetime | None:
    """Parse Jira ISO-8601 timestamp (including +0000 offset) into a UTC-aware datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    elif len(raw) >= 5 and (raw[-5] in ("+", "-")) and ":" not in raw[-5:]:
        raw = f"{raw[:-2]}:{raw[-2:]}"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


async def acquire_jira_project_lock(
    project_id: UUID,
    token: str,
    *,
    ttl_seconds: int | None = None,
    redis: Any = None,
) -> bool:
    """Acquire a per-project distributed Redis lock (SET NX EX). Falls back to True if Redis is down in local tests."""
    lock_key = f"lock:sync:jira_project:{project_id}"
    effective_ttl = ttl_seconds if ttl_seconds is not None else settings.INDEX_LOCK_TTL_SECONDS
    try:
        client = redis if redis is not None else _get_loop_redis()
        acquired = await client.set(lock_key, token, nx=True, ex=effective_ttl)
        return bool(acquired)
    except (RedisError, OSError) as exc:
        logger.warning(
            "jira_sync_lock_redis_unavailable",
            project_id=str(project_id),
            error_type=type(exc).__name__,
        )
        return True


async def release_jira_project_lock(
    project_id: UUID,
    token: str,
    *,
    redis: Any = None,
) -> bool:
    """Atomically release the per-project distributed Redis lock via Lua compare-and-delete."""
    lock_key = f"lock:sync:jira_project:{project_id}"
    try:
        client: Any = redis if redis is not None else _get_loop_redis()
        deleted = await client.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
        return bool(int(deleted or 0) > 0)
    except (RedisError, OSError) as exc:
        logger.warning(
            "jira_sync_lock_release_failed",
            project_id=str(project_id),
            error_type=type(exc).__name__,
        )
        return False


def _extract_user_display(user_obj: Any) -> str | None:
    if not isinstance(user_obj, dict):
        return None
    display = (
        user_obj.get("displayName")
        or user_obj.get("name")
        or user_obj.get("emailAddress")
        or user_obj.get("accountId")
    )
    return str(display)[:255] if isinstance(display, str) and display.strip() else None


def _build_issue_url(site_url: str | None, issue_key: str, self_url: Any) -> str:
    if isinstance(site_url, str) and site_url.strip():
        return f"{site_url.rstrip('/')}/browse/{issue_key}"[:1000]
    if isinstance(self_url, str) and self_url.strip():
        return self_url[:1000]
    return ""


async def sync_jira_project(
    db: AsyncSession,
    project: JiraProject,
    *,
    client: JiraClient | None = None,
    site_url: str | None = None,
    reconcile: bool = True,
    redis: Any = None,
) -> int:
    """Synchronize a single selected Jira project: issues, comments, changelog items, and reconciliation.

    - Uses a per-project Redis lock to prevent concurrent duplicate syncs.
    - Records sync_started_at before querying and sets project.last_synced_at = sync_started_at on completion.
    - Uses a 10-minute lookback buffer on project.last_synced_at and formats JQL datetime in the user's timezone (/myself).
    - Requests expand=changelog and comment field in search; makes per-issue comment/changelog calls only when truncated.
    - Deletes local comments for an issue only after that issue's comment fetch completely succeeds.
    - Reconciles deleted/moved issues only after a fully successful enumeration, and aborts + logs a warning
      (without content) if reconciliation would delete more than 50% of the project's local issues.
    """
    lock_token = uuid4().hex
    if not await acquire_jira_project_lock(project.id, lock_token, redis=redis):
        logger.info("jira_project_sync_skipped_locked", project_id=str(project.id))
        return 0

    try:
        sync_started_at = datetime.now(UTC)

        if client is None:
            connection = await db.get(WorkspaceConnection, project.connection_id)
            if connection is None or connection.status != "active":
                raise JiraAPIError("The Jira connection is no longer active.", status_code=409)
            account = await db.get(ProviderAccount, connection.provider_account_id)
            if account is None or account.status != "active":
                raise JiraAPIError("The Jira account is no longer available.", status_code=409)

            from app.modules.jira.service import JiraConnectionService

            service = JiraConnectionService(db, project.workspace_id, connection.user_id)
            opened_client, cloud_id, resolved_site_url = await service.open_client(account)
            effective_site_url = site_url or resolved_site_url
            async with opened_client as active_client:
                count = await _sync_project_with_client(
                    db=db,
                    project=project,
                    client=active_client,
                    cloud_id=cloud_id,
                    site_url=effective_site_url,
                    sync_started_at=sync_started_at,
                    reconcile=reconcile,
                )
        else:
            count = await _sync_project_with_client(
                db=db,
                project=project,
                client=client,
                cloud_id=project.cloud_id,
                site_url=site_url or client.site_url,
                sync_started_at=sync_started_at,
                reconcile=reconcile,
            )

        project.last_synced_at = sync_started_at
        project.sync_status = "completed"
        project.sync_error = None
        await db.flush()
        return count
    finally:
        await release_jira_project_lock(project.id, lock_token, redis=redis)


async def _sync_project_with_client(
    *,
    db: AsyncSession,
    project: JiraProject,
    client: JiraClient,
    cloud_id: str,
    site_url: str | None,
    sync_started_at: datetime,
    reconcile: bool,
) -> int:
    myself = await client.get_myself(cloud_id)
    user_tz = myself.get("timeZone") if isinstance(myself, dict) else None

    safe_key = project.key.replace('"', "")
    if project.last_synced_at is not None:
        cutoff = project.last_synced_at - timedelta(minutes=JIRA_SYNC_LOOKBACK_MINUTES)
        formatted_cutoff = format_jql_datetime(cutoff, user_tz if isinstance(user_tz, str) else None)
        jql = f'project = "{safe_key}" AND updated >= "{formatted_cutoff}" ORDER BY updated ASC'
    else:
        jql = f'project = "{safe_key}" ORDER BY updated ASC'

    raw_issues = await client.search_issues_jql(
        cloud_id,
        jql=jql,
        expand="changelog",
    )

    upserted_count = 0
    for raw_issue in raw_issues:
        issue_ext_id = str(raw_issue.get("id") or "").strip()
        issue_key = str(raw_issue.get("key") or "").strip()
        fields = raw_issue.get("fields")
        if not issue_ext_id or not issue_key or not isinstance(fields, dict):
            continue

        summary = str(fields.get("summary") or "")[:1000]
        description = adf_to_text(fields.get("description"))

        status_obj = fields.get("status")
        status_name = (
            str(status_obj.get("name") or "")[:128] if isinstance(status_obj, dict) else ""
        )

        issuetype_obj = fields.get("issuetype")
        issue_type_name = (
            str(issuetype_obj.get("name") or "")[:128]
            if isinstance(issuetype_obj, dict)
            else ""
        )

        priority_obj = fields.get("priority")
        priority_name = (
            str(priority_obj.get("name"))[:128]
            if isinstance(priority_obj, dict) and priority_obj.get("name")
            else None
        )

        assignee_name = _extract_user_display(fields.get("assignee"))
        reporter_name = _extract_user_display(fields.get("reporter"))

        raw_labels = fields.get("labels")
        labels = (
            sorted(str(lbl) for lbl in raw_labels if isinstance(lbl, str))
            if isinstance(raw_labels, list)
            else []
        )

        created_at_jira = parse_jira_datetime(fields.get("created"))
        updated_at_jira = parse_jira_datetime(fields.get("updated"))
        issue_url = _build_issue_url(site_url, issue_key, raw_issue.get("self"))

        content_hash = compute_jira_issue_content_hash(
            key=issue_key,
            summary=summary,
            description=description,
            status=status_name,
            issue_type=issue_type_name,
            priority=priority_name,
            assignee=assignee_name,
            reporter=reporter_name,
            labels=labels,
            created_at_jira=created_at_jira,
            updated_at_jira=updated_at_jira,
            url=issue_url,
        )

        issue_stmt = (
            insert(JiraIssue)
            .values(
                workspace_id=project.workspace_id,
                project_id=project.id,
                client_id=project.client_id,
                cloud_id=project.cloud_id,
                jira_issue_id=issue_ext_id,
                key=issue_key,
                summary=summary,
                description=description,
                status=status_name,
                issue_type=issue_type_name,
                priority=priority_name,
                assignee=assignee_name,
                reporter=reporter_name,
                labels=labels,
                created_at_jira=created_at_jira,
                updated_at_jira=updated_at_jira,
                url=issue_url,
                content_hash=content_hash,
            )
            .on_conflict_do_update(
                constraint="uq_jira_issues_workspace_cloud_external",
                set_={
                    "project_id": project.id,
                    "client_id": project.client_id,
                    "key": issue_key,
                    "summary": summary,
                    "description": description,
                    "status": status_name,
                    "issue_type": issue_type_name,
                    "priority": priority_name,
                    "assignee": assignee_name,
                    "reporter": reporter_name,
                    "labels": labels,
                    "created_at_jira": created_at_jira,
                    "updated_at_jira": updated_at_jira,
                    "url": issue_url,
                    "content_hash": content_hash,
                },
            )
            .returning(JiraIssue.id)
        )
        issue_pk = (await db.execute(issue_stmt)).scalar_one()
        upserted_count += 1

        await _sync_issue_comments(
            db=db,
            project=project,
            client=client,
            cloud_id=cloud_id,
            issue_pk=issue_pk,
            issue_key=issue_key,
            comment_field=fields.get("comment"),
        )
        await _sync_issue_changelog(
            db=db,
            project=project,
            client=client,
            cloud_id=cloud_id,
            issue_pk=issue_pk,
            issue_key=issue_key,
            changelog_field=raw_issue.get("changelog"),
        )

    if reconcile:
        await _reconcile_project_issues(
            db=db,
            project=project,
            client=client,
            cloud_id=cloud_id,
        )

    return upserted_count


async def _sync_issue_comments(
    *,
    db: AsyncSession,
    project: JiraProject,
    client: JiraClient,
    cloud_id: str,
    issue_pk: UUID,
    issue_key: str,
    comment_field: Any,
) -> None:
    """Sync comments for one issue; delete stale local comments ONLY on a fully successful fetch."""
    comments_list: list[dict[str, Any]] = []
    comment_fetch_complete = False

    if isinstance(comment_field, dict):
        inline_comments = comment_field.get("comments")
        total = comment_field.get("total")
        max_results = comment_field.get("maxResults")
        if isinstance(inline_comments, list):
            is_truncated = (
                (isinstance(total, int) and total > len(inline_comments))
                or (isinstance(max_results, int) and len(inline_comments) > max_results)
            )
            if not is_truncated:
                comments_list = [c for c in inline_comments if isinstance(c, dict)]
                comment_fetch_complete = len(comments_list) == len(inline_comments)
            else:
                try:
                    comments_list = await client.get_issue_comments(
                        cloud_id,
                        issue_id_or_key=issue_key,
                    )
                    comment_fetch_complete = True
                except JiraAPIError:
                    logger.warning(
                        "jira_issue_comments_fetch_incomplete",
                        project_id=str(project.id),
                        issue_id=str(issue_pk),
                    )
                    comments_list = [c for c in inline_comments if isinstance(c, dict)]
                    comment_fetch_complete = False
    else:
        try:
            comments_list = await client.get_issue_comments(
                cloud_id,
                issue_id_or_key=issue_key,
            )
            comment_fetch_complete = True
        except JiraAPIError:
            logger.warning(
                "jira_issue_comments_fetch_failed",
                project_id=str(project.id),
                issue_id=str(issue_pk),
            )
            comment_fetch_complete = False

    fetched_comment_ids: set[str] = set()
    comment_values: list[dict[str, Any]] = []
    for raw_comment in comments_list:
        comment_ext_id = str(raw_comment.get("id") or "").strip()
        if not comment_ext_id:
            comment_fetch_complete = False
            continue
        author = _extract_user_display(raw_comment.get("author")) or ""
        body_text = adf_to_text(raw_comment.get("body"))
        created_dt = parse_jira_datetime(raw_comment.get("created")) or datetime.now(UTC)
        updated_dt = parse_jira_datetime(raw_comment.get("updated"))
        c_hash = compute_jira_comment_content_hash(
            jira_comment_id=comment_ext_id,
            author=author,
            body=body_text,
            created_at_jira=created_dt,
            updated_at_jira=updated_dt,
        )
        fetched_comment_ids.add(comment_ext_id)
        comment_values.append(
            {
                "workspace_id": project.workspace_id,
                "issue_id": issue_pk,
                "cloud_id": project.cloud_id,
                "jira_comment_id": comment_ext_id,
                "author": author,
                "body": body_text,
                "created_at_jira": created_dt,
                "updated_at_jira": updated_dt,
                "content_hash": c_hash,
            }
        )

    if comment_values:
        stmt = insert(JiraComment).values(comment_values)
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_jira_comments_workspace_cloud_external",
                set_={
                    "issue_id": stmt.excluded.issue_id,
                    "author": stmt.excluded.author,
                    "body": stmt.excluded.body,
                    "created_at_jira": stmt.excluded.created_at_jira,
                    "updated_at_jira": stmt.excluded.updated_at_jira,
                    "content_hash": stmt.excluded.content_hash,
                },
            )
        )

    if comment_fetch_complete:
        stale_stmt = delete(JiraComment).where(
            JiraComment.workspace_id == project.workspace_id,
            JiraComment.issue_id == issue_pk,
        )
        if fetched_comment_ids:
            stale_stmt = stale_stmt.where(
                JiraComment.jira_comment_id.not_in(fetched_comment_ids)
            )
        await db.execute(stale_stmt)


async def _sync_issue_changelog(
    *,
    db: AsyncSession,
    project: JiraProject,
    client: JiraClient,
    cloud_id: str,
    issue_pk: UUID,
    issue_key: str,
    changelog_field: Any,
) -> None:
    """Sync changelog history items for an issue; fetch full changelog only when truncated."""
    histories: list[dict[str, Any]] = []
    if isinstance(changelog_field, dict):
        inline_histories = changelog_field.get("histories")
        total = changelog_field.get("total")
        max_results = changelog_field.get("maxResults")
        if isinstance(inline_histories, list):
            is_truncated = (
                (isinstance(total, int) and total > len(inline_histories))
                or (isinstance(max_results, int) and len(inline_histories) > max_results)
            )
            if not is_truncated:
                histories = [h for h in inline_histories if isinstance(h, dict)]
            else:
                try:
                    histories = await client.get_issue_changelog(
                        cloud_id,
                        issue_id_or_key=issue_key,
                    )
                except JiraAPIError:
                    logger.warning(
                        "jira_issue_changelog_fetch_incomplete",
                        project_id=str(project.id),
                        issue_id=str(issue_pk),
                    )
                    histories = [h for h in inline_histories if isinstance(h, dict)]

    changelog_values: list[dict[str, Any]] = []
    for history in histories:
        history_id = str(history.get("id") or "").strip()
        if not history_id:
            continue
        author = _extract_user_display(history.get("author")) or ""
        created_dt = parse_jira_datetime(history.get("created")) or datetime.now(UTC)
        items = history.get("items")
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field") or "").strip()[:255]
            if not field_name:
                continue
            from_val = item.get("fromString")
            if from_val is None:
                from_val = item.get("from")
            to_val = item.get("toString")
            if to_val is None:
                to_val = item.get("to")

            changelog_values.append(
                {
                    "workspace_id": project.workspace_id,
                    "issue_id": issue_pk,
                    "jira_history_id": history_id,
                    "item_index": idx,
                    "field": field_name,
                    "from_value": str(from_val) if from_val is not None else None,
                    "to_value": str(to_val) if to_val is not None else None,
                    "author": author,
                    "created_at_jira": created_dt,
                }
            )

    if changelog_values:
        stmt = insert(JiraChangelogItem).values(changelog_values)
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_jira_changelog_workspace_issue_history_item",
                set_={
                    "field": stmt.excluded.field,
                    "from_value": stmt.excluded.from_value,
                    "to_value": stmt.excluded.to_value,
                    "author": stmt.excluded.author,
                    "created_at_jira": stmt.excluded.created_at_jira,
                },
            )
        )


async def _reconcile_project_issues(
    *,
    db: AsyncSession,
    project: JiraProject,
    client: JiraClient,
    cloud_id: str,
) -> int:
    """Reconcile local project issues against Jira Cloud.

    Runs only after a fully successful enumeration of project issue IDs.
    Aborts and logs a warning (without content) if it would delete > 50% of local issues.
    """
    local_rows = list(
        (
            await db.execute(
                select(JiraIssue.id, JiraIssue.jira_issue_id).where(
                    JiraIssue.workspace_id == project.workspace_id,
                    JiraIssue.project_id == project.id,
                )
            )
        ).all()
    )
    if not local_rows:
        return 0

    try:
        remote_issue_ids = await client.list_project_issue_ids(
            cloud_id,
            project_key=project.key,
        )
    except JiraAPIError:
        logger.warning(
            "jira_reconcile_enumeration_failed",
            project_id=str(project.id),
            workspace_id=str(project.workspace_id),
        )
        return 0

    to_delete_pks = [
        row.id for row in local_rows if row.jira_issue_id not in remote_issue_ids
    ]
    if not to_delete_pks:
        return 0

    total_local = len(local_rows)
    delete_count = len(to_delete_pks)
    if delete_count > total_local / 2:
        logger.warning(
            "jira_reconcile_aborted_mass_deletion_guard",
            project_id=str(project.id),
            workspace_id=str(project.workspace_id),
            local_count=total_local,
            would_delete_count=delete_count,
        )
        return 0

    await db.execute(
        delete(JiraIssue).where(
            JiraIssue.workspace_id == project.workspace_id,
            JiraIssue.project_id == project.id,
            JiraIssue.id.in_(to_delete_pks),
        )
    )
    return delete_count


async def sync_workspace_jira_projects(
    db: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    client: JiraClient | None = None,
    site_url: str | None = None,
    reconcile: bool = True,
    redis: Any = None,
) -> dict[UUID, int]:
    """Synchronize all included Jira projects for a workspace connection with per-project non-fatal failures."""
    projects = await projects_for_sync(db, workspace_id, connection_id)
    results: dict[UUID, int] = {}

    for project in projects:
        project.sync_status = "running"
        project.sync_error = None
        await db.commit()
        try:
            count = await sync_jira_project(
                db,
                project,
                client=client,
                site_url=site_url,
                reconcile=reconcile,
                redis=redis,
            )
            await db.commit()
            results[project.id] = count
        except Exception as exc:
            error_msg = (
                str(exc) if isinstance(exc, JiraAPIError) else "Synchronization failed."
            )
            await db.rollback()
            proj_reloaded = await db.get(JiraProject, project.id)
            if proj_reloaded is not None:
                proj_reloaded.sync_status = "failed"
                proj_reloaded.sync_error = error_msg
                await db.commit()
            logger.warning(
                "jira_project_sync_failed_non_fatal",
                project_id=str(project.id),
                workspace_id=str(workspace_id),
                error_type=type(exc).__name__,
            )

    return results


async def projects_for_sync(
    db: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
) -> list[JiraProject]:
    """Return all included Jira projects for a workspace connection."""
    result = await db.scalars(
        select(JiraProject).where(
            JiraProject.workspace_id == workspace_id,
            JiraProject.connection_id == connection_id,
            JiraProject.included.is_(True),
        )
    )
    return list(result.all())


async def enqueue_jira_project_sync(project_id: UUID) -> None:
    """Enqueue background synchronization for a Jira project on the Celery sync queue."""
    from app.workers.tasks import dispatch_task, sync_jira_project_task

    dispatch_task(sync_jira_project_task, str(project_id))
