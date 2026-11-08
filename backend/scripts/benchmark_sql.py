"""EXPLAIN (ANALYZE, BUFFERS) benchmark matrix for pgvector halfvec cosine search on `chunks`."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.context.models import ContextChunkRecord
from app.modules.workspaces.models import Workspace
from scripts.bench_db import (
    assert_bench_database_isolated,
    create_bench_engine,
    create_bench_session_maker,
)
from scripts.seed_benchmark import (
    BENCH_WORKSPACE_PREFIX,
    FAKE_EMBEDDING_MODEL,
    DeterministicFakeEmbedder,
)

HNSW_INDEX_NAME = "ix_chunks_embedding_halfvec_cosine"


@dataclass(frozen=True)
class BenchmarkScenarioResult:
    """Parsed EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) metrics for one SQL benchmark scenario."""

    label: str
    index_mode: str
    ef_search: int | None
    iterative_scan: str | None
    client_filtered: bool
    plan_type: str
    execution_ms: float
    buffers_hit: int
    buffers_read: int
    rows_returned: int
    rows_requested: int


def _collect_plan_summary(plan_node: dict[str, Any]) -> tuple[list[str], int, int]:
    """Recursively collect node types/index names and sum shared buffer hits/reads across the plan tree."""
    node_type = str(plan_node.get("Node Type", "Unknown"))
    index_name = plan_node.get("Index Name")
    label = f"{node_type} ({index_name})" if index_name else node_type

    labels = [label]
    hit = int(plan_node.get("Shared Hit Blocks", 0) or 0)
    read = int(plan_node.get("Shared Read Blocks", 0) or 0)

    for child in plan_node.get("Plans", []) or []:
        if isinstance(child, dict):
            child_labels, child_hit, child_read = _collect_plan_summary(child)
            labels.extend(child_labels)
        else:
            child_hit, child_read = 0, 0
        # Note: in PostgreSQL EXPLAIN (BUFFERS, FORMAT JSON), parent nodes include
        # cumulative child buffer counts, so only take root Shared Hit/Read Blocks!
        del child_hit, child_read

    return labels, hit, read


def parse_explain_json(
    explain_payload: list[dict[str, Any]],
    *,
    label: str,
    index_mode: str,
    ef_search: int | None,
    iterative_scan: str | None,
    client_filtered: bool,
    rows_requested: int,
) -> BenchmarkScenarioResult:
    """Extract plan type, execution time, buffer hits/reads, and actual rows from EXPLAIN JSON."""
    top = explain_payload[0]
    root_plan: dict[str, Any] = top.get("Plan", {})
    execution_ms = float(top.get("Execution Time", 0.0) or 0.0)
    rows_returned = int(root_plan.get("Actual Rows", 0) or 0)

    labels, root_hit, root_read = _collect_plan_summary(root_plan)
    # Identify primary scan method (HNSW index scan vs Seq Scan / other index scan)
    hnsw_nodes = [lbl for lbl in labels if HNSW_INDEX_NAME in lbl]
    seq_nodes = [lbl for lbl in labels if "Seq Scan" in lbl]
    if hnsw_nodes:
        plan_type = hnsw_nodes[0]
    elif seq_nodes:
        plan_type = f"{root_plan.get('Node Type', 'Limit')} -> {seq_nodes[0]}"
    else:
        plan_type = " -> ".join(labels[:2])

    return BenchmarkScenarioResult(
        label=label,
        index_mode=index_mode,
        ef_search=ef_search,
        iterative_scan=iterative_scan,
        client_filtered=client_filtered,
        plan_type=plan_type,
        execution_ms=execution_ms,
        buffers_hit=root_hit,
        buffers_read=root_read,
        rows_returned=rows_returned,
        rows_requested=rows_requested,
    )


async def _run_single_explain(
    session: AsyncSession,
    *,
    label: str,
    index_mode: Literal["exact", "hnsw"],
    ef_search: int | None,
    iterative_scan: Literal["off", "relaxed_order"] | None,
    workspace_id: UUID,
    client_id: UUID | None,
    query_vector_literal: str,
    embedding_model: str,
    limit: int,
) -> BenchmarkScenarioResult:
    client_clause = "AND c.client_id = :client_id" if client_id is not None else ""
    explain_sql = text(
        f"""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT c.id, c.card_id, (c.embedding <=> CAST(:qvec AS halfvec(768))) AS distance
        FROM chunks c
        LEFT JOIN sources s
          ON s.id = c.source_id AND s.workspace_id = :workspace_id
        LEFT JOIN github_repositories r
          ON r.id = c.repository_id AND r.workspace_id = :workspace_id
        WHERE c.workspace_id = :workspace_id
          AND c.embedding IS NOT NULL
          AND c.embedding_model = :embedding_model
          AND (
              (c.source_id IS NOT NULL AND s.excluded = false)
              OR (c.repository_id IS NOT NULL AND r.included = true)
          )
          {client_clause}
        ORDER BY c.embedding <=> CAST(:qvec AS halfvec(768))
        LIMIT :limit
        """
    )

    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "qvec": query_vector_literal,
        "embedding_model": embedding_model,
        "limit": limit,
    }
    if client_id is not None:
        params["client_id"] = client_id

    if index_mode == "exact":
        await session.execute(text(f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME}"))
    else:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        await session.execute(text("SET LOCAL enable_sort = off"))
        if ef_search is not None:
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
        if iterative_scan is not None:
            await session.execute(text(f"SET LOCAL hnsw.iterative_scan = {iterative_scan}"))

    raw_result = (await session.execute(explain_sql, params)).scalar_one()
    explain_payload: list[dict[str, Any]] = (
        json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    )
    await session.rollback()

    return parse_explain_json(
        explain_payload,
        label=label,
        index_mode=index_mode,
        ef_search=ef_search,
        iterative_scan=iterative_scan,
        client_filtered=client_id is not None,
        rows_requested=limit,
    )


def format_benchmark_table(results: list[BenchmarkScenarioResult]) -> str:
    """Format benchmark results into a single readable summary table."""
    header = (
        f"{'Scenario':<38} | {'Plan Type':<42} | {'Exec (ms)':>9} | "
        f"{'Buf Hit':>8} | {'Buf Read':>8} | {'Rows (ret/req)':>14}"
    )
    sep = "-" * len(header)
    lines = [header, sep]
    for r in results:
        rows_col = f"{r.rows_returned}/{r.rows_requested}"
        lines.append(
            f"{r.label:<38} | {r.plan_type[:42]:<42} | {r.execution_ms:>9.3f} | "
            f"{r.buffers_hit:>8d} | {r.buffers_read:>8d} | {rows_col:>14}"
        )
    return "\n".join(lines)


async def run_benchmark_sql(
    *,
    seed: int = 42,
    limit: int = 10,
    bench_url: str | None = None,
) -> list[BenchmarkScenarioResult]:
    """Run the full EXPLAIN (ANALYZE, BUFFERS) matrix against the benchmark database."""
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    engine = create_bench_engine(isolated_url)
    session_maker = create_bench_session_maker(engine)

    embedder = DeterministicFakeEmbedder(seed=seed)
    qvec = embedder.embed("merchant checkout settlement payout refund chargeback gateway")
    qvec_literal = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"

    results: list[BenchmarkScenarioResult] = []
    try:
        async with session_maker() as session:
            ws = await session.scalar(
                select(Workspace)
                .where(Workspace.name.like(f"{BENCH_WORKSPACE_PREFIX}%"))
                .order_by(Workspace.name)
                .limit(1)
            )
            if ws is None:
                raise RuntimeError(
                    "No BENCH- workspace found in benchmark DB. Run seed_benchmark.py first."
                )
            ws_id: UUID = ws.id

            sample_client_id = await session.scalar(
                select(ContextChunkRecord.client_id)
                .where(
                    ContextChunkRecord.workspace_id == ws_id,
                    ContextChunkRecord.client_id.is_not(None),
                )
                .limit(1)
            )
            if sample_client_id is None:
                raise RuntimeError("No chunk with client_id found in benchmark workspace.")

            # Warmup query so shared buffers are populated
            await _run_single_explain(
                session,
                label="warmup",
                index_mode="hnsw",
                ef_search=40,
                iterative_scan="off",
                workspace_id=ws_id,
                client_id=None,
                query_vector_literal=qvec_literal,
                embedding_model=FAKE_EMBEDDING_MODEL,
                limit=limit,
            )

            # Run HNSW scenarios first, then exact scan inside a rolled-back savepoint that drops the HNSW index
            for client_filtered in (False, True):
                cid = sample_client_id if client_filtered else None
                filter_tag = "client=yes" if client_filtered else "client=no"

                # 1. Exact scan (no ANN index)
                results.append(
                    await _run_single_explain(
                        session,
                        label=f"no_ann (exact) | {filter_tag}",
                        index_mode="exact",
                        ef_search=None,
                        iterative_scan=None,
                        workspace_id=ws_id,
                        client_id=cid,
                        query_vector_literal=qvec_literal,
                        embedding_model=FAKE_EMBEDDING_MODEL,
                        limit=limit,
                    )
                )

                # 2. HNSW combinations: ef_search in (40, 100, 200) x iterative_scan in (off, relaxed_order)
                for ef_search in (40, 100, 200):
                    for iter_mode in ("off", "relaxed_order"):
                        lit_mode: Literal["off", "relaxed_order"] = (
                            "off" if iter_mode == "off" else "relaxed_order"
                        )
                        results.append(
                            await _run_single_explain(
                                session,
                                label=f"hnsw ef={ef_search:<3d} iter={iter_mode:<13} | {filter_tag}",
                                index_mode="hnsw",
                                ef_search=ef_search,
                                iterative_scan=lit_mode,
                                workspace_id=ws_id,
                                client_id=cid,
                                query_vector_literal=qvec_literal,
                                embedding_model=FAKE_EMBEDDING_MODEL,
                                limit=limit,
                            )
                        )
    finally:
        await engine.dispose()

    print("\n" + format_benchmark_table(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run EXPLAIN (ANALYZE, BUFFERS) benchmark matrix for halfvec cosine retrieval."
    )
    parser.add_argument("--seed", type=int, default=42, help="Embedder seed (default: 42)")
    parser.add_argument("--limit", type=int, default=10, help="Requested top-k rows (default: 10)")
    parser.add_argument("--db-url", default=None, help="Optional BENCH_DATABASE_URL override.")
    args = parser.parse_args()

    asyncio.run(run_benchmark_sql(seed=args.seed, limit=args.limit, bench_url=args.db_url))


if __name__ == "__main__":
    main()
