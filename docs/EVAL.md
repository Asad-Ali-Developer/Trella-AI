# Retrieval Evaluation & SQL Benchmark Guide (`docs/EVAL.md`)

This guide explains how to provision the dedicated benchmark database (`client_insights_bench`), seed synthetic workspace data, generate the golden evaluation dataset, run the baseline retrieval evaluation (`VectorOnlyRetriever` and `KeywordOnlyRetriever`), and benchmark PostgreSQL `pgvector` query plans using `EXPLAIN (ANALYZE, BUFFERS)`.

---

## 1. Safety & Database Isolation

All benchmark and evaluation scripts operate exclusively against `Settings.BENCH_DATABASE_URL` (default: `postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_bench`).

- **Strict isolation guard**: Every script calls `assert_bench_database_isolated()`, which normalizes `(host, port, dbname)` and **refuses to run** if `BENCH_DATABASE_URL` is empty or matches `DATABASE_URL` (dev/prod) or `TEST_DATABASE_URL` (`client_insights_test`).
- **No external API calls**: Synthetic embeddings are produced deterministically by `DeterministicFakeEmbedder` (`embedding_model = "fake-bench-768"`) in 768 dimensions with topic clustering. Zero Gemini API requests are made.
- **Reversible**: Every seeded workspace is prefixed with `BENCH-` and can be removed at any time via `--reset`.

---

## 2. How to Run Everything

Run all commands from the `backend/` directory.

### Step 1: Create `client_insights_bench`, install `vector`, and migrate to `head`

```bash
python -m scripts.bench_db
```

This helper:
1. Verifies `BENCH_DATABASE_URL` is isolated from `DATABASE_URL` and `TEST_DATABASE_URL`.
2. Creates the `client_insights_bench` database if it does not exist.
3. Installs `CREATE EXTENSION IF NOT EXISTS vector`.
4. Runs `alembic upgrade head` against `client_insights_bench`.

### Step 2: Seed synthetic benchmark data (20,000 chunks)

```bash
python -m scripts.seed_benchmark --chunks 20000 --workspaces 3 --clients 10 --seed 42
```

- Generates 3 `BENCH-` workspaces, 10 clients per workspace, Trello sources, cards (tiny title-only cards, medium cards, and multi-chunk long cards), comments, a GitHub repository, and commits.
- Uses the real chunker (`chunk_card_body`, `chunk_comments`, `chunk_commits`) and inserts rows in multi-row batches (`BATCH_INSERT_SIZE = 1000`).
- To clear existing `BENCH-` workspaces before re-seeding, pass `--reset`:
  ```bash
  python -m scripts.seed_benchmark --chunks 20000 --workspaces 3 --clients 10 --seed 42 --reset
  ```

### Step 3: Generate the 40-query golden set (`golden.jsonl`)

```bash
python -m scripts.eval.gen_golden --seed 42
```

Writes 40 queries (10 per group) to `backend/scripts/eval/golden.jsonl`:
- `semantic`: paraphrased topic queries embedded via `DeterministicFakeEmbedder`.
- `exact_identifier`: exact issue/card codes (`PROJ-123`) and commit SHA prefixes.
- `client_filtered`: topic queries restricted to a single `client_id`.
- `date_filtered`: topic queries restricted to a `[date_from, date_to]` window.

Each line in `golden.jsonl` has the format:
```json
{"query": "...", "workspace_id": "...", "client_id": null, "date_from": null, "date_to": null, "expected_card_ids": ["..."], "group": "semantic"}
```

### Step 4: Run retrieval evaluation (`eval_retrieval.py`)

```bash
python -m scripts.eval_retrieval --ef-search 100 --iterative-scan relaxed_order
```

Evaluates both pure-SQL baselines against `backend/scripts/eval/golden.jsonl`:
1. `VectorOnlyRetriever`: `halfvec(768)` cosine distance (`<=>`) with workspace + active-source filtering in the same SQL query, configurable `SET LOCAL hnsw.ef_search`, and optional `SET LOCAL hnsw.iterative_scan`.
2. `KeywordOnlyRetriever`: PostgreSQL full-text search using `websearch_to_tsquery('simple', query)` and `ts_rank_cd(tsv, query)` over the persisted `tsv` column.

Prints per-group and overall metrics and writes a timestamped JSON report to `backend/scripts/eval/reports/<timestamp>.json`.

### Step 5: Run SQL plan & HNSW parameter benchmark (`benchmark_sql.py`)

```bash
python -m scripts.benchmark_sql --seed 42 --limit 10
```

Runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` at the seeded dataset size across:
- Exact scan (no ANN index) vs HNSW (`ix_chunks_embedding_halfvec_cosine`)
- `hnsw.ef_search` in `(40, 100, 200)`
- `hnsw.iterative_scan` in `(off, relaxed_order)`
- With and without a `client_id` filter

---

## 3. What Each Metric Means

### Retrieval Quality & Latency Metrics (`eval_retrieval.py`)
- **`Recall@5` / `Recall@10`**: The fraction of `expected_card_ids` for a query that appear in the top 5 (or top 10) distinct retrieved `card_id`s:
  $$\text{Recall@}k = \frac{|\text{Retrieved}_{1..k} \cap \text{Expected}|}{|\text{Expected}|}$$
- **`MRR` (Mean Reciprocal Rank)**: The mean across queries of $\frac{1}{\text{rank}}$, where $\text{rank}$ is the 1-based position of the first relevant `card_id` in the retrieved list (or $0$ if none of the expected cards are retrieved).
- **`p50 (ms)` / `p95 (ms)`**: The 50th percentile (median) and 95th percentile execution latency (in milliseconds) of the database retrieval query.

### SQL Execution Plan Metrics (`benchmark_sql.py`)
- **`Plan Type`**: The PostgreSQL executor node chosen by the planner (e.g., `Index Scan (ix_chunks_embedding_halfvec_cosine)` vs `Limit -> Sort -> Seq Scan`).
- **`Exec (ms)`**: Actual execution time reported by `EXPLAIN ANALYZE` in milliseconds.
- **`Buf Hit` / `Buf Read`**: Shared buffer pages served from PostgreSQL RAM cache (`Shared Hit Blocks`) vs read from disk/OS page cache (`Shared Read Blocks`).
- **`Rows (ret/req)`**: Actual rows returned by the query vs the `LIMIT` requested (`k`). When a selective predicate (such as `client_id`) filters out candidates during an HNSW scan with `iterative_scan = off`, fewer than `k` rows may be returned; enabling `hnsw.iterative_scan = relaxed_order` allows HNSW to continue scanning until `k` matching rows are found.

---

## 4. Blank Results Tables

### 4.1 Retrieval Evaluation Results (`eval_retrieval.py`)

| Retriever | Query Group | Queries | Recall@5 | Recall@10 | MRR | p50 (ms) | p95 (ms) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `VectorOnlyRetriever` | `semantic` | 10 | | | | | |
| `VectorOnlyRetriever` | `exact_identifier` | 10 | | | | | |
| `VectorOnlyRetriever` | `client_filtered` | 10 | | | | | |
| `VectorOnlyRetriever` | `date_filtered` | 10 | | | | | |
| **`VectorOnlyRetriever`** | **`OVERALL`** | **40** | | | | | |
| `KeywordOnlyRetriever` | `semantic` | 10 | | | | | |
| `KeywordOnlyRetriever` | `exact_identifier` | 10 | | | | | |
| `KeywordOnlyRetriever` | `client_filtered` | 10 | | | | | |
| `KeywordOnlyRetriever` | `date_filtered` | 10 | | | | | |
| **`KeywordOnlyRetriever`** | **`OVERALL`** | **40** | | | | | |

### 4.2 SQL Plan & HNSW Benchmark (`benchmark_sql.py`)

| Index Mode | `ef_search` | `iterative_scan` | `client_id` Filter | Plan Type | Exec (ms) | Buffers Hit | Buffers Read | Rows (ret/req) |
| :--- | :---: | :---: | :---: | :--- | ---: | ---: | ---: | :---: |
| Exact (no ANN) | - | - | No | | | | | /10 |
| HNSW | 40 | `off` | No | | | | | /10 |
| HNSW | 40 | `relaxed_order` | No | | | | | /10 |
| HNSW | 100 | `off` | No | | | | | /10 |
| HNSW | 100 | `relaxed_order` | No | | | | | /10 |
| HNSW | 200 | `off` | No | | | | | /10 |
| HNSW | 200 | `relaxed_order` | No | | | | | /10 |
| Exact (no ANN) | - | - | Yes | | | | | /10 |
| HNSW | 40 | `off` | Yes | | | | | /10 |
| HNSW | 40 | `relaxed_order` | Yes | | | | | /10 |
| HNSW | 100 | `off` | Yes | | | | | /10 |
| HNSW | 100 | `relaxed_order` | Yes | | | | | /10 |
| HNSW | 200 | `off` | Yes | | | | | /10 |
| HNSW | 200 | `relaxed_order` | Yes | | | | | /10 |

