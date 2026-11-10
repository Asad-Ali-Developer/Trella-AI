"""Hard token budget management and progressive context shrinking.

Assembles prompts from scoped items, newest activity first, and shrinks
progressively when over budget in strict order:
1. Drop comments older than newest N per card.
2. Use card_summaries (for current content_hash) instead of raw text for oldest cards.
3. Drop oldest cards entirely.
Never cut text mid-item. Keep [ID: <id>] headers so citations still validate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.context.chunker import TokenCounter, default_token_counter
from app.modules.context.models import TrelloCardSummary
from app.modules.context.schemas import ContextItem
from app.modules.github.models import GithubCommit
from app.modules.runs.prompts import (
    build_generation_prompt,
    render_skill_template,
)
from app.modules.trello.models import TrelloCard, TrelloComment


@dataclass
class BudgetDecision:
    """A record of a single context shrinking decision."""

    action: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BudgetResult:
    """The outcome of assembling and shrinking context items to fit token budget."""

    full_prompt: str
    items_sent: list[ContextItem]
    metrics: dict[str, Any]
    initial_tokens: int
    final_tokens: int
    max_budget: int
    shrunk: bool
    decisions: list[dict[str, Any]]


def _compute_metrics(items: list[Any]) -> dict[str, Any]:
    """Code-computed facts the LLM may quote reflecting the scoped set."""
    roles = [
        getattr(i, "author_role", None)
        or (i.metadata.get("author_role") if hasattr(i, "metadata") and isinstance(i.metadata, dict) else None)
        for i in items
    ]
    items_by_type = dict(Counter(str(i.item_type) for i in items))
    return {
        "context_items_total": len(items),
        "items_by_type": items_by_type,
        "card_count": items_by_type.get("card", 0),
        "comment_count": items_by_type.get("comment", 0),
        "commit_count": items_by_type.get("commit", 0),
        "client_authored_items": sum(1 for r in roles if r == "client"),
        "internal_authored_items": sum(1 for r in roles if r == "internal"),
        "role_data_available": any(r in ("client", "internal") for r in roles),
        "event_metrics": "unavailable",
    }


def _item_header(item: Any, item_id: str) -> str:
    author = getattr(item, "author_name", None) or (
        item.metadata.get("author_name") if hasattr(item, "metadata") and isinstance(item.metadata, dict) else None
    )
    role = getattr(item, "author_role", None) or (
        item.metadata.get("author_role") if hasattr(item, "metadata") and isinstance(item.metadata, dict) else None
    ) or "unknown"
    created = getattr(item, "created_at", None) or getattr(item, "occurred_at", None)
    meta = []
    if author:
        meta.append(f"Author: {author}")
    meta.append(f"Role: {role}")
    if created:
        meta.append(f"At: {created}")
    return f"[ID: {item_id}] (Type: {item.item_type}) ({' | '.join(meta)}) {item.title or ''}"


def _card_activity_timestamp(card: TrelloCard) -> datetime:
    ts = card.last_activity_at or card.updated_at or card.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _comment_activity_timestamp(comment: TrelloComment) -> datetime:
    ts = comment.created_at_trello or comment.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _commit_activity_timestamp(commit: GithubCommit) -> datetime:
    ts = commit.committed_at or commit.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _format_card_raw_text(
    card: TrelloCard,
    include_labels: bool = True,
    member_names: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if card.description.strip():
        parts.append(card.description.strip())
    if card.list_name:
        parts.append(f"List: {card.list_name}")
    if include_labels and card.labels:
        label_names = [label["name"] for label in card.labels if label.get("name")]
        if label_names:
            parts.append("Labels: " + ", ".join(label_names))
    if member_names:
        parts.append("Members: " + ", ".join(member_names))
    return "\n".join(parts)


def assemble_and_budget_prompt(
    *,
    cards: list[TrelloCard],
    comments_by_card: dict[UUID, list[TrelloComment]],
    commits: list[GithubCommit],
    summaries_by_card_id: dict[UUID, TrelloCardSummary],
    max_input_tokens: int,
    prompt_template: str,
    client_name: str,
    period_label: str,
    reference_date: str,
    include_labels: bool = True,
    token_counter: TokenCounter = default_token_counter,
    members_by_id: dict[str, Any] | None = None,
    clients_by_id: dict[UUID, Any] | None = None,
) -> BudgetResult:
    """Assemble the prompt from scoped items and shrink if over budget."""
    task_instruction = render_skill_template(prompt_template, client_name)
    members_map = members_by_id or {}
    clients_map = clients_by_id or {}

    # Sort cards newest activity first
    sorted_cards = sorted(cards, key=_card_activity_timestamp, reverse=True)

    # Sort comments per card newest first
    sorted_comments: dict[UUID, list[TrelloComment]] = {}
    for card in sorted_cards:
        cmts = comments_by_card.get(card.id, [])
        sorted_comments[card.id] = sorted(cmts, key=_comment_activity_timestamp, reverse=True)

    # Sort commits newest first
    sorted_commits = sorted(commits, key=_commit_activity_timestamp, reverse=True)

    # Track current state
    active_cards: list[TrelloCard] = list(sorted_cards)
    comments_limit_per_card: int | None = None  # None = keep all
    summarized_card_ids: set[UUID] = set()
    decisions: list[dict[str, Any]] = []

    def _build_context(
        candidate_cards: list[TrelloCard],
        card_comment_limit: int | None,
        summarized_ids: set[UUID],
    ) -> tuple[str, list[ContextItem], dict[str, Any]]:
        candidate_items: list[tuple[datetime, ContextItem]] = []

        # Add cards
        for card in candidate_cards:
            client = clients_map.get(card.client_id) if card.client_id else None
            member_names = [
                members_map[m_id].full_name or members_map[m_id].username
                for m_id in card.member_ids
                if m_id in members_map
            ]

            if card.id in summarized_ids and card.id in summaries_by_card_id:
                card_text = f"Summary: {summaries_by_card_id[card.id].summary}"
                summary_val = summaries_by_card_id[card.id].summary
            else:
                card_text = _format_card_raw_text(card, include_labels, member_names)
                summary_val = None

            c_item = ContextItem(
                item_type="card",
                source_id=card.source_id,
                client_id=client.id if client else None,
                client_name=client.name if client else None,
                card_id=card.id,
                external_id=card.trello_card_id,
                title=card.name,
                text=card_text,
                summary=summary_val,
                url=card.url,
                occurred_at=card.last_activity_at,
                metadata={
                    "list_id": card.list_id,
                    "list_name": card.list_name,
                    "labels": card.labels,
                    "member_ids": card.member_ids,
                    "due_at": card.due_at.isoformat() if card.due_at else None,
                    "closed": card.closed,
                },
            )
            candidate_items.append((_card_activity_timestamp(card), c_item))

            # Add card's comments
            card_cmts = sorted_comments.get(card.id, [])
            if card_comment_limit is not None:
                card_cmts = card_cmts[:card_comment_limit]
            for comment in card_cmts:
                author = members_map.get(comment.author_id)
                author_name = (
                    author.full_name or author.username if author else "Unknown member"
                )
                role_tag: Literal["client", "internal", "unknown"] = (
                    author.role_tag
                    if author and author.role_tag in ("client", "internal")
                    else "unknown"
                )
                cm_item = ContextItem(
                    item_type="comment",
                    source_id=card.source_id,
                    client_id=client.id if client else None,
                    client_name=client.name if client else None,
                    card_id=card.id,
                    external_id=comment.trello_action_id,
                    title=card.name,
                    text=comment.text,
                    url=card.url,
                    occurred_at=comment.created_at_trello,
                    author_name=author_name,
                    author_role=role_tag,
                    metadata={
                        "author_id": comment.author_id,
                        "author_name": author_name,
                        "author_role": role_tag,
                    },
                )
                candidate_items.append((_comment_activity_timestamp(comment), cm_item))

        # Add commits
        for commit in sorted_commits:
            client = clients_map.get(commit.repository_id) if hasattr(commit, "client_id") else None
            msg_lines = commit.message.splitlines()
            co_item = ContextItem(
                item_type="commit",
                source_id=commit.repository_id,
                external_id=commit.sha,
                title=msg_lines[0] if msg_lines else commit.sha[:7],
                text=commit.message,
                url=commit.url,
                occurred_at=commit.committed_at,
                author_name=commit.author_name,
                author_role="internal",
                metadata={
                    "author": commit.author_name,
                    "author_login": commit.author_login,
                    "author_role": "internal",
                },
            )
            candidate_items.append((_commit_activity_timestamp(commit), co_item))

        # Sort all items newest activity first
        candidate_items.sort(key=lambda x: x[0], reverse=True)
        final_items = [item for _, item in candidate_items]

        # Format items into context text
        formatted_blocks = [
            f"{_item_header(item, str(item.card_id or item.external_id or item.source_id or 'unknown').strip())}\n{item.text}\n"
            for item in final_items
        ]
        ctx_text = "\n---\n".join(formatted_blocks)
        comp_metrics = _compute_metrics(final_items)

        prompt = build_generation_prompt(
            task_instruction=task_instruction,
            client_name=client_name,
            period=period_label,
            reference_date=reference_date,
            metrics=comp_metrics,
            context_text=ctx_text,
        )
        return prompt, final_items, comp_metrics

    # Initial prompt evaluation
    current_prompt, current_items, current_metrics = _build_context(
        active_cards, comments_limit_per_card, summarized_card_ids
    )
    initial_tokens = token_counter(current_prompt)
    current_tokens = initial_tokens

    if current_tokens <= max_input_tokens:
        return BudgetResult(
            full_prompt=current_prompt,
            items_sent=current_items,
            metrics=current_metrics,
            initial_tokens=initial_tokens,
            final_tokens=current_tokens,
            max_budget=max_input_tokens,
            shrunk=False,
            decisions=[],
        )

    # --- Step a: Drop comments older than newest N per card ---
    max_cmts_on_any_card = max(
        (len(sorted_comments.get(c.id, [])) for c in active_cards),
        default=0,
    )
    candidate_limits: list[int] = []
    for lim in [10, 5, 3, 2, 1, 0]:
        if lim < max_cmts_on_any_card:
            candidate_limits.append(lim)
    if 0 not in candidate_limits:
        candidate_limits.append(0)

    for limit in candidate_limits:
        comments_limit_per_card = limit
        candidate_prompt, candidate_items, candidate_metrics = _build_context(
            active_cards, comments_limit_per_card, summarized_card_ids
        )
        current_tokens = token_counter(candidate_prompt)
        dropped_count = sum(
            max(0, len(sorted_comments.get(c.id, [])) - limit) for c in active_cards
        )
        decisions.append(
            {
                "step": "drop_comments",
                "comments_per_card_limit": limit,
                "dropped_comments_count": dropped_count,
            }
        )
        if current_tokens <= max_input_tokens:
            return BudgetResult(
                full_prompt=candidate_prompt,
                items_sent=candidate_items,
                metrics=candidate_metrics,
                initial_tokens=initial_tokens,
                final_tokens=current_tokens,
                max_budget=max_input_tokens,
                shrunk=True,
                decisions=decisions,
            )

    # --- Step b: Use card_summaries for the oldest cards ---
    oldest_first_cards = sorted(active_cards, key=_card_activity_timestamp)
    for card in oldest_first_cards:
        summary = summaries_by_card_id.get(card.id)
        if summary is not None and summary.content_hash == card.content_hash:
            summarized_card_ids.add(card.id)
            candidate_prompt, candidate_items, candidate_metrics = _build_context(
                active_cards, comments_limit_per_card, summarized_card_ids
            )
            current_tokens = token_counter(candidate_prompt)
            decisions.append(
                {
                    "step": "use_card_summaries",
                    "card_id": str(card.id),
                    "summarized_cards_count": len(summarized_card_ids),
                }
            )
            if current_tokens <= max_input_tokens:
                return BudgetResult(
                    full_prompt=candidate_prompt,
                    items_sent=candidate_items,
                    metrics=candidate_metrics,
                    initial_tokens=initial_tokens,
                    final_tokens=current_tokens,
                    max_budget=max_input_tokens,
                    shrunk=True,
                    decisions=decisions,
                )

    # --- Step c: Drop oldest cards entirely ---
    while len(active_cards) > 1:
        oldest_card = min(active_cards, key=_card_activity_timestamp)
        active_cards.remove(oldest_card)
        candidate_prompt, candidate_items, candidate_metrics = _build_context(
            active_cards, comments_limit_per_card, summarized_card_ids
        )
        current_tokens = token_counter(candidate_prompt)
        decisions.append(
            {
                "step": "drop_oldest_cards",
                "dropped_card_id": str(oldest_card.id),
                "remaining_cards_count": len(active_cards),
            }
        )
        if current_tokens <= max_input_tokens:
            return BudgetResult(
                full_prompt=candidate_prompt,
                items_sent=candidate_items,
                metrics=candidate_metrics,
                initial_tokens=initial_tokens,
                final_tokens=current_tokens,
                max_budget=max_input_tokens,
                shrunk=True,
                decisions=decisions,
            )

    # If even the minimum set exceeds budget, fail with clear error
    if current_tokens > max_input_tokens:
        raise ValueError(
            f"Token budget exceeded: minimum prompt ({current_tokens} tokens) "
            f"exceeds RUN_MAX_INPUT_TOKENS ({max_input_tokens})."
        )

    return BudgetResult(
        full_prompt=current_prompt,
        items_sent=current_items,
        metrics=current_metrics,
        initial_tokens=initial_tokens,
        final_tokens=current_tokens,
        max_budget=max_input_tokens,
        shrunk=True,
        decisions=decisions,
    )
