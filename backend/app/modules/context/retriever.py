"""Hybrid vector + full-text chunk retriever with Reciprocal Rank Fusion (RRF) in SQL."""

from __future__ import annotations

import inspect
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable
from uuid import UUID

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    Integer,
    Select,
    String,
    bindparam,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    text,
    union_all,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.context.gemini import (
    EmbeddingRateLimited,
    EmbeddingUnavailable,
    GeminiContextClient,
    GeminiContextError,
)
from app.modules.context.models import EMBEDDING_DIMENSIONS, ContextChunkRecord
from app.modules.github.models import GithubRepository
from app.modules.trello.models import TrelloCard, TrelloClientRecord, TrelloSource

logger = get_logger("app.modules.context.retriever")

RRF_K = 60
CANDIDATE_POOL_LIMIT = 50
IterativeScanMode = Literal["off", "relaxed_order", "strict_order"]

_IDENTIFIER_OR_QUOTED_RE = re.compile(
    r'["\']'
    r'|[A-Za-z0-9]+[-_][A-Za-z0-9]+'
    r'|\b[0-9a-f]{7,40}\b'
)


def is_identifier_or_quoted_query(query: str) -> bool:
    """Return True if query contains quotes or identifier patterns (ticket numbers, SHAs)."""
    return bool(_IDENTIFIER_OR_QUOTED_RE.search(query))


_PGVECTOR_VERSION_CACHE: tuple[int, int] | None = None
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


class ChunkScores(TypedDict):
    """Rank and Reciprocal Rank Fusion score breakdown for a retrieved chunk."""

    vector_rank: int | None
    keyword_rank: int | None
    rrf: float


@dataclass(frozen=True)
class RetrievedChunk:
    """Single retrieved chunk with parent metadata, occurrence timestamp, and RRF scores."""

    chunk_id: UUID
    card_id: UUID | None
    repository_id: UUID | None
    source_type: str
    chunk_kind: str
    text: str
    parent_title: str
    parent_url: str
    occurred_at: datetime | None
    scores: ChunkScores = field(
        default_factory=lambda: ChunkScores(vector_rank=None, keyword_rank=None, rrf=0.0)
    )
    chunk_ids: tuple[UUID, ...] = field(default_factory=tuple)
    source_id: UUID | None = None
    client_id: UUID | None = None
    client_name: str | None = None
    ordinal: int = 0
    trello_card_id: str | None = None
    card_description: str | None = None
    vector_distance: float | None = None

    @property
    def title(self) -> str:
        """Alias for parent_title."""
        return self.parent_title

    @property
    def url(self) -> str:
        """Alias for parent_url."""
        return self.parent_url

    @property
    def score(self) -> float:
        """Primary RRF fusion score."""
        return float(self.scores.get("rrf", 0.0))


@runtime_checkable
class Retriever(Protocol):
    """Protocol for workspace-scoped chunk retrievers."""

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
        limit: int = 8,
    ) -> list[RetrievedChunk]:
        """Search workspace chunks matching filters and return up to `limit` results."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Protocol for post-retrieval chunk rerankers."""

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        limit: int = 8,
    ) -> list[RetrievedChunk]:
        """Rerank candidate chunks for `query` and return up to `limit` items."""
        ...


class NoopReranker:
    """Default pass-through reranker that preserves RRF order without calling an external service."""

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        limit: int = 8,
    ) -> list[RetrievedChunk]:
        del query
        return list(chunks[: max(0, int(limit))])


def parse_pgvector_version(extversion: str | None) -> tuple[int, int]:
    """Parse a pgvector extension version string (e.g. '0.8.0') into (major, minor)."""
    if not extversion:
        return (0, 0)
    match = _VERSION_RE.search(str(extversion))
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


async def get_pgvector_version(db: AsyncSession) -> tuple[int, int]:
    """Detect the installed pgvector extension version once per process and cache the result."""
    global _PGVECTOR_VERSION_CACHE
    if _PGVECTOR_VERSION_CACHE is not None:
        return _PGVECTOR_VERSION_CACHE
    try:
        raw_version = await db.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector' LIMIT 1")
        )
        parsed = parse_pgvector_version(str(raw_version) if raw_version is not None else None)
    except Exception:
        parsed = (0, 0)
    _PGVECTOR_VERSION_CACHE = parsed
    return parsed


def reset_pgvector_version_cache() -> None:
    """Reset the cached pgvector version (used in tests)."""
    global _PGVECTOR_VERSION_CACHE
    _PGVECTOR_VERSION_CACHE = None


async def resolve_active_sources(
    db: AsyncSession,
    workspace_id: UUID,
    *,
    client_id: UUID | None = None,
) -> tuple[list[UUID], list[UUID]]:
    """Resolve active Trello source IDs and active GitHub repository IDs for `workspace_id` in ONE query.

    Filters out excluded Trello boards (`excluded = true`), excluded GitHub repositories
    (`included = false`), inactive workspace connections (`status != 'active'`), and
    inactive provider accounts (`status != 'active'`).
    """
    trello_branch = (
        select(
            literal("trello").label("kind"),
            TrelloSource.id.label("entity_id"),
            TrelloSource.name.label("sort_name"),
        )
        .join(
            WorkspaceConnection,
            WorkspaceConnection.id == TrelloSource.connection_id,
        )
        .join(
            ProviderAccount,
            ProviderAccount.id == WorkspaceConnection.provider_account_id,
        )
        .where(
            TrelloSource.workspace_id == workspace_id,
            TrelloSource.excluded.is_(False),
            WorkspaceConnection.workspace_id == workspace_id,
            WorkspaceConnection.provider == "trello",
            WorkspaceConnection.status == "active",
            ProviderAccount.status == "active",
        )
    )

    github_branch = (
        select(
            literal("github").label("kind"),
            GithubRepository.id.label("entity_id"),
            GithubRepository.full_name.label("sort_name"),
        )
        .join(
            WorkspaceConnection,
            WorkspaceConnection.id == GithubRepository.connection_id,
        )
        .join(
            ProviderAccount,
            ProviderAccount.id == WorkspaceConnection.provider_account_id,
        )
        .where(
            GithubRepository.workspace_id == workspace_id,
            GithubRepository.included.is_(True),
            WorkspaceConnection.workspace_id == workspace_id,
            WorkspaceConnection.provider == "github",
            WorkspaceConnection.status == "active",
            ProviderAccount.status == "active",
        )
    )
    if client_id is not None:
        github_branch = github_branch.where(GithubRepository.client_id == client_id)

    combined = union_all(trello_branch, github_branch).subquery("active_sources")
    stmt = select(combined.c.kind, combined.c.entity_id).order_by(
        combined.c.kind,
        combined.c.sort_name,
        combined.c.entity_id,
    )
    rows = (await db.execute(stmt)).all()

    source_ids: list[UUID] = []
    repository_ids: list[UUID] = []
    for kind, entity_id in rows:
        if kind == "trello":
            source_ids.append(entity_id)
        elif kind == "github":
            repository_ids.append(entity_id)
    return source_ids, repository_ids


_STATEMENT_CACHE: dict[tuple[Any, ...], Select[Any]] = {}


def _apply_scope_filters_parameterized[*Ts](
    stmt: Select[*Ts],
    *,
    has_client: bool,
    has_sources: bool,
    has_repos: bool,
    auto_filter_sources: bool,
    has_date_from: bool,
    has_date_to: bool,
) -> Select[*Ts]:
    """Apply workspace, active source/repository, client, and date filters with parameterized binds."""
    ws_param = bindparam("workspace_id", type_=PG_UUID(as_uuid=True))
    stmt = stmt.where(ContextChunkRecord.workspace_id == ws_param)

    if auto_filter_sources:
        stmt = (
            stmt.outerjoin(
                TrelloSource,
                (TrelloSource.id == ContextChunkRecord.source_id)
                & (TrelloSource.workspace_id == ws_param),
            )
            .outerjoin(
                GithubRepository,
                (GithubRepository.id == ContextChunkRecord.repository_id)
                & (GithubRepository.workspace_id == ws_param),
            )
            .where(
                or_(
                    (ContextChunkRecord.source_id.is_not(None))
                    & (TrelloSource.excluded.is_(False)),
                    (ContextChunkRecord.repository_id.is_not(None))
                    & (GithubRepository.included.is_(True)),
                )
            )
        )
    else:
        branch_clauses = []
        if has_sources:
            branch_clauses.append(
                (ContextChunkRecord.source_id.is_not(None))
                & (
                    ContextChunkRecord.source_id
                    == func.any(bindparam("source_ids", type_=ARRAY(PG_UUID(as_uuid=True))))
                )
            )
        if has_repos:
            branch_clauses.append(
                (ContextChunkRecord.repository_id.is_not(None))
                & (
                    ContextChunkRecord.repository_id
                    == func.any(bindparam("repository_ids", type_=ARRAY(PG_UUID(as_uuid=True))))
                )
            )
        if branch_clauses:
            stmt = stmt.where(or_(*branch_clauses))
        else:
            stmt = stmt.where(literal(False))

    if has_client:
        stmt = stmt.where(
            ContextChunkRecord.client_id
            == bindparam("client_id", type_=PG_UUID(as_uuid=True))
        )
    if has_date_from:
        stmt = stmt.where(
            ContextChunkRecord.occurred_at
            >= bindparam("date_from", type_=DateTime(timezone=True))
        )
    if has_date_to:
        stmt = stmt.where(
            ContextChunkRecord.occurred_at
            <= bindparam("date_to", type_=DateTime(timezone=True))
        )

    return stmt


class HybridRetriever:
    """Hybrid vector + keyword chunk retriever with in-SQL Reciprocal Rank Fusion (k=60)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        embedder: Any | None = None,
        embedding_model: str | None = None,
        ef_search: int | None = None,
        iterative_scan: IterativeScanMode | None = None,
        reranker: Reranker | None = None,
        rrf_k: int = RRF_K,
        candidate_pool_limit: int = CANDIDATE_POOL_LIMIT,
        keyword_tie_limit: int | None = None,
        keyword_candidates: int | None = None,
        vector_weight: float | None = None,
        keyword_weight: float | None = None,
        redis: Any | None = None,
    ) -> None:
        self.session = session
        self.embedder = embedder
        self.redis = redis
        self.embedding_model = embedding_model or settings.GEMINI_EMBEDDING_MODEL
        self.ef_search = (
            int(ef_search) if ef_search is not None else int(settings.RETRIEVAL_EF_SEARCH)
        )
        self.iterative_scan: IterativeScanMode | None = (
            iterative_scan
            if iterative_scan is not None
            else settings.RETRIEVAL_ITERATIVE_SCAN
        )
        self.reranker: Reranker = reranker or NoopReranker()
        self.rrf_k = int(rrf_k)
        self.candidate_pool_limit = int(candidate_pool_limit)
        self.keyword_tie_limit = (
            int(keyword_tie_limit)
            if keyword_tie_limit is not None
            else int(settings.RETRIEVAL_KEYWORD_TIE_LIMIT)
        )
        self.keyword_candidates = (
            int(keyword_candidates)
            if keyword_candidates is not None
            else int(settings.RETRIEVAL_KEYWORD_CANDIDATES)
        )
        self.vector_weight = (
            float(vector_weight)
            if vector_weight is not None
            else float(settings.RETRIEVAL_VECTOR_WEIGHT)
        )
        self.keyword_weight = (
            float(keyword_weight)
            if keyword_weight is not None
            else float(settings.RETRIEVAL_KEYWORD_WEIGHT)
        )

        self.last_embed_latency_ms: float = 0.0
        self.last_db_exec_ms: float = 0.0
        self.last_db_fetch_ms: float = 0.0
        self.last_db_latency_ms: float = 0.0
        self.last_rerank_latency_ms: float = 0.0
        self.last_total_latency_ms: float = 0.0
        self.last_degraded: bool = False
        self.last_metadata: dict[str, Any] = {}

    async def _embed_query(self, query: str) -> tuple[list[float] | None, bool, str | None]:
        """Embed `query` with `embed(..., query=True)`, degrading gracefully on embedding failure."""
        from app.modules.search.cache import (
            get_cached_query_embedding,
            set_cached_query_embedding,
        )

        try:
            cached_vec = await get_cached_query_embedding(
                query,
                self.embedding_model,
                dim=EMBEDDING_DIMENSIONS,
                redis=self.redis,
            )
            if cached_vec is not None:
                return cached_vec, False, None
        except Exception as exc:
            logger.warning(
                "retriever_query_embed_cache_read_failed",
                error_type=type(exc).__name__,
            )

        try:
            if self.embedder is not None:
                embed_fn = self.embedder.embed
                sig = inspect.signature(embed_fn)
                kwargs: dict[str, Any] = {}
                if "query" in sig.parameters:
                    kwargs["query"] = True
                maybe_coro = embed_fn(query, **kwargs)
                vec = await maybe_coro if inspect.isawaitable(maybe_coro) else maybe_coro
                rounded = [round(float(x), 5) for x in vec]
                try:
                    await set_cached_query_embedding(
                        query,
                        self.embedding_model,
                        rounded,
                        dim=EMBEDDING_DIMENSIONS,
                        redis=self.redis,
                    )
                except Exception:
                    pass
                return rounded, False, None

            from app.modules.context import service as context_service

            gemini_cls = getattr(context_service, "GeminiContextClient", GeminiContextClient)
            async with gemini_cls() as gemini:
                vec = await gemini.embed(query, query=True)
                rounded = [round(float(x), 5) for x in vec]
                try:
                    await set_cached_query_embedding(
                        query,
                        self.embedding_model,
                        rounded,
                        dim=EMBEDDING_DIMENSIONS,
                        redis=self.redis,
                    )
                except Exception:
                    pass
                return rounded, False, None
        except (
            EmbeddingRateLimited,
            EmbeddingUnavailable,
            GeminiContextError,
            Exception,
        ) as exc:
            return None, True, type(exc).__name__

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
        limit: int = 8,
    ) -> list[RetrievedChunk]:
        """Execute hybrid vector + full-text search with RRF (k=60) and per-card collapse."""
        t_start = time.perf_counter()
        effective_limit = max(1, int(limit))

        if source_ids is not None and repository_ids is not None:
            if not source_ids and not repository_ids:
                self.last_embed_latency_ms = 0.0
                self.last_db_exec_ms = 0.0
                self.last_db_fetch_ms = 0.0
                self.last_db_latency_ms = 0.0
                self.last_total_latency_ms = (time.perf_counter() - t_start) * 1000.0
                self.last_degraded = False
                self.last_metadata = {
                    "mode": "hybrid",
                    "degraded": False,
                    "embed_ms": 0.0,
                    "db_exec_ms": 0.0,
                    "db_fetch_ms": 0.0,
                    "db_ms": 0.0,
                    "total_ms": round(self.last_total_latency_ms, 3),
                }
                return []

        pgv_version = await get_pgvector_version(self.session)
        supports_iterative_scan = pgv_version >= (0, 8)

        t_embed_start = time.perf_counter()
        query_vec, degraded, embed_error_type = await self._embed_query(query)
        embed_ms = (time.perf_counter() - t_embed_start) * 1000.0
        self.last_embed_latency_ms = embed_ms
        self.last_degraded = degraded

        has_vector = query_vec is not None
        has_client = client_id is not None
        has_sources = source_ids is not None and len(source_ids) > 0
        has_repos = repository_ids is not None and len(repository_ids) > 0
        auto_filter_sources = source_ids is None and repository_ids is None
        has_date_from = date_from is not None
        has_date_to = date_to is not None

        stmt = self._get_or_build_statement(
            has_vector=has_vector,
            has_client=has_client,
            has_sources=has_sources,
            has_repos=has_repos,
            auto_filter_sources=auto_filter_sources,
            has_date_from=has_date_from,
            has_date_to=has_date_to,
            supports_iterative_scan=supports_iterative_scan,
        )

        is_exact = is_identifier_or_quoted_query(query)
        effective_kw_weight = (
            max(1.0, float(self.keyword_weight)) if is_exact else float(self.keyword_weight)
        )

        params: dict[str, Any] = {
            "workspace_id": workspace_id,
            "query": query,
            "limit": effective_limit,
            "ef_search_str": str(int(self.ef_search)),
            "embedding_model": self.embedding_model,
            "vector_weight": float(self.vector_weight),
            "keyword_weight": effective_kw_weight,
        }
        if supports_iterative_scan and self.iterative_scan is not None:
            params["iterative_scan_str"] = str(self.iterative_scan)
        if has_vector:
            params["query_vec"] = query_vec
        if has_client:
            params["client_id"] = client_id
        if has_sources:
            params["source_ids"] = list(source_ids)  # type: ignore[arg-type]
        if has_repos:
            params["repository_ids"] = list(repository_ids)  # type: ignore[arg-type]
        if has_date_from:
            params["date_from"] = date_from
        if has_date_to:
            params["date_to"] = date_to

        t_db_start = time.perf_counter()
        result_proxy = await self.session.execute(stmt, params)
        t_db_exec = time.perf_counter()
        rows = result_proxy.all()
        t_db_fetch = time.perf_counter()

        db_exec_ms = (t_db_exec - t_db_start) * 1000.0
        db_fetch_ms = (t_db_fetch - t_db_exec) * 1000.0
        db_ms = (t_db_fetch - t_db_start) * 1000.0
        self.last_db_exec_ms = db_exec_ms
        self.last_db_fetch_ms = db_fetch_ms
        self.last_db_latency_ms = db_ms

        chunks: list[RetrievedChunk] = []
        for row in rows:
            v_rank = int(row.vector_rank) if row.vector_rank is not None else None
            k_rank = int(row.keyword_rank) if row.keyword_rank is not None else None
            rrf_val = float(row.rrf_score)
            raw_chunk_ids = row.card_chunk_ids or [row.chunk_id]
            chunk_ids_tuple = tuple(
                cid if isinstance(cid, UUID) else UUID(str(cid)) for cid in raw_chunk_ids
            )
            chunks.append(
                RetrievedChunk(
                    chunk_id=row.chunk_id,
                    card_id=row.card_id,
                    repository_id=row.repository_id,
                    source_type=str(row.source_type),
                    chunk_kind=str(row.chunk_kind),
                    text=str(row.text),
                    parent_title=str(row.parent_title or ""),
                    parent_url=str(row.parent_url or ""),
                    occurred_at=row.occurred_at,
                    scores={
                        "vector_rank": v_rank,
                        "keyword_rank": k_rank,
                        "rrf": rrf_val,
                    },
                    chunk_ids=chunk_ids_tuple,
                    source_id=row.source_id,
                    client_id=row.client_id,
                    client_name=row.client_name,
                    ordinal=int(row.ordinal),
                    trello_card_id=row.trello_card_id,
                    card_description=row.card_description,
                    vector_distance=(
                        float(row.vector_distance)
                        if row.vector_distance is not None
                        else None
                    ),
                )
            )

        t_rerank_start = time.perf_counter()
        reranked = await self.reranker.rerank(query, chunks, limit=effective_limit)
        self.last_rerank_latency_ms = (time.perf_counter() - t_rerank_start) * 1000.0
        total_ms = (time.perf_counter() - t_start) * 1000.0
        self.last_total_latency_ms = total_ms

        mode: Literal["hybrid", "keyword_only"] = "keyword_only" if degraded else "hybrid"
        self.last_metadata = {
            "mode": mode,
            "degraded": degraded,
            "embed_error_type": embed_error_type,
            "embed_ms": round(embed_ms, 3),
            "db_exec_ms": round(db_exec_ms, 3),
            "db_fetch_ms": round(db_fetch_ms, 3),
            "db_ms": round(db_ms, 3),
            "total_ms": round(total_ms, 3),
        }

        logger.info(
            "context_hybrid_search_completed",
            workspace_id=str(workspace_id),
            client_id=str(client_id) if client_id is not None else None,
            mode=mode,
            degraded=degraded,
            embed_error_type=embed_error_type,
            result_count=len(reranked),
            limit=effective_limit,
            ef_search=self.ef_search,
            iterative_scan=self.iterative_scan if supports_iterative_scan else "unsupported",
            embed_ms=round(embed_ms, 3),
            db_exec_ms=round(db_exec_ms, 3),
            db_fetch_ms=round(db_fetch_ms, 3),
            db_ms=round(db_ms, 3),
            total_ms=round(total_ms, 3),
        )

        return reranked

    def _get_or_build_statement(
        self,
        *,
        has_vector: bool,
        has_client: bool,
        has_sources: bool,
        has_repos: bool,
        auto_filter_sources: bool,
        has_date_from: bool,
        has_date_to: bool,
        supports_iterative_scan: bool,
    ) -> Select[Any]:
        """Retrieve statement from statement construction cache or compile and cache it."""
        cache_key = (
            has_vector,
            has_client,
            has_sources,
            has_repos,
            auto_filter_sources,
            has_date_from,
            has_date_to,
            supports_iterative_scan,
            self.iterative_scan if supports_iterative_scan else None,
            self.candidate_pool_limit,
            self.keyword_candidates,
            self.rrf_k,
            self.keyword_tie_limit,
        )
        cached = _STATEMENT_CACHE.get(cache_key)
        if cached is not None:
            return cached

        stmt = self._build_hybrid_statement(
            has_vector=has_vector,
            has_client=has_client,
            has_sources=has_sources,
            has_repos=has_repos,
            auto_filter_sources=auto_filter_sources,
            has_date_from=has_date_from,
            has_date_to=has_date_to,
            supports_iterative_scan=supports_iterative_scan,
        )
        _STATEMENT_CACHE[cache_key] = stmt
        return stmt

    def _build_hybrid_statement(
        self,
        *,
        has_vector: bool,
        has_client: bool,
        has_sources: bool,
        has_repos: bool,
        auto_filter_sources: bool,
        has_date_from: bool,
        has_date_to: bool,
        supports_iterative_scan: bool,
    ) -> Select[Any]:
        """Build the single-statement parameterized hybrid query with two CTEs, HNSW set_config, RRF, and per-card collapse."""
        config_cols: list[Any] = [
            func.set_config(
                "hnsw.ef_search",
                bindparam("ef_search_str", type_=String),
                True,
            ).label("ef_cfg")
        ]
        if supports_iterative_scan and self.iterative_scan is not None:
            if self.iterative_scan not in ("off", "relaxed_order", "strict_order"):
                raise ValueError(f"Unsupported iterative_scan mode: {self.iterative_scan!r}")
            config_cols.append(
                func.set_config(
                    "hnsw.iterative_scan",
                    bindparam("iterative_scan_str", type_=String),
                    True,
                ).label("iter_cfg")
            )
        config_cte = select(*config_cols).cte("config_setup")

        # 1. Vector top-50 CTE
        if has_vector:
            halfvec_param = bindparam("query_vec", type_=HALFVEC(EMBEDDING_DIMENSIONS))
            distance_expr = ContextChunkRecord.embedding.cosine_distance(halfvec_param)
            vector_base = select(
                ContextChunkRecord.id.label("chunk_id"),
                cast(distance_expr, Float).label("v_distance"),
            ).where(
                ContextChunkRecord.embedding.is_not(None),
                ContextChunkRecord.embedding_model
                == bindparam("embedding_model", type_=String),
                select(literal(True)).select_from(config_cte).scalar_subquery()
                == literal(True),
            )
            vector_base = _apply_scope_filters_parameterized(
                vector_base,
                has_client=has_client,
                has_sources=has_sources,
                has_repos=has_repos,
                auto_filter_sources=auto_filter_sources,
                has_date_from=has_date_from,
                has_date_to=has_date_to,
            )
            vector_candidates = (
                vector_base.order_by(distance_expr)
                .limit(self.candidate_pool_limit)
                .subquery("vector_candidates")
            )
            vector_cte = select(
                vector_candidates.c.chunk_id,
                func.row_number()
                .over(
                    order_by=(
                        vector_candidates.c.v_distance.asc(),
                        vector_candidates.c.chunk_id.asc(),
                    )
                )
                .label("v_rank"),
                vector_candidates.c.v_distance,
            ).cte("vector_top")
        else:
            vector_cte = (
                select(
                    cast(literal(None), PG_UUID(as_uuid=True)).label("chunk_id"),
                    cast(literal(None), Integer).label("v_rank"),
                    cast(literal(None), Float).label("v_distance"),
                )
                .where(
                    literal(False),
                    select(literal(True)).select_from(config_cte).scalar_subquery()
                    == literal(True),
                )
                .cte("vector_top")
            )

        # 2. Keyword top-50 CTE with pre-capping before evaluating ts_rank_cd
        ts_query = func.websearch_to_tsquery("simple", bindparam("query", type_=String))
        precap_base = select(
            ContextChunkRecord.id.label("chunk_id"),
            ContextChunkRecord.tsv.label("tsv"),
        ).where(
            ContextChunkRecord.tsv.op("@@")(ts_query),
        )
        precap_base = _apply_scope_filters_parameterized(
            precap_base,
            has_client=has_client,
            has_sources=has_sources,
            has_repos=has_repos,
            auto_filter_sources=auto_filter_sources,
            has_date_from=has_date_from,
            has_date_to=has_date_to,
        )
        precap_subq = (
            precap_base.order_by(
                ContextChunkRecord.occurred_at.desc().nulls_last(),
                ContextChunkRecord.id.desc(),
            )
            .limit(self.keyword_candidates)
            .subquery("keyword_precap")
        )

        k_score_expr = func.ts_rank_cd(precap_subq.c.tsv, ts_query)
        keyword_candidates = (
            select(
                precap_subq.c.chunk_id,
                cast(k_score_expr, Float).label("k_score"),
            )
            .order_by(k_score_expr.desc(), precap_subq.c.chunk_id.asc())
            .limit(self.candidate_pool_limit)
            .subquery("keyword_candidates")
        )
        keyword_cols: list[Any] = [
            keyword_candidates.c.chunk_id,
            func.row_number()
            .over(
                order_by=(
                    keyword_candidates.c.k_score.desc(),
                    keyword_candidates.c.chunk_id.asc(),
                )
            )
            .label("k_rank"),
            keyword_candidates.c.k_score,
        ]
        if self.keyword_tie_limit > 0:
            keyword_cols.append(
                func.count()
                .over(partition_by=keyword_candidates.c.k_score)
                .label("k_tie_count")
            )
        keyword_cte = select(*keyword_cols).cte("keyword_top")

        # 3. Reciprocal Rank Fusion (k=60) over FULL OUTER JOIN with weighted terms
        fused_chunk_id = func.coalesce(vector_cte.c.chunk_id, keyword_cte.c.chunk_id).label(
            "chunk_id"
        )
        vector_weight_param = bindparam("vector_weight", type_=Float)
        keyword_weight_param = bindparam("keyword_weight", type_=Float)

        vector_rrf_term = func.coalesce(
            vector_weight_param / (literal(float(self.rrf_k)) + cast(vector_cte.c.v_rank, Float)),
            literal(0.0),
        )
        raw_keyword_rrf_term = func.coalesce(
            keyword_weight_param / (literal(float(self.rrf_k)) + cast(keyword_cte.c.k_rank, Float)),
            literal(0.0),
        )
        keyword_rrf_term: Any
        if has_vector and self.keyword_tie_limit > 0:
            keyword_rrf_term = case(
                (
                    keyword_cte.c.k_tie_count <= literal(self.keyword_tie_limit),
                    raw_keyword_rrf_term,
                ),
                else_=literal(0.0),
            )
            effective_k_rank = case(
                (
                    keyword_cte.c.k_tie_count <= literal(self.keyword_tie_limit),
                    keyword_cte.c.k_rank,
                ),
                else_=cast(literal(None), Integer),
            ).label("keyword_rank")
        else:
            keyword_rrf_term = raw_keyword_rrf_term
            effective_k_rank = keyword_cte.c.k_rank.label("keyword_rank")

        rrf_expr = (vector_rrf_term + keyword_rrf_term).label("rrf_score")

        fused_stmt = (
            select(
                fused_chunk_id,
                vector_cte.c.v_rank.label("vector_rank"),
                vector_cte.c.v_distance.label("vector_distance"),
                effective_k_rank,
                keyword_cte.c.k_score.label("keyword_score"),
                rrf_expr,
            )
            .select_from(
                vector_cte.join(
                    keyword_cte,
                    vector_cte.c.chunk_id == keyword_cte.c.chunk_id,
                    full=True,
                )
            )
        )
        if has_vector and self.keyword_tie_limit > 0:
            fused_stmt = fused_stmt.where(
                or_(
                    vector_cte.c.v_rank.is_not(None),
                    keyword_cte.c.k_tie_count <= literal(self.keyword_tie_limit),
                )
            )
        fused_subq = fused_stmt.subquery("fused_chunks")

        # 4. Per-card collapse: group by card_id when card_id IS NOT NULL, or by chunk_id for non-card chunks.
        collapse_key = func.coalesce(ContextChunkRecord.card_id, ContextChunkRecord.id)
        best_rank_order = (
            fused_subq.c.rrf_score.desc(),
            func.coalesce(fused_subq.c.keyword_rank, literal(999999)).asc(),
            func.coalesce(fused_subq.c.vector_rank, literal(999999)).asc(),
            ContextChunkRecord.ordinal.asc(),
            ContextChunkRecord.id.asc(),
        )
        card_row_num = (
            func.row_number()
            .over(partition_by=collapse_key, order_by=best_rank_order)
            .label("rn")
        )
        card_chunk_ids_agg = (
            func.array_agg(ContextChunkRecord.id)
            .over(
                partition_by=collapse_key,
                order_by=best_rank_order,
                rows=(None, None),
            )
            .label("card_chunk_ids")
        )

        ws_param = bindparam("workspace_id", type_=PG_UUID(as_uuid=True))
        collapsed_subq = (
            select(
                ContextChunkRecord.id.label("chunk_id"),
                ContextChunkRecord.card_id,
                ContextChunkRecord.repository_id,
                ContextChunkRecord.source_id,
                ContextChunkRecord.client_id,
                ContextChunkRecord.source_type,
                ContextChunkRecord.chunk_kind,
                ContextChunkRecord.ordinal,
                ContextChunkRecord.text,
                ContextChunkRecord.occurred_at,
                fused_subq.c.vector_rank,
                fused_subq.c.vector_distance,
                fused_subq.c.keyword_rank,
                fused_subq.c.rrf_score,
                card_row_num,
                cast(card_chunk_ids_agg, ARRAY(PG_UUID(as_uuid=True))).label("card_chunk_ids"),
            )
            .join(ContextChunkRecord, ContextChunkRecord.id == fused_subq.c.chunk_id)
            .where(ContextChunkRecord.workspace_id == ws_param)
            .subquery("collapsed_chunks")
        )

        # 5. Join parent card / repository / client metadata and take top `limit`
        parent_title_expr = case(
            (collapsed_subq.c.card_id.is_not(None), func.coalesce(TrelloCard.name, literal(""))),
            else_=func.coalesce(GithubRepository.full_name, literal("")),
        ).label("parent_title")
        parent_url_expr = case(
            (collapsed_subq.c.card_id.is_not(None), func.coalesce(TrelloCard.url, literal(""))),
            else_=func.coalesce(GithubRepository.url, literal("")),
        ).label("parent_url")
        occurred_at_expr = func.coalesce(
            collapsed_subq.c.occurred_at,
            TrelloCard.last_activity_at,
        ).label("occurred_at")

        final_stmt = (
            select(
                collapsed_subq.c.chunk_id,
                collapsed_subq.c.card_id,
                collapsed_subq.c.repository_id,
                collapsed_subq.c.source_id,
                collapsed_subq.c.client_id,
                collapsed_subq.c.source_type,
                collapsed_subq.c.chunk_kind,
                collapsed_subq.c.ordinal,
                collapsed_subq.c.text,
                occurred_at_expr,
                collapsed_subq.c.vector_rank,
                collapsed_subq.c.vector_distance,
                collapsed_subq.c.keyword_rank,
                collapsed_subq.c.rrf_score,
                collapsed_subq.c.card_chunk_ids,
                parent_title_expr,
                parent_url_expr,
                TrelloCard.trello_card_id.label("trello_card_id"),
                TrelloCard.description.label("card_description"),
                cast(TrelloClientRecord.name, String).label("client_name"),
                cast(literal(True), Boolean).label("_ok"),
            )
            .outerjoin(
                TrelloCard,
                (TrelloCard.id == collapsed_subq.c.card_id)
                & (TrelloCard.workspace_id == ws_param),
            )
            .outerjoin(
                GithubRepository,
                (GithubRepository.id == collapsed_subq.c.repository_id)
                & (GithubRepository.workspace_id == ws_param),
            )
            .outerjoin(
                TrelloClientRecord,
                (TrelloClientRecord.id == collapsed_subq.c.client_id)
                & (TrelloClientRecord.workspace_id == ws_param),
            )
            .where(collapsed_subq.c.rn == 1)
            .order_by(
                collapsed_subq.c.rrf_score.desc(),
                func.coalesce(collapsed_subq.c.keyword_rank, literal(999999)).asc(),
                func.coalesce(collapsed_subq.c.vector_rank, literal(999999)).asc(),
                collapsed_subq.c.chunk_id.asc(),
            )
            .limit(bindparam("limit", type_=Integer))
        )

        return final_stmt
