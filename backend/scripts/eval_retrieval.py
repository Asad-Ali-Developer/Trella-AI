"""Retrieval evaluation harness, Retriever protocol, and pure-SQL baseline retrievers."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Select, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.context.models import EMBEDDING_DIMENSIONS, ContextChunkRecord
from app.modules.context.retriever import HybridRetriever
from app.modules.github.models import GithubRepository
from app.modules.trello.models import TrelloSource
from scripts.bench_db import (
    assert_bench_database_isolated,
    create_bench_engine,
    create_bench_session_maker,
)
from scripts.eval.gen_golden import DEFAULT_GOLDEN_PATH, GoldenQueryEntry, load_golden_jsonl
from scripts.seed_benchmark import FAKE_EMBEDDING_MODEL, DeterministicFakeEmbedder

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent / "eval" / "reports"
IterativeScanMode = Literal["off", "relaxed_order", "strict_order"]


@dataclass(frozen=True)
class RetrievedChunk:
    """Single retrieved chunk row with score and parent identifiers."""

    chunk_id: UUID
    card_id: UUID | None
    repository_id: UUID | None
    source_id: UUID | None
    client_id: UUID | None
    chunk_kind: str
    ordinal: int
    score: float
    text: str


@runtime_checkable
class Retriever(Protocol):
    """Protocol for chunk retrievers evaluated by the benchmark harness."""

    async def search(
        self,
        *,
        workspace_id: UUID,
        query: str,
        client_id: UUID | None = None,
        source_ids: Sequence[UUID] | None = None,
        repository_ids: Sequence[UUID] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        """Search workspace chunks matching filters and return up to `limit` results."""
        ...


def _apply_common_chunk_filters[*Ts](
    stmt: Select[*Ts],
    *,
    workspace_id: UUID,
    client_id: UUID | None,
    source_ids: Sequence[UUID] | None,
    repository_ids: Sequence[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select[*Ts]:
    """Apply workspace, active-source, client, and date filters in the same SQL statement."""
    stmt = (
        stmt.outerjoin(
            TrelloSource,
            (TrelloSource.id == ContextChunkRecord.source_id)
            & (TrelloSource.workspace_id == workspace_id),
        )
        .outerjoin(
            GithubRepository,
            (GithubRepository.id == ContextChunkRecord.repository_id)
            & (GithubRepository.workspace_id == workspace_id),
        )
        .where(
            ContextChunkRecord.workspace_id == workspace_id,
            or_(
                (ContextChunkRecord.source_id.is_not(None)) & (TrelloSource.excluded.is_(False)),
                (ContextChunkRecord.repository_id.is_not(None))
                & (GithubRepository.included.is_(True)),
            ),
        )
    )

    if source_ids is not None or repository_ids is not None:
        branch_clauses = []
        if source_ids:
            branch_clauses.append(ContextChunkRecord.source_id.in_(list(source_ids)))
        if repository_ids:
            branch_clauses.append(ContextChunkRecord.repository_id.in_(list(repository_ids)))
        if branch_clauses:
            stmt = stmt.where(or_(*branch_clauses))
        else:
            stmt = stmt.where(text("FALSE"))

    if client_id is not None:
        stmt = stmt.where(ContextChunkRecord.client_id == client_id)
    if date_from is not None:
        stmt = stmt.where(ContextChunkRecord.occurred_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(ContextChunkRecord.occurred_at <= date_to)

    return stmt


class VectorOnlyRetriever:
    """Pure-SQL halfvec cosine baseline retriever over `chunks` with configurable HNSW settings."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        embedder: DeterministicFakeEmbedder | None = None,
        embedding_model: str = FAKE_EMBEDDING_MODEL,
        ef_search: int = 100,
        iterative_scan: IterativeScanMode | None = "relaxed_order",
    ) -> None:
        self.session = session
        self.embedder = embedder or DeterministicFakeEmbedder()
        self.embedding_model = embedding_model
        self.ef_search = int(ef_search)
        self.iterative_scan = iterative_scan
        self.last_db_latency_ms: float = 0.0

    async def search(
        self,
        *,
        workspace_id: UUID,
        query: str,
        client_id: UUID | None = None,
        source_ids: Sequence[UUID] | None = None,
        repository_ids: Sequence[UUID] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        query_vec = [round(float(x), 5) for x in self.embedder.embed(query)]
        halfvec_param = cast(query_vec, HALFVEC(EMBEDDING_DIMENSIONS))
        distance_expr = ContextChunkRecord.embedding.cosine_distance(halfvec_param)

        stmt = select(
            ContextChunkRecord.id,
            ContextChunkRecord.card_id,
            ContextChunkRecord.repository_id,
            ContextChunkRecord.source_id,
            ContextChunkRecord.client_id,
            ContextChunkRecord.chunk_kind,
            ContextChunkRecord.ordinal,
            ContextChunkRecord.text,
            distance_expr.label("distance"),
        ).where(
            ContextChunkRecord.embedding.is_not(None),
            ContextChunkRecord.embedding_model == self.embedding_model,
        )

        stmt = _apply_common_chunk_filters(
            stmt,
            workspace_id=workspace_id,
            client_id=client_id,
            source_ids=source_ids,
            repository_ids=repository_ids,
            date_from=date_from,
            date_to=date_to,
        )
        stmt = stmt.order_by(distance_expr).limit(limit)

        t0 = time.perf_counter()
        async with self.session.begin_nested():
            await self.session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self.ef_search)}"))
            if self.iterative_scan is not None:
                if self.iterative_scan not in ("off", "relaxed_order", "strict_order"):
                    raise ValueError(f"Unsupported iterative_scan mode: {self.iterative_scan!r}")
                await self.session.execute(
                    text(f"SET LOCAL hnsw.iterative_scan = {self.iterative_scan}")
                )
            t_exec_start = time.perf_counter()
            result_proxy = await self.session.execute(stmt)
            t_exec_end = time.perf_counter()
            rows = result_proxy.all()
        t1 = time.perf_counter()
        self.last_db_exec_ms = (t_exec_end - t_exec_start) * 1000.0
        self.last_db_latency_ms = (t1 - t0) * 1000.0

        return [
            RetrievedChunk(
                chunk_id=row.id,
                card_id=row.card_id,
                repository_id=row.repository_id,
                source_id=row.source_id,
                client_id=row.client_id,
                chunk_kind=row.chunk_kind,
                ordinal=row.ordinal,
                score=float(1.0 - float(row.distance)),
                text=row.text,
            )
            for row in rows
        ]


class KeywordOnlyRetriever:
    """Pure-SQL full-text search baseline using `websearch_to_tsquery('simple', ...)` and `ts_rank_cd`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.last_db_latency_ms: float = 0.0

    async def search(
        self,
        *,
        workspace_id: UUID,
        query: str,
        client_id: UUID | None = None,
        source_ids: Sequence[UUID] | None = None,
        repository_ids: Sequence[UUID] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        ts_query = func.websearch_to_tsquery("simple", query)
        rank_expr = func.ts_rank_cd(ContextChunkRecord.tsv, ts_query)

        stmt = select(
            ContextChunkRecord.id,
            ContextChunkRecord.card_id,
            ContextChunkRecord.repository_id,
            ContextChunkRecord.source_id,
            ContextChunkRecord.client_id,
            ContextChunkRecord.chunk_kind,
            ContextChunkRecord.ordinal,
            ContextChunkRecord.text,
            rank_expr.label("rank"),
        ).where(
            ContextChunkRecord.tsv.op("@@")(ts_query),
        )

        stmt = _apply_common_chunk_filters(
            stmt,
            workspace_id=workspace_id,
            client_id=client_id,
            source_ids=source_ids,
            repository_ids=repository_ids,
            date_from=date_from,
            date_to=date_to,
        )
        stmt = stmt.order_by(rank_expr.desc(), ContextChunkRecord.id).limit(limit)

        t0 = time.perf_counter()
        result_proxy = await self.session.execute(stmt)
        t_exec = time.perf_counter()
        rows = result_proxy.all()
        t1 = time.perf_counter()
        self.last_db_exec_ms = (t_exec - t0) * 1000.0
        self.last_db_latency_ms = (t1 - t0) * 1000.0

        return [
            RetrievedChunk(
                chunk_id=row.id,
                card_id=row.card_id,
                repository_id=row.repository_id,
                source_id=row.source_id,
                client_id=row.client_id,
                chunk_kind=row.chunk_kind,
                ordinal=row.ordinal,
                score=float(row.rank),
                text=row.text,
            )
            for row in rows
        ]


def deduplicate_ranked_card_ids(chunks: Sequence[Any]) -> list[str]:
    """Extract unique card_ids from retrieved chunks while preserving rank order."""
    seen: set[str] = set()
    ranked: list[str] = []
    for ch in chunks:
        if ch.card_id is None:
            continue
        cid = str(ch.card_id)
        if cid not in seen:
            seen.add(cid)
            ranked.append(cid)
    return ranked


def compute_recall_at_k(
    retrieved_card_ids: Sequence[str],
    expected_card_ids: Sequence[str],
    k: int,
) -> float:
    """Compute Recall@k = |retrieved[:k] ∩ expected| / |expected|."""
    if k <= 0:
        return 0.0
    expected_set = {str(cid) for cid in expected_card_ids if cid}
    if not expected_set:
        return 1.0
    top_k_set = {str(cid) for cid in retrieved_card_ids[:k]}
    hits = len(expected_set & top_k_set)
    return float(hits / len(expected_set))


def compute_mrr(
    retrieved_card_ids: Sequence[str],
    expected_card_ids: Sequence[str],
) -> float:
    """Compute Reciprocal Rank (1 / rank of first expected card in `retrieved_card_ids`, or 0.0)."""
    expected_set = {str(cid) for cid in expected_card_ids if cid}
    if not expected_set:
        return 0.0
    for idx, cid in enumerate(retrieved_card_ids, start=1):
        if str(cid) in expected_set:
            return float(1.0 / idx)
    return 0.0


def compute_percentile(values: Sequence[float], percentile: float) -> float:
    """Compute linear-interpolated percentile (e.g. 50.0 or 95.0) over `values`."""
    if not values:
        return 0.0
    sorted_vals = sorted(float(v) for v in values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (max(0.0, min(100.0, percentile)) / 100.0) * (len(sorted_vals) - 1)
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return sorted_vals[lower]
    weight = pos - lower
    return float(sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight)


@dataclass(frozen=True)
class GroupMetrics:
    """Aggregated evaluation metrics for a query group or overall."""

    count: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    p50_ms: float
    p95_ms: float
    p50_exec_ms: float = 0.0
    p95_exec_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "recall_at_5": round(self.recall_at_5, 4),
            "recall_at_10": round(self.recall_at_10, 4),
            "mrr": round(self.mrr, 4),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p50_exec_ms": round(self.p50_exec_ms, 3),
            "p95_exec_ms": round(self.p95_exec_ms, 3),
        }


def aggregate_query_records(records: Sequence[dict[str, Any]]) -> GroupMetrics:
    """Aggregate per-query metric records into a GroupMetrics summary."""
    if not records:
        return GroupMetrics(
            count=0,
            recall_at_5=0.0,
            recall_at_10=0.0,
            mrr=0.0,
            p50_ms=0.0,
            p95_ms=0.0,
            p50_exec_ms=0.0,
            p95_exec_ms=0.0,
        )
    n = len(records)
    r5 = sum(float(r["recall_at_5"]) for r in records) / n
    r10 = sum(float(r["recall_at_10"]) for r in records) / n
    mrr = sum(float(r["mrr"]) for r in records) / n
    latencies = [float(r["latency_ms"]) for r in records]
    exec_latencies = [float(r.get("db_exec_ms", r["latency_ms"])) for r in records]
    return GroupMetrics(
        count=n,
        recall_at_5=r5,
        recall_at_10=r10,
        mrr=mrr,
        p50_ms=compute_percentile(latencies, 50.0),
        p95_ms=compute_percentile(latencies, 95.0),
        p50_exec_ms=compute_percentile(exec_latencies, 50.0),
        p95_exec_ms=compute_percentile(exec_latencies, 95.0),
    )


async def evaluate_retriever(
    retriever: Retriever | HybridRetriever,
    golden_entries: Sequence[GoldenQueryEntry],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Run all golden queries against `retriever` and return per-group and overall metrics."""
    per_query: list[dict[str, Any]] = []
    by_group: dict[str, list[dict[str, Any]]] = {}

    for entry in golden_entries:
        ws_id = UUID(entry.workspace_id)
        client_id = UUID(entry.client_id) if entry.client_id else None
        date_from = datetime.fromisoformat(entry.date_from) if entry.date_from else None
        date_to = datetime.fromisoformat(entry.date_to) if entry.date_to else None

        t0 = time.perf_counter()
        chunks = await retriever.search(
            workspace_id=ws_id,
            query=entry.query,
            client_id=client_id,
            source_ids=None,
            repository_ids=None,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        wall_ms = (time.perf_counter() - t0) * 1000.0
        db_ms = float(getattr(retriever, "last_db_latency_ms", wall_ms) or wall_ms)
        db_exec_ms = float(getattr(retriever, "last_db_exec_ms", db_ms) or db_ms)

        ranked_cards = deduplicate_ranked_card_ids(chunks)
        r5 = compute_recall_at_k(ranked_cards, entry.expected_card_ids, 5)
        r10 = compute_recall_at_k(ranked_cards, entry.expected_card_ids, 10)
        mrr = compute_mrr(ranked_cards, entry.expected_card_ids)

        rec = {
            "group": entry.group,
            "query": entry.query,
            "workspace_id": entry.workspace_id,
            "client_id": entry.client_id,
            "expected_card_ids": entry.expected_card_ids,
            "retrieved_card_ids_top10": ranked_cards[:10],
            "recall_at_5": r5,
            "recall_at_10": r10,
            "mrr": mrr,
            "latency_ms": db_ms,
            "db_exec_ms": db_exec_ms,
            "wall_ms": wall_ms,
        }
        per_query.append(rec)
        by_group.setdefault(entry.group, []).append(rec)

    group_summaries = {
        grp: aggregate_query_records(recs).to_dict() for grp, recs in by_group.items()
    }
    overall_summary = aggregate_query_records(per_query).to_dict()

    return {
        "overall": overall_summary,
        "groups": group_summaries,
        "queries": per_query,
    }


async def evaluate_tsquery_comparison(
    session: AsyncSession,
    golden_entries: Sequence[GoldenQueryEntry],
) -> dict[str, Any]:
    """Evaluate plainto_tsquery (AND) vs websearch_to_tsquery (OR) for candidate CTE execution times."""
    conn = await session.connection()
    driver = (await conn.get_raw_connection()).driver_connection

    nl_entries = [
        e for e in golden_entries if e.group in ("semantic", "client_filtered", "date_filtered")
    ]
    id_entries = [e for e in golden_entries if e.group == "exact_identifier"]

    plain_times: list[float] = []
    plain_counts: list[int] = []
    or_times: list[float] = []
    or_counts: list[int] = []
    id_times: list[float] = []
    id_counts: list[int] = []

    for entry in nl_entries:
        ws_id = UUID(entry.workspace_id)
        q = entry.query
        q_or = " or ".join(q.split())

        t0 = time.perf_counter()
        rows_plain = await driver.fetch(
            """
            SELECT id FROM (
                SELECT id, tsv, ts_q FROM chunks, plainto_tsquery('simple', $2) AS ts_q
                WHERE workspace_id = $1 AND tsv @@ ts_q
                ORDER BY occurred_at DESC NULLS LAST, id DESC LIMIT 300
            ) pre ORDER BY ts_rank_cd(tsv, ts_q) DESC LIMIT 50
            """,
            ws_id,
            q,
        )
        plain_times.append((time.perf_counter() - t0) * 1000.0)
        plain_counts.append(len(rows_plain))

        t0 = time.perf_counter()
        rows_or = await driver.fetch(
            """
            SELECT id FROM (
                SELECT id, tsv, ts_q FROM chunks, websearch_to_tsquery('simple', $2) AS ts_q
                WHERE workspace_id = $1 AND tsv @@ ts_q
                ORDER BY occurred_at DESC NULLS LAST, id DESC LIMIT 300
            ) pre ORDER BY ts_rank_cd(tsv, ts_q) DESC LIMIT 50
            """,
            ws_id,
            q_or,
        )
        or_times.append((time.perf_counter() - t0) * 1000.0)
        or_counts.append(len(rows_or))

    for entry in id_entries:
        ws_id = UUID(entry.workspace_id)
        q = entry.query
        t0 = time.perf_counter()
        rows_id = await driver.fetch(
            """
            SELECT id FROM (
                SELECT id, tsv, ts_q FROM chunks, websearch_to_tsquery('simple', $2) AS ts_q
                WHERE workspace_id = $1 AND tsv @@ ts_q
                ORDER BY occurred_at DESC NULLS LAST, id DESC LIMIT 300
            ) pre ORDER BY ts_rank_cd(tsv, ts_q) DESC LIMIT 50
            """,
            ws_id,
            q,
        )
        id_times.append((time.perf_counter() - t0) * 1000.0)
        id_counts.append(len(rows_id))

    return {
        "plainto_and": {
            "p50_ms": compute_percentile(plain_times, 50.0),
            "p95_ms": compute_percentile(plain_times, 95.0),
            "avg_matches": (
                round(sum(plain_counts) / len(plain_counts), 1) if plain_counts else 0.0
            ),
        },
        "websearch_or": {
            "p50_ms": compute_percentile(or_times, 50.0),
            "p95_ms": compute_percentile(or_times, 95.0),
            "avg_matches": (
                round(sum(or_counts) / len(or_counts), 1) if or_counts else 0.0
            ),
        },
        "websearch_exact_id": {
            "p50_ms": compute_percentile(id_times, 50.0),
            "p95_ms": compute_percentile(id_times, 95.0),
            "avg_matches": (
                round(sum(id_counts) / len(id_counts), 1) if id_counts else 0.0
            ),
        },
    }


def _print_eval_table(retriever_name: str, report: dict[str, Any]) -> None:
    print(f"\n=== {retriever_name} ===")
    header = (
        f"{'Group':<20} | {'Count':>5} | {'Recall@5':>8} | {'Recall@10':>9} | {'MRR':>8} | "
        f"{'db_ms p50':>9} | {'exec_ms p50':>11} | {'p95 (ms)':>8}"
    )
    print(header)
    print("-" * len(header))
    for grp, metrics in report["groups"].items():
        print(
            f"{grp:<20} | {metrics['count']:>5d} | {metrics['recall_at_5']:>8.4f} | "
            f"{metrics['recall_at_10']:>9.4f} | {metrics['mrr']:>8.4f} | "
            f"{metrics['p50_ms']:>9.2f} | {metrics.get('p50_exec_ms', metrics['p50_ms']):>11.2f} | "
            f"{metrics['p95_ms']:>8.2f}"
        )
    print("-" * len(header))
    ov = report["overall"]
    print(
        f"{'OVERALL':<20} | {ov['count']:>5d} | {ov['recall_at_5']:>8.4f} | "
        f"{ov['recall_at_10']:>9.4f} | {ov['mrr']:>8.4f} | "
        f"{ov['p50_ms']:>9.2f} | {ov.get('p50_exec_ms', ov['p50_ms']):>11.2f} | "
        f"{ov['p95_ms']:>8.2f}"
    )


async def run_evaluation(
    *,
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    seed: int = 42,
    ef_search: int = 40,
    iterative_scan: IterativeScanMode | None = "relaxed_order",
    bench_url: str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run VectorOnlyRetriever, KeywordOnlyRetriever, and HybridRetriever on the golden set and write a JSON report."""
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    golden_entries = load_golden_jsonl(golden_path)
    if not golden_entries:
        raise RuntimeError(f"Golden set at {golden_path} is empty.")

    engine = create_bench_engine(isolated_url)
    session_maker = create_bench_session_maker(engine)
    try:
        async with session_maker() as session:
            embedder = DeterministicFakeEmbedder(seed=seed)
            vector_retriever = VectorOnlyRetriever(
                session,
                embedder=embedder,
                ef_search=ef_search,
                iterative_scan=iterative_scan,
            )
            keyword_retriever = KeywordOnlyRetriever(session)

            # Warmup queries so connection setup is not counted in p50/p95
            first_ws = UUID(golden_entries[0].workspace_id)
            await vector_retriever.search(workspace_id=first_ws, query="warmup", limit=5)
            await keyword_retriever.search(workspace_id=first_ws, query="warmup", limit=5)

            vector_report = await evaluate_retriever(vector_retriever, golden_entries)
            keyword_report = await evaluate_retriever(keyword_retriever, golden_entries)

            # Evaluate HybridRetriever with weighted RRF across weights [0.3, 0.5, 1.0]
            hybrid_reports: dict[float, dict[str, Any]] = {}
            for kw_weight in [0.3, 0.5, 1.0]:
                hybrid_ret = HybridRetriever(
                    session,
                    embedder=embedder,
                    embedding_model=FAKE_EMBEDDING_MODEL,
                    ef_search=ef_search,
                    iterative_scan=iterative_scan,
                    candidate_pool_limit=15,
                    vector_weight=1.0,
                    keyword_weight=kw_weight,
                )
                await hybrid_ret.search(workspace_id=first_ws, query="warmup", limit=5)
                report = await evaluate_retriever(hybrid_ret, golden_entries)
                hybrid_reports[kw_weight] = report

            # Evaluate natural-language queries: plainto_tsquery (AND) vs websearch_to_tsquery (OR)
            tsquery_comp = await evaluate_tsquery_comparison(session, golden_entries)
    finally:
        await engine.dispose()

    _print_eval_table(
        f"VectorOnlyRetriever (ef_search={ef_search}, iterative_scan={iterative_scan})",
        vector_report,
    )
    _print_eval_table("KeywordOnlyRetriever (simple FTS + ts_rank_cd)", keyword_report)
    for kw_weight in [0.3, 0.5, 1.0]:
        _print_eval_table(
            f"HybridRetriever (vector_weight=1.0, keyword_weight={kw_weight}, ef_search={ef_search})",
            hybrid_reports[kw_weight],
        )

    print("\n=== Keyword CTE Strategy Comparison (Target < 8 ms) ===")
    print(
        f"{'Strategy':<30} | {'Match Mode':<12} | {'CTE p50 (ms)':>12} | {'CTE p95 (ms)':>12} | {'Avg Matches':>11}"
    )
    print("-" * 87)
    p_and = tsquery_comp["plainto_and"]
    print(
        f"{'plainto_tsquery (NL queries)':<30} | {'AND':<12} | {p_and['p50_ms']:>12.2f} | {p_and['p95_ms']:>12.2f} | {p_and['avg_matches']:>11.1f}"
    )
    w_or = tsquery_comp["websearch_or"]
    print(
        f"{'websearch_to_tsquery (NL)':<30} | {'OR':<12} | {w_or['p50_ms']:>12.2f} | {w_or['p95_ms']:>12.2f} | {w_or['avg_matches']:>11.1f}"
    )
    w_id = tsquery_comp["websearch_exact_id"]
    print(
        f"{'websearch_to_tsquery (Exact)':<30} | {'Identifiers':<12} | {w_id['p50_ms']:>12.2f} | {w_id['p95_ms']:>12.2f} | {w_id['avg_matches']:>11.1f}"
    )

    now_utc = datetime.now(UTC)
    timestamp_slug = now_utc.strftime("%Y%m%dT%H%M%SZ")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{timestamp_slug}.json"

    full_payload: dict[str, Any] = {
        "generated_at": now_utc.isoformat(),
        "golden_path": str(golden_path),
        "golden_count": len(golden_entries),
        "config": {
            "seed": seed,
            "embedding_model": FAKE_EMBEDDING_MODEL,
            "ef_search": ef_search,
            "iterative_scan": iterative_scan,
        },
        "retrievers": {
            "VectorOnlyRetriever": vector_report,
            "KeywordOnlyRetriever": keyword_report,
            "HybridRetriever_w0.3": hybrid_reports[0.3],
            "HybridRetriever_w0.5": hybrid_reports[0.5],
            "HybridRetriever_w1.0": hybrid_reports[1.0],
            "tsquery_comparison": tsquery_comp,
        },
    }
    report_path.write_text(json.dumps(full_payload, indent=2), encoding="utf-8")
    print(f"\nSaved JSON evaluation report to {report_path}")
    return full_payload, report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate VectorOnlyRetriever and KeywordOnlyRetriever against golden.jsonl."
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=DEFAULT_GOLDEN_PATH,
        help="Path to golden.jsonl (default: backend/scripts/eval/golden.jsonl)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help="Directory for JSON reports (default: backend/scripts/eval/reports)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Embedder seed (default: 42)")
    parser.add_argument("--ef-search", type=int, default=40, help="HNSW ef_search (default: 40)")
    parser.add_argument(
        "--iterative-scan",
        choices=["off", "relaxed_order", "strict_order"],
        default="relaxed_order",
        help="HNSW iterative_scan mode (default: relaxed_order)",
    )
    parser.add_argument("--db-url", default=None, help="Optional BENCH_DATABASE_URL override.")
    args = parser.parse_args()

    asyncio.run(
        run_evaluation(
            golden_path=args.golden,
            reports_dir=args.reports_dir,
            seed=args.seed,
            ef_search=args.ef_search,
            iterative_scan=args.iterative_scan,
            bench_url=args.db_url,
        )
    )


if __name__ == "__main__":
    main()

