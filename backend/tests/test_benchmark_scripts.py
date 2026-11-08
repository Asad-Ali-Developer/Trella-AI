"""Tests for benchmark scripts: fake embedder, chunker integration, eval metrics, and DB safety guard."""

from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.context.retriever import HybridRetriever
from scripts.bench_db import assert_bench_database_isolated
from scripts.benchmark_sql import HNSW_INDEX_NAME, parse_explain_json
from scripts.eval.gen_golden import (
    GoldenQueryEntry,
    generate_golden_queries,
    load_golden_jsonl,
    write_golden_jsonl,
)
from scripts.eval_retrieval import (
    KeywordOnlyRetriever,
    RetrievedChunk,
    Retriever,
    VectorOnlyRetriever,
    aggregate_query_records,
    compute_mrr,
    compute_percentile,
    compute_recall_at_k,
    deduplicate_ranked_card_ids,
    evaluate_retriever,
)
from scripts.seed_benchmark import (
    BENCH_WORKSPACE_PREFIX,
    FAKE_EMBEDDING_MODEL,
    DeterministicFakeEmbedder,
    build_synthetic_dataset,
    cosine_similarity,
    insert_synthetic_dataset,
    reset_bench_data,
)


def test_safety_guard_refuses_dev_and_test_databases() -> None:
    dev_url = settings.DATABASE_URL
    test_url = settings.TEST_DATABASE_URL

    # Exact match with DATABASE_URL is refused
    with pytest.raises(RuntimeError, match="must not equal DATABASE_URL"):
        assert_bench_database_isolated(
            bench_url=dev_url,
            dev_url=dev_url,
            test_url=test_url,
        )

    # Exact match with TEST_DATABASE_URL is refused
    with pytest.raises(RuntimeError, match="must not equal TEST_DATABASE_URL"):
        assert_bench_database_isolated(
            bench_url=test_url,
            dev_url=dev_url,
            test_url=test_url,
        )

    # Normalized host/scheme variations (127.0.0.1 vs localhost, postgres:// vs postgresql+asyncpg://) are also refused
    with pytest.raises(RuntimeError, match="must not equal DATABASE_URL"):
        assert_bench_database_isolated(
            bench_url="postgres://other:secret@127.0.0.1:5433/client_insights",
            dev_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights",
            test_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_test",
        )

    with pytest.raises(RuntimeError, match="must not equal TEST_DATABASE_URL"):
        assert_bench_database_isolated(
            bench_url="postgresql://user:pass@127.0.0.1:5433/client_insights_test",
            dev_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights",
            test_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_test",
        )

    # Empty URL is refused
    with pytest.raises(RuntimeError, match="must not be empty"):
        assert_bench_database_isolated(
            bench_url="   ",
            dev_url=dev_url,
            test_url=test_url,
        )

    # Dedicated client_insights_bench succeeds
    valid = assert_bench_database_isolated(
        bench_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_bench",
        dev_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights",
        test_url="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_test",
    )
    assert valid.endswith("/client_insights_bench")


def test_fake_embedder_is_deterministic_and_topic_clustered() -> None:
    embedder_a = DeterministicFakeEmbedder(seed=42)
    embedder_b = DeterministicFakeEmbedder(seed=42)

    payments_text_1 = "Stripe checkout payment settlement gateway failed with webhook timeout."
    payments_text_2 = "Merchant refund and chargeback payout reconciliation on ACH gateway."
    auth_text_1 = "Enterprise SAML SSO and OAuth PKCE authentication with TOTP MFA session."
    mobile_text_1 = "iOS and Android React Native mobile app offline biometric push sync."

    v_pay_1 = embedder_a.embed(payments_text_1)
    v_pay_1_repeat = embedder_b.embed(payments_text_1)
    v_pay_2 = embedder_a.embed(payments_text_2)
    v_auth_1 = embedder_a.embed(auth_text_1)
    v_mob_1 = embedder_a.embed(mobile_text_1)

    # 1. Exact determinism across calls and instances
    assert len(v_pay_1) == 768
    assert v_pay_1 == v_pay_1_repeat

    # 2. All vectors are unit length
    for vec in (v_pay_1, v_pay_2, v_auth_1, v_mob_1):
        norm = math.sqrt(sum(x * x for x in vec))
        assert math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6)

    # 3. Topic clustering: same-topic similarity >> cross-topic similarity
    same_topic_sim = cosine_similarity(v_pay_1, v_pay_2)
    cross_auth_sim = cosine_similarity(v_pay_1, v_auth_1)
    cross_mobile_sim = cosine_similarity(v_pay_1, v_mob_1)

    assert same_topic_sim > 0.70
    assert cross_auth_sim < 0.25
    assert cross_mobile_sim < 0.25
    assert same_topic_sim > cross_auth_sim + 0.50


def test_synthetic_chunker_integration_produces_valid_rows() -> None:
    dataset = build_synthetic_dataset(
        target_chunks=60,
        num_workspaces=2,
        clients_per_workspace=3,
        seed=42,
    )

    assert len(dataset["workspaces"]) == 2
    assert all(ws["name"].startswith(BENCH_WORKSPACE_PREFIX) for ws in dataset["workspaces"])
    assert len(dataset["clients"]) == 6
    assert len(dataset["chunks"]) == 60

    chunks = dataset["chunks"]
    kinds = {ch["chunk_kind"] for ch in chunks}
    assert "card_body" in kinds
    assert "comment_group" in kinds
    assert "commit_group" in kinds

    # Verify tiny cards (empty description) and long cards (split across ordinal >= 1) exist
    descriptions = [c["description"] for c in dataset["cards"]]
    assert any(d == "" for d in descriptions)
    assert any(len(d) > 1000 for d in descriptions)
    assert any(ch["chunk_kind"] == "card_body" and ch["ordinal"] >= 1 for ch in chunks)

    for ch in chunks:
        assert ch["embedding_model"] == FAKE_EMBEDDING_MODEL
        assert len(ch["embedding"]) == 768
        assert ch["token_estimate"] > 0
        assert len(ch["content_hash"]) == 64
        if ch["card_id"] is not None:
            assert ch["repository_id"] is None
            assert ch["source_type"] == "trello"
            assert ch["source_id"] is not None
            assert ch["text"].startswith("Client: ")
        else:
            assert ch["repository_id"] is not None
            assert ch["source_type"] == "github"
            assert ch["source_id"] is None
            assert ch["group_key"] is not None
            assert ch["text"].startswith("Client: ")


def test_eval_metrics_recall_at_k_and_mrr_on_handmade_example() -> None:
    expected = ["card-A", "card-B"]
    retrieved = ["card-X", "card-A", "card-Y", "card-Z", "card-W", "card-B"]

    # At k=1: only card-X retrieved -> 0 of 2 expected found
    assert math.isclose(compute_recall_at_k(retrieved, expected, 1), 0.0)
    # At k=2: card-A found -> 1 of 2 expected found = 0.5
    assert math.isclose(compute_recall_at_k(retrieved, expected, 2), 0.5)
    # At k=5: still only card-A in top 5 -> 0.5
    assert math.isclose(compute_recall_at_k(retrieved, expected, 5), 0.5)
    # At k=10: both card-A and card-B in top 10 -> 1.0
    assert math.isclose(compute_recall_at_k(retrieved, expected, 10), 1.0)

    # First relevant card is card-A at 1-based rank 2 -> MRR = 1/2 = 0.5
    assert math.isclose(compute_mrr(retrieved, expected), 0.5)

    # When no expected card is present -> Recall = 0.0, MRR = 0.0
    assert math.isclose(compute_recall_at_k(["card-1", "card-2"], expected, 5), 0.0)
    assert math.isclose(compute_mrr(["card-1", "card-2"], expected), 0.0)

    # Deduplication preserves first rank order across multiple chunks of the same card
    c1, c2 = uuid4(), uuid4()
    raw_chunks = [
        RetrievedChunk(c1, c1, None, None, None, "card_body", 0, 0.95, "a"),
        RetrievedChunk(c1, c1, None, None, None, "comment_group", 0, 0.91, "b"),
        RetrievedChunk(c2, c2, None, None, None, "card_body", 0, 0.85, "c"),
    ]
    assert deduplicate_ranked_card_ids(raw_chunks) == [str(c1), str(c2)]

    # Percentile and group aggregation check
    assert math.isclose(compute_percentile([10.0, 20.0, 30.0, 40.0, 50.0], 50.0), 30.0)
    agg = aggregate_query_records(
        [
            {"recall_at_5": 0.5, "recall_at_10": 1.0, "mrr": 0.5, "latency_ms": 10.0},
            {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr": 1.0, "latency_ms": 30.0},
        ]
    )
    assert agg.count == 2
    assert math.isclose(agg.recall_at_5, 0.75)
    assert math.isclose(agg.recall_at_10, 1.0)
    assert math.isclose(agg.mrr, 0.75)
    assert math.isclose(agg.p50_ms, 20.0)


@pytest.mark.asyncio
async def test_small_seed_golden_and_retrievers_integration(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    # Seed a tiny synthetic dataset (30 chunks, not 20k) into db_session and verify
    # batch insert, golden generation, VectorOnlyRetriever, KeywordOnlyRetriever, and reset.
    dataset = build_synthetic_dataset(
        target_chunks=36,
        num_workspaces=2,
        clients_per_workspace=2,
        seed=42,
    )
    await insert_synthetic_dataset(db_session, dataset, batch_size=20)

    golden_entries = await generate_golden_queries(db_session, seed=42, count_per_group=2)
    assert len(golden_entries) == 8
    assert {e.group for e in golden_entries} == {
        "semantic",
        "exact_identifier",
        "client_filtered",
        "date_filtered",
    }

    golden_file = write_golden_jsonl(golden_entries, tmp_path / "golden.jsonl")
    reloaded = load_golden_jsonl(golden_file)
    assert len(reloaded) == 8
    assert isinstance(reloaded[0], GoldenQueryEntry)

    vec_retriever = VectorOnlyRetriever(
        db_session,
        embedder=DeterministicFakeEmbedder(seed=42),
        ef_search=40,
        iterative_scan="relaxed_order",
    )
    kw_retriever = KeywordOnlyRetriever(db_session)
    assert isinstance(vec_retriever, Retriever)
    assert isinstance(kw_retriever, Retriever)

    vec_report = await evaluate_retriever(vec_retriever, reloaded, limit=10)
    kw_report = await evaluate_retriever(kw_retriever, reloaded, limit=10)
    hybrid_retriever = HybridRetriever(
        db_session,
        embedder=DeterministicFakeEmbedder(seed=42),
        embedding_model=FAKE_EMBEDDING_MODEL,
        ef_search=40,
        iterative_scan="relaxed_order",
    )
    hybrid_report = await evaluate_retriever(hybrid_retriever, reloaded, limit=10)
    assert hybrid_report["overall"]["count"] == 8

    assert vec_report["overall"]["count"] == 8
    assert vec_report["overall"]["recall_at_5"] > 0.5
    assert kw_report["groups"]["exact_identifier"]["recall_at_5"] >= 0.5

    # Verify explain JSON parser on a sample explain output structure
    sample_plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 10,
                "Shared Hit Blocks": 42,
                "Shared Read Blocks": 3,
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": HNSW_INDEX_NAME,
                        "Actual Rows": 10,
                        "Shared Hit Blocks": 40,
                        "Shared Read Blocks": 3,
                    }
                ],
            },
            "Execution Time": 1.234,
        }
    ]
    parsed = parse_explain_json(
        sample_plan,
        label="test",
        index_mode="hnsw",
        ef_search=100,
        iterative_scan="relaxed_order",
        client_filtered=True,
        rows_requested=10,
    )
    assert HNSW_INDEX_NAME in parsed.plan_type
    assert parsed.buffers_hit == 42
    assert parsed.buffers_read == 3
    assert parsed.rows_returned == 10

    removed = await reset_bench_data(db_session)
    assert removed == 2

