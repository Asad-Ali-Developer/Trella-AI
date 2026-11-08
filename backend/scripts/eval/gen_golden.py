"""Generate 40 golden evaluation queries over synthetic benchmark data in backend/scripts/eval/golden.jsonl."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.context.models import ContextChunkRecord
from app.modules.trello.models import TrelloCard, TrelloSource
from app.modules.workspaces.models import Workspace
from scripts.bench_db import (
    assert_bench_database_isolated,
    create_bench_engine,
    create_bench_session_maker,
)
from scripts.seed_benchmark import (
    BENCH_WORKSPACE_PREFIX,
    FAKE_EMBEDDING_MODEL,
    TOPIC_KEYWORDS,
    TOPICS,
    DeterministicFakeEmbedder,
    cosine_similarity,
)

DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parent / "golden.jsonl"

PARAPHRASED_TOPIC_QUERIES: dict[str, str] = {
    "payments": "merchant checkout settlement payout refund chargeback reconciliation gateway",
    "onboarding": "enterprise signup activation wizard kyc provisioning walkthrough checklist",
    "reporting": "scheduled executive report digest csv pdf export ledger summary",
    "auth": "federated saml sso oauth pkce authentication mfa totp session passkey",
    "mobile_app": "ios android react-native mobile biometric offline push notification sync",
    "notifications": "slack email webhook alert notification quiet hours unsubscribe bounce",
    "integrations": "trello github jira connector cursor sync webhook verification",
    "analytics": "cohort retention funnel attribution telemetry warehouse clickhouse metrics",
    "security": "fernet aes encryption key rotation rbac audit log tenant isolation",
    "billing": "subscription invoice proration metering quota overage dunning plan-limit",
}


@dataclass(frozen=True)
class GoldenQueryEntry:
    """Single golden query item serialized to golden.jsonl."""

    query: str
    workspace_id: str
    client_id: str | None
    date_from: str | None
    date_to: str | None
    expected_card_ids: list[str]
    group: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "workspace_id": self.workspace_id,
            "client_id": self.client_id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "expected_card_ids": self.expected_card_ids,
            "group": self.group,
        }


def _dedupe_card_ids(card_ids: list[UUID], max_ids: int = 5) -> list[str]:
    seen: set[UUID] = set()
    ordered: list[str] = []
    for cid in card_ids:
        if cid not in seen:
            seen.add(cid)
            ordered.append(str(cid))
            if len(ordered) >= max_ids:
                break
    return ordered


async def generate_golden_queries(
    session: AsyncSession,
    *,
    seed: int = 42,
    count_per_group: int = 10,
) -> list[GoldenQueryEntry]:
    """Build 40 golden queries (10 per group: semantic, exact_identifier, client_filtered, date_filtered)."""
    embedder = DeterministicFakeEmbedder(seed=seed)

    workspaces = list(
        (
            await session.scalars(
                select(Workspace)
                .where(Workspace.name.like(f"{BENCH_WORKSPACE_PREFIX}%"))
                .order_by(Workspace.name)
            )
        ).all()
    )
    if not workspaces:
        raise RuntimeError(
            "No BENCH- workspaces found in benchmark database. Run seed_benchmark.py first."
        )

    # Load all active-source card chunks across BENCH workspaces
    ws_ids = [ws.id for ws in workspaces]
    active_source_ids = set(
        (
            await session.scalars(
                select(TrelloSource.id).where(
                    TrelloSource.workspace_id.in_(ws_ids),
                    TrelloSource.excluded.is_(False),
                )
            )
        ).all()
    )

    chunk_rows = list(
        (
            await session.scalars(
                select(ContextChunkRecord).where(
                    ContextChunkRecord.workspace_id.in_(ws_ids),
                    ContextChunkRecord.card_id.is_not(None),
                    ContextChunkRecord.source_id.in_(active_source_ids),
                    ContextChunkRecord.embedding_model == FAKE_EMBEDDING_MODEL,
                )
            )
        ).all()
    )
    if not chunk_rows:
        raise RuntimeError("No embedded card chunks found in benchmark database.")

    cards_by_id: dict[UUID, TrelloCard] = {
        c.id: c
        for c in (
            await session.scalars(
                select(TrelloCard).where(TrelloCard.workspace_id.in_(ws_ids))
            )
        ).all()
    }

    chunks_by_ws: dict[UUID, list[ContextChunkRecord]] = {ws.id: [] for ws in workspaces}
    for ch in chunk_rows:
        chunks_by_ws[ch.workspace_id].append(ch)

    entries: list[GoldenQueryEntry] = []

    # 1. Semantic group (10 queries: 1 per topic across workspaces)
    for idx in range(count_per_group):
        topic = TOPICS[idx % len(TOPICS)]
        ws = workspaces[idx % len(workspaces)]
        ws_chunks = chunks_by_ws[ws.id]
        query_text = PARAPHRASED_TOPIC_QUERIES[topic]
        q_vec = embedder.embed(query_text)

        scored = sorted(
            ws_chunks,
            key=lambda ch: cosine_similarity(q_vec, list(ch.embedding or [])),
            reverse=True,
        )
        top_cards = _dedupe_card_ids(
            [ch.card_id for ch in scored if ch.card_id is not None],
            max_ids=5,
        )
        entries.append(
            GoldenQueryEntry(
                query=query_text,
                workspace_id=str(ws.id),
                client_id=None,
                date_from=None,
                date_to=None,
                expected_card_ids=top_cards,
                group="semantic",
            )
        )

    # 2. Exact-identifier group (10 queries with exact PROJ-xxx and commit SHA / topic terms)
    body_chunks_with_proj: list[ContextChunkRecord] = [
        ch
        for ch in chunk_rows
        if ch.chunk_kind == "card_body"
        and ch.ordinal == 0
        and ch.card_id is not None
        and isinstance(ch.chunk_metadata, dict)
        and ch.chunk_metadata.get("proj_code")
    ]
    body_chunks_with_proj.sort(key=lambda ch: str(ch.chunk_metadata.get("proj_code", "")))
    step = max(1, len(body_chunks_with_proj) // count_per_group)
    for idx in range(count_per_group):
        target_ch = body_chunks_with_proj[(idx * step) % len(body_chunks_with_proj)]
        assert target_ch.card_id is not None
        proj_code = str(target_ch.chunk_metadata["proj_code"])
        sha_ref = str(target_ch.chunk_metadata.get("commit_sha_ref") or "")
        topic = str(target_ch.chunk_metadata.get("topic") or TOPICS[idx % len(TOPICS)])
        kw = TOPIC_KEYWORDS.get(topic, ("issue",))[0]
        # Note: in websearch_to_tsquery, a leading hyphen (e.g. PROJ-101) is parsed as negation
        # unless quoted or present in card text without negation; only include sha_ref if present in chunk text.
        parts = [f'"{proj_code}"']
        if sha_ref and sha_ref in target_ch.text:
            parts.append(sha_ref)
        if topic in target_ch.text.lower():
            parts.append(topic)
        if kw in target_ch.text.lower():
            parts.append(kw)
        query_text = " ".join(parts)
        entries.append(
            GoldenQueryEntry(
                query=query_text,
                workspace_id=str(target_ch.workspace_id),
                client_id=None,
                date_from=None,
                date_to=None,
                expected_card_ids=[str(target_ch.card_id)],
                group="exact_identifier",
            )
        )

    # 3. Client-filtered group (10 queries scoped to a specific client_id + topic)
    for idx in range(count_per_group):
        ws = workspaces[idx % len(workspaces)]
        ws_chunks = chunks_by_ws[ws.id]
        # Group chunks by (client_id, topic)
        by_client_topic: dict[tuple[UUID, str], list[ContextChunkRecord]] = {}
        for ch in ws_chunks:
            if ch.client_id is None or ch.card_id is None:
                continue
            ch_topic = str((ch.chunk_metadata or {}).get("topic") or "")
            if ch_topic in TOPICS:
                by_client_topic.setdefault((ch.client_id, ch_topic), []).append(ch)

        candidates = sorted(
            by_client_topic.items(),
            key=lambda item: (str(item[0][0]), item[0][1]),
        )
        (target_client_id, topic), matching_chunks = candidates[idx % len(candidates)]
        query_text = PARAPHRASED_TOPIC_QUERIES[topic]
        q_vec = embedder.embed(query_text)

        client_chunks = [ch for ch in ws_chunks if ch.client_id == target_client_id]
        scored = sorted(
            client_chunks,
            key=lambda ch: cosine_similarity(q_vec, list(ch.embedding or [])),
            reverse=True,
        )
        top_cards = _dedupe_card_ids(
            [ch.card_id for ch in scored if ch.card_id is not None],
            max_ids=5,
        )
        if not top_cards and matching_chunks:
            top_cards = _dedupe_card_ids(
                [ch.card_id for ch in matching_chunks if ch.card_id is not None],
                max_ids=5,
            )
        entries.append(
            GoldenQueryEntry(
                query=query_text,
                workspace_id=str(ws.id),
                client_id=str(target_client_id),
                date_from=None,
                date_to=None,
                expected_card_ids=top_cards,
                group="client_filtered",
            )
        )

    # 4. Date-filtered group (10 queries scoped to a date_from..date_to window + topic)
    for idx in range(count_per_group):
        ws = workspaces[idx % len(workspaces)]
        topic = TOPICS[idx % len(TOPICS)]
        ws_chunks = [
            ch
            for ch in chunks_by_ws[ws.id]
            if ch.occurred_at is not None and ch.card_id is not None
        ]
        topic_chunks = [
            ch
            for ch in ws_chunks
            if (ch.chunk_metadata or {}).get("topic") == topic
        ]
        anchor_chunk = topic_chunks[idx % len(topic_chunks)] if topic_chunks else ws_chunks[0]
        assert anchor_chunk.occurred_at is not None
        anchor_dt: datetime = anchor_chunk.occurred_at
        date_from_dt = anchor_dt - timedelta(days=7)
        date_to_dt = anchor_dt + timedelta(days=7)

        query_text = PARAPHRASED_TOPIC_QUERIES[topic]
        q_vec = embedder.embed(query_text)

        in_window = [
            ch
            for ch in ws_chunks
            if ch.occurred_at is not None and date_from_dt <= ch.occurred_at <= date_to_dt
        ]
        scored = sorted(
            in_window,
            key=lambda ch: cosine_similarity(q_vec, list(ch.embedding or [])),
            reverse=True,
        )
        top_cards = _dedupe_card_ids(
            [ch.card_id for ch in scored if ch.card_id is not None and ch.card_id in cards_by_id],
            max_ids=5,
        )
        entries.append(
            GoldenQueryEntry(
                query=query_text,
                workspace_id=str(ws.id),
                client_id=None,
                date_from=date_from_dt.isoformat(),
                date_to=date_to_dt.isoformat(),
                expected_card_ids=top_cards,
                group="date_filtered",
            )
        )

    return entries


def write_golden_jsonl(
    entries: list[GoldenQueryEntry],
    output_path: Path = DEFAULT_GOLDEN_PATH,
) -> Path:
    """Write golden query entries to a JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry.to_dict(), sort_keys=False) + "\n")
    return output_path


def load_golden_jsonl(path: Path = DEFAULT_GOLDEN_PATH) -> list[GoldenQueryEntry]:
    """Load golden query entries from a JSONL file."""
    entries: list[GoldenQueryEntry] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            entries.append(
                GoldenQueryEntry(
                    query=str(raw["query"]),
                    workspace_id=str(raw["workspace_id"]),
                    client_id=str(raw["client_id"]) if raw.get("client_id") is not None else None,
                    date_from=str(raw["date_from"]) if raw.get("date_from") is not None else None,
                    date_to=str(raw["date_to"]) if raw.get("date_to") is not None else None,
                    expected_card_ids=[str(cid) for cid in raw.get("expected_card_ids", [])],
                    group=str(raw.get("group", "semantic")),
                )
            )
    return entries


async def run_gen_golden(
    *,
    seed: int = 42,
    output_path: Path = DEFAULT_GOLDEN_PATH,
    bench_url: str | None = None,
) -> list[GoldenQueryEntry]:
    """Connect to the isolated benchmark DB, generate 40 golden queries, and write golden.jsonl."""
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    engine = create_bench_engine(isolated_url)
    session_maker = create_bench_session_maker(engine)
    try:
        async with session_maker() as session:
            entries = await generate_golden_queries(session, seed=seed)
    finally:
        await engine.dispose()

    write_golden_jsonl(entries, output_path=output_path)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate 40 golden retrieval queries in backend/scripts/eval/golden.jsonl."
    )
    parser.add_argument("--seed", type=int, default=42, help="Seed used during seed_benchmark.py (default: 42)")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_GOLDEN_PATH,
        help="Output JSONL file path (default: backend/scripts/eval/golden.jsonl)",
    )
    parser.add_argument("--db-url", default=None, help="Optional BENCH_DATABASE_URL override.")
    args = parser.parse_args()

    entries = asyncio.run(
        run_gen_golden(seed=args.seed, output_path=args.output, bench_url=args.db_url)
    )
    print(f"Wrote {len(entries)} golden queries to {args.output}")


if __name__ == "__main__":
    main()
