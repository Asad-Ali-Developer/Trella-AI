"""Benchmark script measuring TTFT (Time To First Token) and total latency with a stub LLM on the 20k-chunk workspace."""

from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.modules.search.ask import stream_ask_response
from app.modules.search.schemas import AskRequest
from scripts.bench_db import (
    assert_bench_database_isolated,
    create_bench_engine,
    create_bench_session_maker,
)
from scripts.eval.gen_golden import DEFAULT_GOLDEN_PATH, load_golden_jsonl
from scripts.seed_benchmark import DeterministicFakeEmbedder


class InMemoryBenchmarkRedis:
    """In-memory Redis store for isolated benchmark execution."""

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

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> list[int]:
        key = str(keys_and_args[0])
        window_ms = int(keys_and_args[1]) if len(keys_and_args) > 1 else 60000
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return [val, window_ms]


class StubLLMStreamResponse:
    """Mock HTTP streaming response delivering immediate token deltas without Gemini latency."""

    def __init__(self, deltas: list[str]) -> None:
        self.deltas = deltas
        self.status_code = 200
        self.headers = {"Content-Type": "text/event-stream"}
        self.closed = False

    async def __aenter__(self) -> StubLLMStreamResponse:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.closed = True

    async def aiter_lines(self) -> Any:
        for delta in self.deltas:
            line_data = {
                "candidates": [
                    {
                        "content": {"parts": [{"text": delta}]},
                        "finishReason": "STOP",
                    }
                ]
            }
            yield f"data: {json.dumps(line_data)}\n"
        yield 'data: {"usageMetadata": {"promptTokenCount": 250, "candidatesTokenCount": 25}}\n'

    async def aclose(self) -> None:
        self.closed = True


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


async def execute_ask_stream(
    session: Any,
    workspace_id: UUID,
    query: str,
    embedder: Any,
    redis: Any,
    client_id: UUID | None = None,
) -> tuple[float, float]:
    """Execute stream_ask_response with a stub LLM and measure TTFT and total latency in milliseconds."""
    t_start = time.perf_counter()
    ttft_ms: float | None = None

    stub_stream = StubLLMStreamResponse(
        [
            "According to ",
            "[c1], the project is on ",
            "schedule with all deliverables met.",
        ]
    )

    req = AskRequest(question=query, client_id=client_id)
    user_id = UUID("00000000-0000-0000-0000-000000000001")

    async def fake_embed(text: str, *args: Any, **kwargs: Any) -> list[float]:
        return embedder.embed(text)

    with (
        patch("app.modules.search.ask._get_loop_client") as mock_client_getter,
        patch("app.modules.context.gemini.GeminiContextClient.embed", side_effect=fake_embed),
    ):
        mock_client = MagicMock()
        mock_client.stream.return_value = stub_stream
        mock_client_getter.return_value = mock_client

        generator = stream_ask_response(
            request_data=req,
            workspace_id=workspace_id,
            user_id=user_id,
            db=session,
            redis=redis,
        )

        async for chunk in generator:
            if "event: token" in chunk and ttft_ms is None:
                ttft_ms = (time.perf_counter() - t_start) * 1000.0

    t_total = (time.perf_counter() - t_start) * 1000.0
    if ttft_ms is None:
        ttft_ms = t_total

    return round(ttft_ms, 3), round(t_total, 3)


async def run_benchmark(bench_url: str | None = None) -> dict[str, Any]:
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    golden_entries = load_golden_jsonl(DEFAULT_GOLDEN_PATH)
    if not golden_entries:
        raise RuntimeError("No golden queries found for benchmark.")

    engine = create_bench_engine(isolated_url)
    session_maker = create_bench_session_maker(engine)
    embedder = DeterministicFakeEmbedder(seed=42)
    bench_redis = InMemoryBenchmarkRedis()

    ttft_latencies: list[float] = []
    total_latencies: list[float] = []

    try:
        async with session_maker() as session:
            # Warm up
            first_ws = golden_entries[0].workspace_id
            await execute_ask_stream(
                session, first_ws, "warmup question", embedder, bench_redis
            )

            print(f"Measuring POST /api/v1/ask on {len(golden_entries)} queries across 20k-chunk workspace...")
            for _idx, entry in enumerate(golden_entries, start=1):
                ttft, total = await execute_ask_stream(
                    session,
                    entry.workspace_id,
                    entry.query,
                    embedder,
                    bench_redis,
                    client_id=entry.client_id,
                )
                ttft_latencies.append(ttft)
                total_latencies.append(total)

    finally:
        await engine.dispose()

    ttft_p50 = compute_percentile(ttft_latencies, 50.0)
    ttft_p95 = compute_percentile(ttft_latencies, 95.0)
    total_p50 = compute_percentile(total_latencies, 50.0)
    total_p95 = compute_percentile(total_latencies, 95.0)

    print("\n" + "=" * 65)
    print("POST /api/v1/ask BENCHMARK (Stub LLM, 20,000 Chunks Workspace)")
    print("=" * 65)
    print(f"{'Metric':<25} | {'p50 Latency':>16} | {'p95 Latency':>16}")
    print("-" * 65)
    print(f"{'Time To First Token (TTFT)':<25} | {ttft_p50:>13.2f} ms | {ttft_p95:>13.2f} ms")
    print(f"{'Total Stream Time':<25} | {total_p50:>13.2f} ms | {total_p95:>13.2f} ms")
    print(f"{'Mean TTFT':<25} | {round(sum(ttft_latencies) / len(ttft_latencies), 2):>13.2f} ms |")
    print(f"{'Mean Total':<25} | {round(sum(total_latencies) / len(total_latencies), 2):>13.2f} ms |")
    print("=" * 65)

    return {
        "query_count": len(golden_entries),
        "ttft_p50": ttft_p50,
        "ttft_p95": ttft_p95,
        "total_p50": total_p50,
        "total_p95": total_p95,
    }


if __name__ == "__main__":
    asyncio.run(run_benchmark())
