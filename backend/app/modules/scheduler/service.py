"""Service layer for Report Schedules and Delivery Orchestration."""

import zoneinfo
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from croniter import croniter
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import build_email, is_email_configured, send_email
from app.core.logging import get_logger
from app.core.security.encryption import decrypt_secret
from app.modules.auth.models import User
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.delivery.models import Delivery
from app.modules.delivery.slack import SlackClient, build_slack_block_kit_digest
from app.modules.runs.models import Run
from app.modules.runs.schemas import RunCreateRequest
from app.modules.runs.service import RunService
from app.modules.scheduler.delta import has_context_changes_since
from app.modules.scheduler.models import Schedule
from app.modules.scheduler.schemas import ScheduleCreateRequest, ScheduleUpdateRequest
from app.modules.skills.models import Skill
from app.modules.trello.models import TrelloClientRecord as Client
from app.modules.workspaces.models import Membership, Workspace

logger = get_logger("app.modules.scheduler.service")


def calculate_next_run(
    cron_expr: str,
    tz_name: str,
    base_time: datetime | None = None,
) -> datetime:
    """Calculate the next execution timestamp (UTC) from a cron expression and timezone."""
    # 1. Validate timezone
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")

    # 2. Validate cron expression
    if not croniter.is_valid(cron_expr):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cron expression: '{cron_expr}'. Expected standard 5-part cron format (e.g. '0 9 * * 1').",
        )

    # 3. Base time localized to the target timezone
    current_utc = base_time or datetime.now(UTC)
    current_local = current_utc.astimezone(tz)

    iter_obj = croniter(cron_expr, current_local)
    next_local = iter_obj.get_next(datetime)
    assert isinstance(next_local, datetime)

    # 4. Return as UTC datetime
    return next_local.astimezone(UTC)


class ScheduleService:
    """Handles CRUD for schedules and execution of automated reports."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_schedule(
        self,
        workspace_id: UUID,
        payload: ScheduleCreateRequest,
    ) -> Schedule:
        """Create a new recurring report schedule for a workspace."""
        # 1. Verify skill exists and belongs to this workspace or is built-in
        skill = await self.db.get(Skill, payload.skill_id)
        if skill is None or (skill.workspace_id is not None and skill.workspace_id != workspace_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Skill not found in this workspace.",
            )

        # 2. Verify client exists if specified
        if payload.client_id is not None:
            client = await self.db.get(Client, payload.client_id)
            if client is None or client.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Client not found in this workspace.",
                )

        # 3. Calculate initial next_run_at
        next_run = calculate_next_run(payload.cron, payload.timezone) if payload.active else None

        schedule = Schedule(
            workspace_id=workspace_id,
            skill_id=payload.skill_id,
            client_id=payload.client_id,
            name=payload.name,
            cron=payload.cron,
            timezone=payload.timezone,
            channel=payload.channel,
            recipients=payload.recipients,
            slack_channel_id=payload.slack_channel_id,
            slack_channel_name=payload.slack_channel_name,
            is_delta_only=payload.is_delta_only,
            next_run_at=next_run,
            active=payload.active,
        )
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        logger.info(
            "schedule_created",
            schedule_id=str(schedule.id),
            workspace_id=str(workspace_id),
            next_run_at=schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        )
        return schedule

    async def list_schedules(self, workspace_id: UUID) -> list[Schedule]:
        """List all report schedules for the specified workspace."""
        query = (
            select(Schedule)
            .where(Schedule.workspace_id == workspace_id)
            .order_by(Schedule.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_schedule(self, schedule_id: UUID, workspace_id: UUID) -> Schedule:
        """Get a specific schedule by ID with workspace verification."""
        schedule = await self.db.get(Schedule, schedule_id)
        if schedule is None or schedule.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule not found.",
            )
        return schedule

    async def update_schedule(
        self,
        schedule_id: UUID,
        workspace_id: UUID,
        payload: ScheduleUpdateRequest,
    ) -> Schedule:
        """Update an existing schedule and adjust next_run_at if timing changed."""
        schedule = await self.get_schedule(schedule_id, workspace_id)

        cron_changed = payload.cron is not None and payload.cron != schedule.cron
        tz_changed = payload.timezone is not None and payload.timezone != schedule.timezone
        active_changed = payload.active is not None and payload.active != schedule.active

        if payload.name is not None:
            schedule.name = payload.name
        if payload.cron is not None:
            schedule.cron = payload.cron
        if payload.timezone is not None:
            schedule.timezone = payload.timezone
        if payload.channel is not None:
            schedule.channel = payload.channel
        if payload.recipients is not None:
            schedule.recipients = payload.recipients
        if payload.slack_channel_id is not None:
            schedule.slack_channel_id = payload.slack_channel_id
        if payload.slack_channel_name is not None:
            schedule.slack_channel_name = payload.slack_channel_name
        if payload.is_delta_only is not None:
            schedule.is_delta_only = payload.is_delta_only
        if payload.active is not None:
            schedule.active = payload.active

        # Recalculate next_run_at if timing or active state changed
        if (cron_changed or tz_changed or active_changed) and schedule.active:
            schedule.next_run_at = calculate_next_run(schedule.cron, schedule.timezone)
        elif not schedule.active:
            schedule.next_run_at = None

        await self.db.commit()
        await self.db.refresh(schedule)
        logger.info("schedule_updated", schedule_id=str(schedule.id))
        return schedule

    async def delete_schedule(self, schedule_id: UUID, workspace_id: UUID) -> None:
        """Delete a schedule."""
        schedule = await self.get_schedule(schedule_id, workspace_id)
        await self.db.delete(schedule)
        await self.db.commit()
        logger.info("schedule_deleted", schedule_id=str(schedule_id))

    async def find_due_schedules(self) -> list[Schedule]:
        """Find all active schedules that are due for execution and advance next_run_at."""
        now = datetime.now(UTC)
        query = (
            select(Schedule)
            .where(
                Schedule.active.is_(True),
                Schedule.next_run_at.is_not(None),
                Schedule.next_run_at <= now,
            )
        )
        result = await self.db.execute(query)
        due_schedules = list(result.scalars().all())

        for sched in due_schedules:
            # Advance next_run_at immediately to prevent duplicate runs
            sched.last_run_at = now
            sched.next_run_at = calculate_next_run(sched.cron, sched.timezone, base_time=now)

        if due_schedules:
            await self.db.commit()
            for sched in due_schedules:
                await self.db.refresh(sched)

        return due_schedules

    async def execute_scheduled_run(self, schedule_id: UUID) -> Run | None:
        """Execute a scheduled run, applying delta checks and queueing deliveries."""
        schedule = await self.db.get(Schedule, schedule_id)
        if schedule is None or not schedule.active:
            return None

        workspace = await self.db.get(Workspace, schedule.workspace_id)
        if workspace is None:
            return None

        # 1. Delta check: skip LLM call entirely if delta-only and no changes detected
        if schedule.is_delta_only:
            has_changes = await has_context_changes_since(
                self.db,
                schedule.workspace_id,
                schedule.last_run_at,
                client_id=schedule.client_id,
            )
            if not has_changes:
                logger.info(
                    "scheduled_run_skipped_delta_unchanged",
                    schedule_id=str(schedule_id),
                    workspace_id=str(schedule.workspace_id),
                )
                # Create a skipped delivery log
                delivery = Delivery(
                    workspace_id=schedule.workspace_id,
                    run_id=schedule.id,  # Link to schedule as placeholder
                    schedule_id=schedule.id,
                    channel=schedule.channel,
                    recipient=(
                        schedule.slack_channel_name
                        or (schedule.recipients[0] if schedule.recipients else "none")
                    ),
                    status="skipped",
                    error="Skipped: No new cards or comment changes detected since last run.",
                    delivered_at=datetime.now(UTC),
                )
                self.db.add(delivery)
                await self.db.commit()
                return None

        # 2. Trigger skill run
        run_service = RunService(self.db)
        run_create = RunCreateRequest(
            skill_id=schedule.skill_id,
            client_id=schedule.client_id,
            trigger="scheduled",
        )
        run = await run_service.create_run(schedule.workspace_id, None, run_create)
        executed_run = await run_service.execute_run(run.id)

        # 3. Handle run completion or failure
        if executed_run.status == "completed":
            await self._enqueue_deliveries_for_run(schedule, executed_run)
        else:
            await self._handle_execution_failure(
                schedule,
                workspace,
                executed_run.error or "Skill execution failed",
            )

        return executed_run

    async def _enqueue_deliveries_for_run(self, schedule: Schedule, run: Run) -> list[Delivery]:
        """Create Delivery records and dispatch them to the Celery delivery queue."""
        from app.workers.tasks import deliver_report_task, dispatch_task

        deliveries: list[Delivery] = []

        # Slack delivery
        if schedule.channel in ("slack", "both") and schedule.slack_channel_id:
            deliv = Delivery(
                workspace_id=schedule.workspace_id,
                run_id=run.id,
                schedule_id=schedule.id,
                channel="slack",
                recipient=schedule.slack_channel_name or schedule.slack_channel_id,
                status="pending",
            )
            self.db.add(deliv)
            deliveries.append(deliv)

        # Email delivery
        if schedule.channel in ("email", "both"):
            recipients = schedule.recipients or []
            if not recipients:
                # Fallback to workspace owner email
                owner_email = await self._get_workspace_owner_email(schedule.workspace_id)
                if owner_email:
                    recipients = [owner_email]

            for rec in recipients:
                deliv = Delivery(
                    workspace_id=schedule.workspace_id,
                    run_id=run.id,
                    schedule_id=schedule.id,
                    channel="email",
                    recipient=rec,
                    status="pending",
                )
                self.db.add(deliv)
                deliveries.append(deliv)

        await self.db.commit()

        # Enqueue delivery tasks via Celery worker
        for d in deliveries:
            await self.db.refresh(d)
            dispatch_task(deliver_report_task, str(d.id))

        return deliveries

    async def dispatch_delivery(self, delivery_id: UUID) -> Delivery:
        """Perform the actual delivery of a report to Slack or Email with retry tracking."""
        delivery = await self.db.get(Delivery, delivery_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="Delivery record not found.")

        run = await self.db.get(Run, delivery.run_id)
        if run is None or run.output_json is None:
            delivery.status = "failed"
            delivery.error = "Associated run or report output is missing."
            await self.db.commit()
            return delivery

        workspace = await self.db.get(Workspace, delivery.workspace_id)
        workspace_name = workspace.name if workspace else "Workspace"

        client_name = None
        if run.client_id:
            client = await self.db.get(Client, run.client_id)
            if client:
                client_name = client.name

        report_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard/reports/{run.id}"

        try:
            if delivery.channel == "slack":
                await self._deliver_to_slack(delivery, workspace_name, client_name, run.output_json, report_url)
            elif delivery.channel == "email":
                await self._deliver_to_email(delivery, workspace_name, client_name, run.output_json, report_url)

            delivery.status = "sent"
            delivery.delivered_at = datetime.now(UTC)
            delivery.error = None
            await self.db.commit()
            logger.info("report_delivered_successfully", delivery_id=str(delivery.id), channel=delivery.channel)

        except Exception as exc:
            error_message = str(exc)
            delivery.attempts += 1
            delivery.error = error_message
            if delivery.attempts >= 3:
                delivery.status = "failed"
                # Send alert to workspace owner
                if workspace:
                    await self._send_failure_alert(workspace, delivery.channel, error_message)
            await self.db.commit()
            logger.error(
                "report_delivery_attempt_failed",
                delivery_id=str(delivery.id),
                channel=delivery.channel,
                attempts=delivery.attempts,
                error=error_message,
            )
            raise

        return delivery

    async def _deliver_to_slack(
        self,
        delivery: Delivery,
        workspace_name: str,
        client_name: str | None,
        report_output: dict[str, Any],
        report_url: str,
    ) -> None:
        """Send formatted Block Kit message to Slack."""
        # Find active Slack WorkspaceConnection
        conn_query = select(WorkspaceConnection).where(
            WorkspaceConnection.workspace_id == delivery.workspace_id,
            WorkspaceConnection.provider == "slack",
            WorkspaceConnection.status == "active",
        )
        res = await self.db.execute(conn_query)
        connection = res.scalar_one_or_none()
        if connection is None:
            raise ValueError("No active Slack integration connected to this workspace.")

        account = await self.db.get(ProviderAccount, connection.provider_account_id)
        if account is None:
            raise ValueError("Slack provider account credentials not found.")

        bot_token = decrypt_secret(account.encrypted_token)
        slack_client = SlackClient(token=bot_token)

        blocks = build_slack_block_kit_digest(
            workspace_name=workspace_name,
            client_name=client_name,
            report_output=report_output,
            report_url=report_url,
        )
        headline = report_output.get("headline") or "DeepClient Digest"

        # If delivery.schedule_id is present, get slack_channel_id
        channel_id = None
        if delivery.schedule_id:
            sched = await self.db.get(Schedule, delivery.schedule_id)
            if sched:
                channel_id = sched.slack_channel_id

        target_channel = channel_id or delivery.recipient
        await slack_client.post_message(channel=target_channel, text=headline, blocks=blocks)

    async def _deliver_to_email(
        self,
        delivery: Delivery,
        workspace_name: str,
        client_name: str | None,
        report_output: dict[str, Any],
        report_url: str,
    ) -> None:
        """Send formatted HTML email with unsubscribe header."""
        target_name = client_name or "All Clients"
        headline = report_output.get("headline") or f"Weekly Client Synthesis • {target_name}"
        unsubscribe_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard/schedules?unsubscribe={delivery.recipient}"

        headers = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

        context = {
            "headline": headline,
            "target_name": target_name,
            "workspace_name": workspace_name,
            "needs": report_output.get("needs", [])[:5],
            "risks": report_output.get("risks", [])[:5],
            "patterns": report_output.get("patterns", [])[:3],
            "report_url": report_url,
            "unsubscribe_url": unsubscribe_url,
        }

        plain_text = (
            f"{headline}\n\n"
            f"Client: {target_name} | Workspace: {workspace_name}\n\n"
            f"View your complete report at: {report_url}\n"
        )

        message = build_email(
            recipient=delivery.recipient,
            subject=f"📊 DeepClient Digest: {target_name} ({workspace_name})",
            template_name="notifications/report_digest.html",
            context=context,
            text=plain_text,
            headers=headers,
        )
        send_email(message)

    async def _handle_execution_failure(
        self,
        schedule: Schedule,
        workspace: Workspace,
        error_message: str,
    ) -> None:
        """Log failure and alert workspace owner."""
        logger.error(
            "scheduled_run_execution_failed",
            schedule_id=str(schedule.id),
            workspace_id=str(workspace.id),
            error=error_message,
        )
        await self._send_failure_alert(workspace, "scheduled run", error_message, schedule_name=schedule.name)

    async def _send_failure_alert(
        self,
        workspace: Workspace,
        channel: str,
        error_message: str,
        schedule_name: str = "Scheduled Report",
    ) -> None:
        """Send failure notification email to the workspace owner."""
        owner_email = await self._get_workspace_owner_email(workspace.id)
        if not owner_email or not is_email_configured():
            return

        dashboard_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard/schedules"
        context = {
            "workspace_name": workspace.name,
            "schedule_name": schedule_name,
            "error_message": error_message,
            "dashboard_url": dashboard_url,
        }
        message = build_email(
            recipient=owner_email,
            subject=f"⚠️ Action Required: DeepClient delivery failed in {workspace.name}",
            template_name="notifications/report_failure_alert.html",
            context=context,
            text=(
                f"A scheduled report delivery ({channel}) failed in workspace '{workspace.name}'.\n\n"
                f"Error: {error_message}\n\n"
                f"Review schedules at: {dashboard_url}"
            ),
        )
        try:
            send_email(message)
        except Exception as exc:
            logger.warning("failure_alert_email_failed", error=str(exc))

    async def _get_workspace_owner_email(self, workspace_id: UUID) -> str | None:
        """Look up the email address of the workspace owner."""
        query = (
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role == "owner",
            )
            .limit(1)
        )
        res = await self.db.execute(query)
        return res.scalar_one_or_none()

    async def list_deliveries(
        self,
        workspace_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Delivery], int]:
        """List delivery audit records with pagination."""
        count_query = (
            select(func.count(Delivery.id))
            .where(Delivery.workspace_id == workspace_id)
        )
        total = (await self.db.execute(count_query)).scalar() or 0

        query = (
            select(Delivery)
            .where(Delivery.workspace_id == workspace_id)
            .order_by(Delivery.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total
