"""Benchmark script measuring p50/p95 latency for cold vs warm cache on the seeded 20k-chunk workspace."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any
from uuid import UUID

from app.modules.context.retriever import HybridRetriever, resolve_active_sources
from app.modules.search.cache import (
    get_cached_search_results,
    get_workspace_data_version,
    search_result_cache_key,
    set_cached_search_results,
)
from app.modules.search.schemas import SearchResultItem
from scripts.bench_db import (
    assert_bench_database_isolated,
    create_bench_engine,
    create_bench_session_maker,
)
from scripts.eval.gen_golden import DEFAULT_GOLDEN_PATH, load_golden_jsonl
from scripts.seed_benchmark import DeterministicFakeEmbedder


class InMemoryBenchmarkRedis:
    """In-memory Redis store for isolated, deterministic benchmark execution."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return val


def compute_percentile(values: list[float], p: float) -> float:
    """Compute percentile using linear interpolation."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(float(sorted_v[int(k)]), 3)
    d0 = sorted_v[int(f)] * (c - k)
    d1 = sorted_v[int(c)] * (k - f)
    return round(float(d0 + d1), 3)


async def execute_cached_search(
    session: Any,
    workspace_id: UUID,
    query: str,
    embedder: Any,
    redis: Any,
    limit: int = 10,
    client_id: UUID | None = None,
) -> tuple[list[SearchResultItem], bool, float]:
    """Simulate POST /api/v1/search execution logic and return (results, cached, elapsed_ms)."""
    t_start = time.perf_counter()

    # 1. Resolve active sources server-side
    active_sources, active_repos = await resolve_active_sources(
        session,
        workspace_id=workspace_id,
        client_id=client_id,
    )
    all_active_ids = sorted([str(s) for s in active_sources] + [str(r) for r in active_repos])

    # 2. Check result cache
    data_version = await get_workspace_data_version(workspace_id, redis=redis)
    cache_key = search_result_cache_key(
        workspace_id=workspace_id,
        data_version=data_version,
        query=query,
        client_id=client_id,
        date_from=None,
        date_to=None,
        limit=limit,
        active_source_ids=all_active_ids,
    )

    cached_results = await get_cached_search_results(cache_key, redis=redis)
    if cached_results is not None:
        elapsed = (time.perf_counter() - t_start) * 1000.0
        return cached_results, True, elapsed

    # 3. Cache miss: execute retriever
    retriever = HybridRetriever(session, embedder=embedder, redis=redis)
    chunks = await retriever.search(
        workspace_id=workspace_id,
        query=query,
        client_id=client_id,
        source_ids=active_sources,
        repository_ids=active_repos,
        limit=limit,
    )

    results: list[SearchResultItem] = []
    for ch in chunks:
        parent_type = "card" if ch.card_id is not None else "repository"
        parent_id = ch.card_id or ch.repository_id or ch.chunk_id
        results.append(
            SearchResultItem(
                chunk_id=ch.chunk_id,
                parent_type=parent_type,
                parent_id=parent_id,
                title=ch.parent_title or "",
                url=ch.parent_url or "",
                text=ch.text,
                score=ch.score,
                signal_ranks={
                    "vector": ch.scores.get("vector_rank"),
                    "keyword": ch.scores.get("keyword_rank"),
                },
            )
        )

    await set_cached_search_results(cache_key, results, redis=redis)
    elapsed = (time.perf_counter() - t_start) * 1000.0
    return results, False, elapsed


async def run_benchmark(bench_url: str | None = None) -> dict[str, Any]:
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    golden_entries = load_golden_jsonl(DEFAULT_GOLDEN_PATH)
    if not golden_entries:
        raise RuntimeError("No golden queries found for benchmark.")

    engine = create_bench_engine(isolated_url)
    session_maker = create_bench_session_maker(engine)
    embedder = DeterministicFakeEmbedder(seed=42)
    bench_redis = InMemoryBenchmarkRedis()

    cold_latencies: list[float] = []
    warm_latencies: list[float] = []

    try:
        async with session_maker() as session:
            # Warm up DB connection and verify workspace
            first_ws = golden_entries[0].workspace_id
            await execute_cached_search(
                session, first_ws, "warmup query", embedder, bench_redis, limit=5
            )

            print(f"Running benchmark on {len(golden_entries)} queries across 20k-chunk workspace...")
            for _idx, entry in enumerate(golden_entries, start=1):
                # 1. Cold pass: ensure cache entry is not present
                data_ver = await get_workspace_data_version(entry.workspace_id, redis=bench_redis)
                active_sources, active_repos = await resolve_active_sources(
                    session, entry.workspace_id, client_id=entry.client_id
                )
                active_ids = sorted([str(s) for s in active_sources] + [str(r) for r in active_repos])
                ckey = search_result_cache_key(
                    workspace_id=entry.workspace_id,
                    data_version=data_ver,
                    query=entry.query,
                    client_id=entry.client_id,
                    date_from=None,
                    date_to=None,
                    limit=10,
                    active_source_ids=active_ids,
                )
                bench_redis.store.pop(ckey, None)

                _, cold_hit, cold_ms = await execute_cached_search(
                    session,
                    entry.workspace_id,
                    entry.query,
                    embedder,
                    bench_redis,
                    limit=10,
                    client_id=entry.client_id,
                )
                assert cold_hit is False, "Cold pass should be a cache miss"
                cold_latencies.append(cold_ms)

                # 2. Warm pass: should immediately hit cache
                _, warm_hit, warm_ms = await execute_cached_search(
                    session,
                    entry.workspace_id,
                    entry.query,
                    embedder,
                    bench_redis,
                    limit=10,
                    client_id=entry.client_id,
                )
                assert warm_hit is True, "Warm pass should be a cache hit"
                warm_latencies.append(warm_ms)
    finally:
        await engine.dispose()

    cold_p50 = compute_percentile(cold_latencies, 50.0)
    cold_p95 = compute_percentile(cold_latencies, 95.0)
    warm_p50 = compute_percentile(warm_latencies, 50.0)
    warm_p95 = compute_percentile(warm_latencies, 95.0)
    speedup_p50 = round(cold_p50 / warm_p50, 1) if warm_p50 > 0 else 0.0
    speedup_p95 = round(cold_p95 / warm_p95, 1) if warm_p95 > 0 else 0.0

    report = {
        "query_count": len(golden_entries),
        "cold": {
            "p50_ms": cold_p50,
            "p95_ms": cold_p95,
            "avg_ms": round(sum(cold_latencies) / len(cold_latencies), 3),
        },
        "warm": {
            "p50_ms": warm_p50,
            "p95_ms": warm_p95,
            "avg_ms": round(sum(warm_latencies) / len(warm_latencies), 3),
        },
        "speedup": {
            "p50": f"{speedup_p50}x",
            "p95": f"{speedup_p95}x",
        },
    }

    print("\n" + "=" * 65)
    print("SEARCH CACHE BENCHMARK (20,000 Chunks Seeded Workspace)")
    print("=" * 65)
    print(f"{'Metric':<20} | {'Cold Cache (Miss)':>18} | {'Warm Cache (Hit)':>18}")
    print("-" * 65)
    print(f"{'p50 Latency':<20} | {cold_p50:>15.2f} ms | {warm_p50:>15.2f} ms")
    print(f"{'p95 Latency':<20} | {cold_p95:>15.2f} ms | {warm_p95:>15.2f} ms")
    print(f"{'Mean Latency':<20} | {report['cold']['avg_ms']:>15.2f} ms | {report['warm']['avg_ms']:>15.2f} ms")
    print("-" * 65)
    print(f"{'Speedup (p50)':<20} | {speedup_p50:>18.1f}x faster")
    print(f"{'Speedup (p95)':<20} | {speedup_p95:>18.1f}x faster")
    print("=" * 65 + "\n")

    return report


if __name__ == "__main__":
    asyncio.run(run_benchmark())
