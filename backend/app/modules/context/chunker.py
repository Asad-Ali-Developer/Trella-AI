"""Pure chunking functions for Trello cards, comments, and GitHub commits.

No database access, no network calls, and no raw card/comment content in logs.
"""

import hashlib
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

CHUNKER_VERSION: int = 1
DEFAULT_TARGET_TOKENS: int = 400
DEFAULT_OVERLAP_TOKENS: int = 50
DEFAULT_COMMENTS_PER_GROUP: int = 10

ChunkKind = Literal[
    "card_body",
    "comment_group",
    "commit_group",
    "issue_body",
    "issue_comment_group",
    "issue_transition_group",
]

CHUNKER_VERSION_BY_KIND: dict[str, int] = {
    "card_body": 1,
    "comment_group": 1,
    "commit_group": 1,
    "issue_body": 2,
    "issue_comment_group": 2,
    "issue_transition_group": 2,
}


def chunker_version_for_kind(kind: str) -> int:
    """Return the active chunker version for `kind` without invalidating older kinds."""
    return CHUNKER_VERSION_BY_KIND.get(kind, CHUNKER_VERSION)


class TokenCounter(Protocol):
    """Protocol for estimating token count of a text string."""

    def __call__(self, text: str) -> int:
        """Return the estimated token count for `text`."""
        ...


def default_token_counter(text: str) -> int:
    """Estimate token count as 0 for empty text, otherwise ceil(len(text) / 4)."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def compute_content_hash(
    text: str,
    chunker_version: int = CHUNKER_VERSION,
) -> str:
    """Compute deterministic SHA-256 content hash over (text, chunker_version) only.

    Re-embedding on model or dimension changes is determined by comparing
    chunks.embedding_model against Settings, not via content_hash.
    """
    payload = f"{chunker_version}\0{text}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Chunk:
    """Pure output chunk produced by the chunker."""

    kind: ChunkKind
    ordinal: int
    text: str
    token_estimate: int
    occurred_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    group_key: str | None = None


@dataclass(frozen=True)
class CardBodyInput:
    """Input data for chunking a Trello card body."""

    client_name: str | None
    board_name: str
    list_name: str | None
    card_title: str
    description: str = ""
    labels: Sequence[str] = ()
    checklists: Sequence[dict[str, Any]] = ()
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommentInput:
    """Input data for a single card comment."""

    comment_id: str
    author_name: str
    created_at: datetime
    text: str


@dataclass(frozen=True)
class CommitInput:
    """Input data for a single GitHub commit."""

    commit_id: str
    sha: str
    author_name: str
    committed_at: datetime
    message: str


@dataclass(frozen=True)
class IssueBodyInput:
    """Input data for chunking a Jira issue body."""

    client_name: str | None
    project_name: str
    issue_key: str
    summary: str
    description: str = ""
    status: str = ""
    issue_type: str = ""
    priority: str | None = None
    assignee: str | None = None
    reporter: str | None = None
    labels: Sequence[str] = ()
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IssueCommentInput:
    """Input data for a single Jira issue comment."""

    comment_id: str
    author_name: str
    created_at: datetime
    body: str


@dataclass(frozen=True)
class IssueTransitionInput:
    """Input data for a single Jira changelog field transition."""

    history_id: str
    item_index: int
    field: str
    from_value: str | None
    to_value: str | None
    author_name: str
    created_at: datetime


def _card_header(
    client_name: str | None,
    board_name: str,
    list_name: str | None,
    card_title: str,
) -> str:
    client_label = (client_name or "").strip() or "Unassigned"
    board_label = board_name.strip() or "Untitled Board"
    list_label = (list_name or "").strip() or "Unspecified"
    title_label = card_title.strip() or "Untitled Card"
    return f"Client: {client_label} | Board: {board_label} | List: {list_label} | Card: {title_label}"


def _commit_header(
    client_name: str | None,
    repo_name: str,
    date_str: str,
) -> str:
    client_label = (client_name or "").strip() or "Unassigned"
    repo_label = repo_name.strip() or "Unknown Repo"
    return f"Client: {client_label} | Repo: {repo_label} | Date: {date_str}"


def _issue_header(
    client_name: str | None,
    project_name: str,
    issue_key: str,
    summary: str,
) -> str:
    client_label = (client_name or "").strip() or "Unassigned"
    project_label = project_name.strip() or "Untitled Project"
    key_label = issue_key.strip() or "UNKNOWN"
    summary_label = summary.strip() or "Untitled Issue"
    return f"Client: {client_label} | Project: {project_label} | Issue {key_label}: {summary_label}"


def _format_checklists(checklists: Sequence[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for checklist in checklists:
        name = str(checklist.get("name") or "Checklist").strip()
        items = checklist.get("items") or checklist.get("checkItems") or []
        if not isinstance(items, Sequence):
            continue
        formatted_items: list[str] = []
        for item in items:
            if isinstance(item, dict):
                item_name = str(item.get("name") or "").strip()
                state = str(item.get("state") or "incomplete").lower()
                marker = "[x]" if state in ("complete", "completed", "done", "true") else "[ ]"
                if item_name:
                    formatted_items.append(f"{marker} {item_name}")
            elif isinstance(item, str) and item.strip():
                formatted_items.append(f"[ ] {item.strip()}")
        if formatted_items:
            lines.append(f"{name}: " + "; ".join(formatted_items))
    return lines


def _split_body_with_overlap(
    body: str,
    *,
    header: str,
    counter: TokenCounter,
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Split `body` into chunks each prefixed by `header`, applying overlap only when needed."""
    full_single = f"{header}\n{body}" if body else header
    if counter(full_single) <= target_tokens:
        return [full_single]

    header_prefix = f"{header}\n"
    header_tokens = counter(header_prefix)
    body_budget_tokens = max(16, target_tokens - header_tokens)
    safe_overlap_tokens = max(0, min(overlap_tokens, body_budget_tokens // 2))

    # Derive character window sizes guided by token counter, then refine per slice
    approx_chars_per_token = max(1, math.floor(len(body) / max(1, counter(body))))
    window_chars = max(32, body_budget_tokens * approx_chars_per_token)
    overlap_chars = max(0, safe_overlap_tokens * approx_chars_per_token)

    chunks_out: list[str] = []
    start = 0
    n = len(body)

    while start < n:
        end = min(n, start + window_chars)
        # Adjust `end` downward if counter(header_prefix + slice) exceeds target_tokens
        while end > start + 16 and counter(header_prefix + body[start:end]) > target_tokens:
            shrink = max(8, (end - start) // 8)
            end = max(start + 16, end - shrink)

        # Prefer breaking on a whitespace/newline boundary if available near `end`
        if end < n:
            boundary_floor = start + max(16, int((end - start) * 0.7))
            newline_pos = body.rfind("\n", boundary_floor, end)
            space_pos = body.rfind(" ", boundary_floor, end)
            best_break = max(newline_pos, space_pos)
            if best_break > start:
                end = best_break + 1

        slice_text = body[start:end]
        chunks_out.append(f"{header_prefix}{slice_text}")

        if end >= n:
            break

        if overlap_chars > 0:
            next_start = max(start + 1, end - overlap_chars)
            # Align overlap start to a word boundary when possible without losing coverage
            if next_start > start + 1 and next_start < end:
                ws = body.find(" ", next_start, min(end, next_start + 24))
                if ws != -1 and ws + 1 < end:
                    next_start = ws + 1
            start = next_start
        else:
            start = end

    return chunks_out


def chunk_card_body(
    card: CardBodyInput,
    *,
    counter: TokenCounter = default_token_counter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    chunker_version: int = CHUNKER_VERSION,
) -> list[Chunk]:
    """Build card_body chunks starting with 'Client: X | Board: Y | List: Z | Card: Title'.

    Includes title, description, labels, and checklists.
    Fits in a single chunk without overlap when <= target_tokens (~400).
    When exceeding target_tokens, splits into multiple chunks of ~target_tokens
    with ~overlap_tokens (~50) overlap, repeating the header on every chunk.
    Never truncates long text.
    """
    header = _card_header(card.client_name, card.board_name, card.list_name, card.card_title)
    sections: list[str] = [f"Title: {card.card_title.strip()}"]
    if card.labels:
        clean_labels = [lbl.strip() for lbl in card.labels if lbl and lbl.strip()]
        if clean_labels:
            sections.append("Labels: " + ", ".join(clean_labels))
    checklist_lines = _format_checklists(card.checklists)
    if checklist_lines:
        sections.extend(checklist_lines)
    if card.description:
        sections.append(f"Description: {card.description}")

    body = "\n".join(sections)
    chunk_texts = _split_body_with_overlap(
        body,
        header=header,
        counter=counter,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )

    total_parts = len(chunk_texts)
    result: list[Chunk] = []
    for ordinal, text in enumerate(chunk_texts):
        meta = dict(card.metadata)
        meta["part_count"] = total_parts
        result.append(
            Chunk(
                kind="card_body",
                ordinal=ordinal,
                text=text,
                token_estimate=counter(text),
                occurred_at=card.occurred_at,
                metadata=meta,
                content_hash=compute_content_hash(text, chunker_version=chunker_version),
                group_key=None,
            )
        )
    return result


def chunk_comments(
    comments: Sequence[CommentInput],
    *,
    client_name: str | None,
    board_name: str,
    list_name: str | None,
    card_title: str,
    comments_per_group: int = DEFAULT_COMMENTS_PER_GROUP,
    counter: TokenCounter = default_token_counter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    chunker_version: int = CHUNKER_VERSION,
) -> list[Chunk]:
    """Group comments by fixed positional buckets (ordered by created_at, comment_id).

    1. Sorts comments deterministically by (created_at, comment_id).
    2. Partitions into fixed-size positional windows of `comments_per_group` (e.g. 10).
    3. Token-splits ONLY within a single positional window if that window exceeds
       `target_tokens` (~400 tokens), so editing any comment never shifts comment
       boundaries in earlier or later positional groups.
    4. Every chunk starts with 'Client: X | Board: Y | List: Z | Card: Title' and
       formats each comment with author and ISO timestamp.

    Note: Deleting a comment shifts positional groups after it (whereas edits to
    existing comments and append-only comment additions stay local to the affected
    positional group).
    """
    if not comments:
        return []

    def _utc_dt(dt: datetime) -> datetime:
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    bucket_size = max(1, comments_per_group)
    header = _card_header(client_name, board_name, list_name, card_title)
    sorted_comments = sorted(
        comments,
        key=lambda c: (_utc_dt(c.created_at), str(c.comment_id)),
    )

    chunks: list[Chunk] = []

    for group_idx, start_idx in enumerate(range(0, len(sorted_comments), bucket_size)):
        group = sorted_comments[start_idx : start_idx + bucket_size]
        comment_ids = [str(c.comment_id) for c in group]
        latest_at = max(_utc_dt(c.created_at) for c in group)
        lines = [
            f"[{_utc_dt(c.created_at).isoformat()}] {c.author_name.strip() or 'Unknown'}: {c.text}"
            for c in group
        ]
        group_body = "\n".join(lines)
        full_group_text = f"{header}\n{group_body}"

        if counter(full_group_text) <= target_tokens:
            chunks.append(
                Chunk(
                    kind="comment_group",
                    ordinal=group_idx * 100,
                    text=full_group_text,
                    token_estimate=counter(full_group_text),
                    occurred_at=latest_at,
                    metadata={
                        "group_index": group_idx,
                        "comment_ids": comment_ids,
                    },
                    content_hash=compute_content_hash(
                        full_group_text, chunker_version=chunker_version
                    ),
                    group_key=None,
                )
            )
        else:
            # Token-split strictly within this positional group so other groups are unaffected
            sub_chunks = _split_body_with_overlap(
                group_body,
                header=header,
                counter=counter,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
            )
            if len(sub_chunks) >= 100:
                raise ValueError(
                    f"Comment group {group_idx} requires {len(sub_chunks)} sub-chunks; "
                    "maximum supported is 99 sub-chunks per group."
                )
            for sub_idx, sub_text in enumerate(sub_chunks):
                chunks.append(
                    Chunk(
                        kind="comment_group",
                        ordinal=group_idx * 100 + sub_idx,
                        text=sub_text,
                        token_estimate=counter(sub_text),
                        occurred_at=latest_at,
                        metadata={
                            "group_index": group_idx,
                            "sub_index": sub_idx,
                            "comment_ids": comment_ids,
                        },
                        content_hash=compute_content_hash(
                            sub_text, chunker_version=chunker_version
                        ),
                        group_key=None,
                    )
                )

    return chunks


def chunk_commits(
    commits: Sequence[CommitInput],
    *,
    client_name: str | None,
    repo_name: str,
    counter: TokenCounter = default_token_counter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    chunker_version: int = CHUNKER_VERSION,
) -> list[Chunk]:
    """Group commits per repository per UTC date (YYYY-MM-DD) up to ~400 tokens.

    1. Buckets commits by UTC date `group_key = committed_at.date().isoformat()`,
       ordered deterministically by (committed_at, sha, commit_id).
    2. Within each date bucket, packs commits into chunks of ~target_tokens
       (splitting oversized single commit messages across chunks if needed, with no truncation).
    3. Every chunk starts with 'Client: X | Repo: R | Date: YYYY-MM-DD', sets
       `group_key = YYYY-MM-DD` (ordinal 0..k within that date), and records
       `metadata["commit_ids"]` and `metadata["commit_shas"]`.
    """
    if not commits:
        return []

    def _utc_dt(dt: datetime) -> datetime:
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    sorted_commits = sorted(
        commits,
        key=lambda c: (_utc_dt(c.committed_at), c.sha, str(c.commit_id)),
    )

    by_date: dict[str, list[CommitInput]] = defaultdict(list)
    for commit in sorted_commits:
        date_key = _utc_dt(commit.committed_at).date().isoformat()
        by_date[date_key].append(commit)

    output: list[Chunk] = []

    for date_key in sorted(by_date.keys()):
        day_commits = by_date[date_key]
        header = _commit_header(client_name, repo_name, date_key)
        ordinal = 0

        current_lines: list[str] = []
        current_ids: list[str] = []
        current_shas: list[str] = []
        current_latest: datetime | None = None

        def _flush_current(date_str: str = date_key, hdr: str = header) -> None:
            nonlocal ordinal, current_lines, current_ids, current_shas, current_latest
            if not current_lines:
                return
            body = "\n".join(current_lines)
            full_text = f"{hdr}\n{body}"
            output.append(
                Chunk(
                    kind="commit_group",
                    ordinal=ordinal,
                    text=full_text,
                    token_estimate=counter(full_text),
                    occurred_at=current_latest,
                    metadata={
                        "date": date_str,
                        "commit_ids": list(current_ids),
                        "commit_shas": list(current_shas),
                    },
                    content_hash=compute_content_hash(full_text, chunker_version=chunker_version),
                    group_key=date_str,
                )
            )
            ordinal += 1
            current_lines = []
            current_ids = []
            current_shas = []
            current_latest = None

        for commit in day_commits:
            commit_dt = _utc_dt(commit.committed_at)
            author = commit.author_name.strip() or "Unknown"
            line = f"{commit.sha[:7]} ({author}, {commit_dt.isoformat()}): {commit.message}"
            candidate_lines = [*current_lines, line]
            candidate_text = f"{header}\n" + "\n".join(candidate_lines)

            if current_lines and counter(candidate_text) > target_tokens:
                _flush_current()

            # Check if the single commit line itself exceeds target_tokens
            single_text = f"{header}\n{line}"
            if counter(single_text) > target_tokens:
                sub_texts = _split_body_with_overlap(
                    line,
                    header=header,
                    counter=counter,
                    target_tokens=target_tokens,
                    overlap_tokens=0,
                )
                for sub_text in sub_texts:
                    output.append(
                        Chunk(
                            kind="commit_group",
                            ordinal=ordinal,
                            text=sub_text,
                            token_estimate=counter(sub_text),
                            occurred_at=commit_dt,
                            metadata={
                                "date": date_key,
                                "commit_ids": [str(commit.commit_id)],
                                "commit_shas": [commit.sha],
                            },
                            content_hash=compute_content_hash(
                                sub_text, chunker_version=chunker_version
                            ),
                            group_key=date_key,
                        )
                    )
                    ordinal += 1
            else:
                current_lines.append(line)
                current_ids.append(str(commit.commit_id))
                current_shas.append(commit.sha)
                if current_latest is None or commit_dt > current_latest:
                    current_latest = commit_dt

        _flush_current()

    return output


def chunk_issue_body(
    issue: IssueBodyInput,
    *,
    counter: TokenCounter = default_token_counter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    chunker_version: int | None = None,
) -> list[Chunk]:
    """Build issue_body chunks starting with 'Client: X | Project: Y | Issue KEY: summary'.

    Includes description, status, issue type, priority, assignee, and labels.
    Never truncates long text; splits with overlap when > target_tokens (~400).
    """
    ver = chunker_version if chunker_version is not None else chunker_version_for_kind("issue_body")
    header = _issue_header(
        issue.client_name,
        issue.project_name,
        issue.issue_key,
        issue.summary,
    )
    sections: list[str] = [f"Issue: {issue.issue_key.strip()} - {issue.summary.strip()}"]
    if issue.status.strip():
        sections.append(f"Status: {issue.status.strip()}")
    if issue.issue_type.strip():
        sections.append(f"Type: {issue.issue_type.strip()}")
    if issue.priority and issue.priority.strip():
        sections.append(f"Priority: {issue.priority.strip()}")
    if issue.assignee and issue.assignee.strip():
        sections.append(f"Assignee: {issue.assignee.strip()}")
    if issue.reporter and issue.reporter.strip():
        sections.append(f"Reporter: {issue.reporter.strip()}")
    if issue.labels:
        clean_labels = [lbl.strip() for lbl in issue.labels if lbl and lbl.strip()]
        if clean_labels:
            sections.append("Labels: " + ", ".join(clean_labels))
    if issue.description:
        sections.append(f"Description: {issue.description}")

    body = "\n".join(sections)
    chunk_texts = _split_body_with_overlap(
        body,
        header=header,
        counter=counter,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )

    total_parts = len(chunk_texts)
    result: list[Chunk] = []
    for ordinal, text in enumerate(chunk_texts):
        meta = dict(issue.metadata)
        meta["part_count"] = total_parts
        result.append(
            Chunk(
                kind="issue_body",
                ordinal=ordinal,
                text=text,
                token_estimate=counter(text),
                occurred_at=issue.occurred_at,
                metadata=meta,
                content_hash=compute_content_hash(text, chunker_version=ver),
                group_key=None,
            )
        )
    return result


def chunk_issue_comments(
    comments: Sequence[IssueCommentInput],
    *,
    client_name: str | None,
    project_name: str,
    issue_key: str,
    issue_summary: str,
    comments_per_group: int = DEFAULT_COMMENTS_PER_GROUP,
    counter: TokenCounter = default_token_counter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    chunker_version: int | None = None,
) -> list[Chunk]:
    """Group Jira issue comments deterministically into ~400-token chunks with author + timestamp per comment."""
    if not comments:
        return []

    ver = (
        chunker_version
        if chunker_version is not None
        else chunker_version_for_kind("issue_comment_group")
    )

    def _utc_dt(dt: datetime) -> datetime:
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    bucket_size = max(1, comments_per_group)
    header = _issue_header(client_name, project_name, issue_key, issue_summary)
    sorted_comments = sorted(
        comments,
        key=lambda c: (_utc_dt(c.created_at), str(c.comment_id)),
    )

    chunks: list[Chunk] = []
    for group_idx, start_idx in enumerate(range(0, len(sorted_comments), bucket_size)):
        group = sorted_comments[start_idx : start_idx + bucket_size]
        comment_ids = [str(c.comment_id) for c in group]
        latest_at = max(_utc_dt(c.created_at) for c in group)
        lines = [
            f"[{_utc_dt(c.created_at).isoformat()}] {c.author_name.strip() or 'Unknown'}: {c.body}"
            for c in group
        ]
        group_body = "\n".join(lines)
        full_group_text = f"{header}\n{group_body}"

        if counter(full_group_text) <= target_tokens:
            chunks.append(
                Chunk(
                    kind="issue_comment_group",
                    ordinal=group_idx * 100,
                    text=full_group_text,
                    token_estimate=counter(full_group_text),
                    occurred_at=latest_at,
                    metadata={
                        "group_index": group_idx,
                        "comment_ids": comment_ids,
                    },
                    content_hash=compute_content_hash(full_group_text, chunker_version=ver),
                    group_key=None,
                )
            )
        else:
            sub_chunks = _split_body_with_overlap(
                group_body,
                header=header,
                counter=counter,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
            )
            if len(sub_chunks) >= 100:
                raise ValueError(
                    f"Issue comment group {group_idx} requires {len(sub_chunks)} sub-chunks; "
                    "maximum supported is 99 sub-chunks per group."
                )
            for sub_idx, sub_text in enumerate(sub_chunks):
                chunks.append(
                    Chunk(
                        kind="issue_comment_group",
                        ordinal=group_idx * 100 + sub_idx,
                        text=sub_text,
                        token_estimate=counter(sub_text),
                        occurred_at=latest_at,
                        metadata={
                            "group_index": group_idx,
                            "sub_index": sub_idx,
                            "comment_ids": comment_ids,
                        },
                        content_hash=compute_content_hash(sub_text, chunker_version=ver),
                        group_key=None,
                    )
                )

    return chunks


def chunk_issue_transitions(
    transitions: Sequence[IssueTransitionInput],
    *,
    client_name: str | None,
    project_name: str,
    issue_key: str,
    issue_summary: str,
    counter: TokenCounter = default_token_counter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    chunker_version: int | None = None,
) -> list[Chunk]:
    """Build issue_transition_group chunks from status transitions in the issue changelog with author and date."""
    status_transitions = [
        t for t in transitions if t.field.strip().lower() == "status"
    ]
    if not status_transitions:
        return []

    ver = (
        chunker_version
        if chunker_version is not None
        else chunker_version_for_kind("issue_transition_group")
    )

    def _utc_dt(dt: datetime) -> datetime:
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    header = _issue_header(client_name, project_name, issue_key, issue_summary)
    sorted_transitions = sorted(
        status_transitions,
        key=lambda t: (_utc_dt(t.created_at), str(t.history_id), int(t.item_index)),
    )

    latest_at = max(_utc_dt(t.created_at) for t in sorted_transitions)
    history_ids = [f"{t.history_id}:{t.item_index}" for t in sorted_transitions]
    lines: list[str] = []
    for t in sorted_transitions:
        dt_iso = _utc_dt(t.created_at).isoformat()
        author = t.author_name.strip() or "Unknown"
        from_val = (t.from_value or "None").strip()
        to_val = (t.to_value or "None").strip()
        lines.append(f"[{dt_iso}] {author}: Status changed from '{from_val}' to '{to_val}'")

    body = "\n".join(lines)
    chunk_texts = _split_body_with_overlap(
        body,
        header=header,
        counter=counter,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )

    chunks: list[Chunk] = []
    for ordinal, text in enumerate(chunk_texts):
        chunks.append(
            Chunk(
                kind="issue_transition_group",
                ordinal=ordinal,
                text=text,
                token_estimate=counter(text),
                occurred_at=latest_at,
                metadata={
                    "issue_key": issue_key,
                    "transition_refs": history_ids,
                },
                content_hash=compute_content_hash(text, chunker_version=ver),
                group_key=None,
            )
        )
    return chunks
