"""Scope resolution module for skill runs.

Resolves skill.scope_json in SQL queries strictly scoped by workspace_id,
filtering sources, clients, included item types, and activity timestamp ranges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.trello.models import TrelloCard, TrelloComment, TrelloSource

ALLOWED_INCLUDES: set[str] = {
    "cards",
    "comments",
    "commits",
    "labels",
    "checklists",
    "projects",
}


class ScopeValidationError(ValueError):
    """Raised when skill.scope_json contains unknown, invalid, or malformed values."""


@dataclass(frozen=True)
class ValidatedScopeConfig:
    """Parsed and validated scope configuration."""

    all_sources: bool
    source_board_ids: list[str] = field(default_factory=list)
    source_uuids: list[UUID] = field(default_factory=list)
    all_clients: bool = True
    client_ids: list[UUID] = field(default_factory=list)
    include: set[str] = field(default_factory=lambda: {"cards", "comments", "commits"})
    date_range_type: str = "all"  # "all", "last_7_days", "last_14_days", "last_30_days", "explicit"
    explicit_date_from: datetime | None = None
    explicit_date_to: datetime | None = None


@dataclass
class ResolvedScope:
    """The resolved set of IDs and metadata in scope."""

    card_ids: set[UUID]
    comment_ids: set[UUID]
    commit_ids: set[UUID]
    date_from: datetime | None
    date_to: datetime | None
    period_label: str
    include_labels: bool
    include_checklists: bool
    include_cards: bool
    include_comments: bool
    include_commits: bool


def _parse_iso_datetime(value: Any, field_name: str) -> datetime:
    """Parse an ISO 8601 date or datetime string with UTC timezone."""
    if not isinstance(value, str):
        raise ScopeValidationError(
            f"Invalid {field_name}: expected ISO date string, got {type(value).__name__}."
        )
    val = value.strip()
    if not val:
        raise ScopeValidationError(f"Invalid {field_name}: empty date string.")
    try:
        dt = datetime.fromisoformat(val)
    except ValueError as exc:
        raise ScopeValidationError(
            f"Invalid {field_name} '{val}': must be valid ISO 8601 format."
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class ScopeResolver:
    """Validates scope_json and executes SQL queries to resolve items in scope."""

    @staticmethod
    def validate_scope(scope_json: dict[str, Any] | None) -> ValidatedScopeConfig:
        """Validate scope_json schema and semantics, raising ScopeValidationError on error."""
        if scope_json is None:
            return ValidatedScopeConfig(
                all_sources=True,
                all_clients=True,
                include={"cards", "comments", "commits"},
                date_range_type="all",
            )

        if not isinstance(scope_json, dict):
            raise ScopeValidationError(
                f"scope_json must be a dict or null, got {type(scope_json).__name__}."
            )

        # 1. Sources
        all_sources = False
        board_ids: list[str] = []
        source_uuids: list[UUID] = []
        raw_sources = scope_json.get("sources")
        if raw_sources is None:
            all_sources = True
        elif isinstance(raw_sources, str):
            if raw_sources in ("*", "board:*"):
                all_sources = True
            else:
                raise ScopeValidationError(
                    f"Invalid sources string '{raw_sources}'. Expected 'board:*' or '*'."
                )
        elif isinstance(raw_sources, (list, tuple)):
            if not raw_sources:
                all_sources = False
            else:
                for src in raw_sources:
                    if not isinstance(src, str):
                        raise ScopeValidationError(
                            f"Invalid source entry {src!r}: expected string."
                        )
                    src_str = src.strip()
                    if not src_str:
                        raise ScopeValidationError("Invalid source entry: empty string.")
                    if src_str in ("*", "board:*"):
                        all_sources = True
                        continue
                    if src_str.startswith("board:"):
                        val = src_str[len("board:") :].strip()
                        if not val:
                            raise ScopeValidationError(
                                f"Invalid source entry '{src_str}': empty board identifier."
                            )
                        board_ids.append(val)
                        try:
                            source_uuids.append(UUID(val))
                        except ValueError:
                            pass
                    elif ":" in src_str:
                        raise ScopeValidationError(
                            f"Unsupported source prefix in '{src_str}'. Only 'board:' is supported."
                        )
                    else:
                        board_ids.append(src_str)
                        try:
                            source_uuids.append(UUID(src_str))
                        except ValueError:
                            pass
        else:
            raise ScopeValidationError(
                f"Invalid sources type: {type(raw_sources).__name__}. Expected list or string."
            )

        # 2. Clients
        all_clients = False
        client_ids: list[UUID] = []
        raw_clients = scope_json.get("clients")
        if raw_clients is None or raw_clients == "all":
            all_clients = True
        elif isinstance(raw_clients, str):
            try:
                client_ids.append(UUID(raw_clients.strip()))
            except ValueError as exc:
                raise ScopeValidationError(
                    f"Invalid client '{raw_clients}'. Expected 'all' or valid UUID."
                ) from exc
        elif isinstance(raw_clients, (list, tuple)):
            for c in raw_clients:
                if c == "all":
                    all_clients = True
                    continue
                if isinstance(c, UUID):
                    client_ids.append(c)
                elif isinstance(c, str):
                    try:
                        client_ids.append(UUID(c.strip()))
                    except ValueError as exc:
                        raise ScopeValidationError(
                            f"Invalid client ID '{c}'. Expected valid UUID."
                        ) from exc
                else:
                    raise ScopeValidationError(
                        f"Invalid client entry {c!r}: expected UUID or UUID string."
                    )
        else:
            raise ScopeValidationError(
                f"Invalid clients type: {type(raw_clients).__name__}. Expected 'all' or list of UUIDs."
            )

        # 3. Include
        raw_include = scope_json.get("include")
        if raw_include is None:
            include_set = {"cards", "comments", "commits"}
        elif isinstance(raw_include, (list, tuple, set)):
            include_set = set()
            for inc in raw_include:
                if not isinstance(inc, str):
                    raise ScopeValidationError(
                        f"Invalid include item {inc!r}: expected string."
                    )
                inc_clean = inc.strip().lower()
                if inc_clean not in ALLOWED_INCLUDES:
                    raise ScopeValidationError(
                        f"Unknown include token '{inc}'. Allowed tokens are: {sorted(ALLOWED_INCLUDES)}."
                    )
                include_set.add(inc_clean)
        else:
            raise ScopeValidationError(
                f"Invalid include type: {type(raw_include).__name__}. Expected list of strings."
            )

        # 4. Date Range
        raw_date_range = scope_json.get("date_range")
        date_range_type = "all"
        explicit_date_from: datetime | None = None
        explicit_date_to: datetime | None = None

        if raw_date_range is None or raw_date_range == "all":
            date_range_type = "all"
        elif isinstance(raw_date_range, str):
            dr_clean = raw_date_range.strip().lower()
            if dr_clean in ("last_7_days", "last_14_days", "last_30_days", "all"):
                date_range_type = dr_clean
            else:
                raise ScopeValidationError(
                    f"Unknown date_range '{raw_date_range}'. "
                    "Expected 'last_7_days', 'last_14_days', 'last_30_days', 'all', or a dict with from/to."
                )
        elif isinstance(raw_date_range, dict):
            extra_keys = set(raw_date_range.keys()) - {"from", "to"}
            if extra_keys:
                raise ScopeValidationError(
                    f"Invalid keys in date_range dict: {sorted(extra_keys)}. Only 'from' and 'to' are permitted."
                )
            if "from" not in raw_date_range and "to" not in raw_date_range:
                raise ScopeValidationError(
                    "date_range dict must contain at least one of 'from' or 'to'."
                )
            date_range_type = "explicit"
            if "from" in raw_date_range and raw_date_range["from"] is not None:
                explicit_date_from = _parse_iso_datetime(raw_date_range["from"], "date_range 'from'")
            if "to" in raw_date_range and raw_date_range["to"] is not None:
                explicit_date_to = _parse_iso_datetime(raw_date_range["to"], "date_range 'to'")

            if (
                explicit_date_from is not None
                and explicit_date_to is not None
                and explicit_date_from > explicit_date_to
            ):
                raise ScopeValidationError("date_range 'from' cannot be after 'to'.")
        else:
            raise ScopeValidationError(
                f"Invalid date_range type: {type(raw_date_range).__name__}."
            )

        return ValidatedScopeConfig(
            all_sources=all_sources,
            source_board_ids=board_ids,
            source_uuids=source_uuids,
            all_clients=all_clients,
            client_ids=client_ids,
            include=include_set,
            date_range_type=date_range_type,
            explicit_date_from=explicit_date_from,
            explicit_date_to=explicit_date_to,
        )

    @classmethod
    async def resolve(
        cls,
        db: AsyncSession,
        workspace_id: UUID,
        scope_json: dict[str, Any] | None,
        client_id_override: UUID | None = None,
        now: datetime | None = None,
    ) -> ResolvedScope:
        """Resolve scope configuration into exact card, comment, and commit IDs via SQL."""
        config = cls.validate_scope(scope_json)
        current_time = now or datetime.now(UTC)

        # Compute resolved date_from / date_to
        date_from: datetime | None = None
        date_to: datetime | None = None
        if config.date_range_type == "last_7_days":
            date_from = current_time - timedelta(days=7)
            date_to = current_time
            period_label = f"{date_from.date().isoformat()} to {date_to.date().isoformat()}"
        elif config.date_range_type == "last_14_days":
            date_from = current_time - timedelta(days=14)
            date_to = current_time
            period_label = f"{date_from.date().isoformat()} to {date_to.date().isoformat()}"
        elif config.date_range_type == "last_30_days":
            date_from = current_time - timedelta(days=30)
            date_to = current_time
            period_label = f"{date_from.date().isoformat()} to {date_to.date().isoformat()}"
        elif config.date_range_type == "explicit":
            date_from = config.explicit_date_from
            date_to = config.explicit_date_to
            if date_from and date_to:
                period_label = f"{date_from.date().isoformat()} to {date_to.date().isoformat()}"
            elif date_from:
                period_label = f"since {date_from.date().isoformat()}"
            elif date_to:
                period_label = f"until {date_to.date().isoformat()}"
            else:
                period_label = "all"
        else:
            date_from = None
            date_to = None
            period_label = "all"

        # Resolve effective client IDs
        effective_client_ids: list[UUID] | None = None
        if client_id_override is not None:
            if config.all_clients or client_id_override in config.client_ids:
                effective_client_ids = [client_id_override]
            else:
                effective_client_ids = []  # Explicit client override not in scoped clients
        elif not config.all_clients:
            effective_client_ids = list(config.client_ids)

        # Resolve matching Trello sources
        matching_source_ids: list[UUID] | None = None
        if not config.all_sources:
            src_query = select(TrelloSource.id).where(
                TrelloSource.workspace_id == workspace_id,
            )
            conditions = []
            if config.source_board_ids:
                conditions.append(TrelloSource.trello_board_id.in_(config.source_board_ids))
            if config.source_uuids:
                conditions.append(TrelloSource.id.in_(config.source_uuids))
            if conditions:
                src_query = src_query.where(or_(*conditions))
            else:
                src_query = src_query.where(false())
            res = await db.scalars(src_query)
            matching_source_ids = list(res.all())

        # 1. Resolve Cards
        card_ids: set[UUID] = set()
        include_cards = "cards" in config.include
        if include_cards:
            if matching_source_ids is not None and len(matching_source_ids) == 0:
                card_ids = set()
            elif effective_client_ids is not None and len(effective_client_ids) == 0:
                card_ids = set()
            else:
                query = select(TrelloCard.id).where(TrelloCard.workspace_id == workspace_id)
                if matching_source_ids is not None:
                    query = query.where(TrelloCard.source_id.in_(matching_source_ids))
                if effective_client_ids is not None:
                    query = query.where(TrelloCard.client_id.in_(effective_client_ids))
                if date_from is not None:
                    query = query.where(TrelloCard.last_activity_at >= date_from)
                if date_to is not None:
                    query = query.where(TrelloCard.last_activity_at <= date_to)
                res = await db.scalars(query)
                card_ids = set(res.all())

        # 2. Resolve Comments
        comment_ids: set[UUID] = set()
        include_comments = "comments" in config.include
        if include_comments:
            if matching_source_ids is not None and len(matching_source_ids) == 0:
                comment_ids = set()
            elif effective_client_ids is not None and len(effective_client_ids) == 0:
                comment_ids = set()
            else:
                query = (
                    select(TrelloComment.id)
                    .join(TrelloCard, TrelloComment.card_id == TrelloCard.id)
                    .where(TrelloCard.workspace_id == workspace_id)
                )
                if matching_source_ids is not None:
                    query = query.where(TrelloCard.source_id.in_(matching_source_ids))
                if effective_client_ids is not None:
                    query = query.where(TrelloCard.client_id.in_(effective_client_ids))
                if date_from is not None:
                    query = query.where(TrelloComment.created_at_trello >= date_from)
                if date_to is not None:
                    query = query.where(TrelloComment.created_at_trello <= date_to)
                res = await db.scalars(query)
                comment_ids = set(res.all())

        # 3. Resolve Commits
        commit_ids: set[UUID] = set()
        include_commits = "commits" in config.include
        # Commits belong to GitHub repos, which are included if all_sources is True
        if include_commits and config.all_sources:
            if effective_client_ids is not None and len(effective_client_ids) == 0:
                commit_ids = set()
            else:
                query = (
                    select(GithubCommit.id)
                    .join(GithubRepository, GithubCommit.repository_id == GithubRepository.id)
                    .where(GithubCommit.workspace_id == workspace_id)
                )
                if effective_client_ids is not None:
                    query = query.where(GithubRepository.client_id.in_(effective_client_ids))
                if date_from is not None:
                    query = query.where(GithubCommit.committed_at >= date_from)
                if date_to is not None:
                    query = query.where(GithubCommit.committed_at <= date_to)
                res = await db.scalars(query)
                commit_ids = set(res.all())

        return ResolvedScope(
            card_ids=card_ids,
            comment_ids=comment_ids,
            commit_ids=commit_ids,
            date_from=date_from,
            date_to=date_to,
            period_label=period_label,
            include_labels="labels" in config.include,
            include_checklists="checklists" in config.include,
            include_cards=include_cards,
            include_comments=include_comments,
            include_commits=include_commits,
        )
