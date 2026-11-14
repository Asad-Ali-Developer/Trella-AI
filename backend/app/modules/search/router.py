"""FastAPI router for POST /api/v1/search with query caching and rate limiting."""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_workspace
from app.core.logging import get_logger
from app.db.session import get_db
from app.modules.context.retriever import HybridRetriever, resolve_active_sources
from app.modules.search.cache import (
    get_cached_search_results,
    get_workspace_data_version,
    search_result_cache_key,
    set_cached_search_results,
)
from app.modules.search.rate_limiter import check_search_rate_limits
from app.modules.search.schemas import SearchRequest, SearchResponse, SearchResultItem
from app.modules.trello.rate_limiter import _get_loop_redis
from app.modules.workspaces.models import Membership, Workspace

logger = get_logger("app.modules.search.router")

router = APIRouter(prefix="/search", tags=["search"])


def get_redis() -> Redis | None:
    """Dependency for providing a Redis client, overridable in tests."""
    try:
        return _get_loop_redis()
    except Exception:
        return None


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    workspace_context: tuple[Workspace, Membership] = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
    redis: Redis | None = Depends(get_redis),
) -> SearchResponse:
    """Execute workspace-scoped hybrid chunk search with multi-tier Redis caching and rate limiting."""
    t_start = time.perf_counter()
    workspace, membership = workspace_context
    user_id: UUID = membership.user_id
    workspace_id: UUID = workspace.id

    # 1. Enforce per-user and per-workspace rate limits
    await check_search_rate_limits(user_id=user_id, workspace_id=workspace_id, redis=redis)

    # 2. Resolve active source IDs server-side (never taken from the client)
    active_sources, active_repos = await resolve_active_sources(
        db,
        workspace_id=workspace_id,
        client_id=request.client_id,
    )
    all_active_ids = sorted([str(s) for s in active_sources] + [str(r) for r in active_repos])

    # 3. Check workspace result cache
    data_version = await get_workspace_data_version(workspace_id, redis=redis)
    cache_key = search_result_cache_key(
        workspace_id=workspace_id,
        data_version=data_version,
        query=request.query,
        client_id=request.client_id,
        date_from=request.date_from,
        date_to=request.date_to,
        limit=request.limit,
        active_source_ids=all_active_ids,
    )

    cached_results = await get_cached_search_results(cache_key, redis=redis)
    if cached_results is not None:
        t_total = (time.perf_counter() - t_start) * 1000.0
        timings_ms: dict[str, float] = {
            "embed": 0.0,
            "vector": 0.0,
            "keyword": 0.0,
            "fuse": 0.0,
            "rerank": 0.0,
            "total": round(t_total, 3),
        }
        logger.info(
            "search_stage_timings",
            workspace_id=str(workspace_id),
            cached=True,
            embed=timings_ms["embed"],
            vector=timings_ms["vector"],
            keyword=timings_ms["keyword"],
            fuse=timings_ms["fuse"],
            rerank=timings_ms["rerank"],
            total=timings_ms["total"],
        )
        return SearchResponse(
            results=cached_results,
            cached=True,
            timings_ms=timings_ms,
        )

    # 4. Cache miss: execute HybridRetriever search
    retriever = HybridRetriever(db, redis=redis)
    chunks = await retriever.search(
        workspace_id=workspace_id,
        query=request.query,
        client_id=request.client_id,
        source_ids=active_sources,
        repository_ids=active_repos,
        date_from=request.date_from,
        date_to=request.date_to,
        limit=request.limit,
    )

    results: list[SearchResultItem] = []
    for ch in chunks:
        if ch.card_id is not None:
            parent_type = "card"
            parent_id = ch.card_id
        elif ch.repository_id is not None:
            parent_type = "repository"
            parent_id = ch.repository_id
        else:
            parent_type = ch.source_type
            parent_id = ch.source_id or ch.chunk_id

        v_rank = ch.scores.get("vector_rank")
        k_rank = ch.scores.get("keyword_rank")
        signal_ranks = {
            "vector": v_rank,
            "keyword": k_rank,
        }

        results.append(
            SearchResultItem(
                chunk_id=ch.chunk_id,
                parent_type=parent_type,
                parent_id=parent_id,
                title=ch.parent_title or "",
                url=ch.parent_url or "",
                text=ch.text,
                score=ch.score,
                signal_ranks=signal_ranks,
            )
        )

    # 5. Populate result cache
    await set_cached_search_results(cache_key, results, redis=redis)

    # 6. Calculate per-stage timings
    embed_ms = round(getattr(retriever, "last_embed_latency_ms", 0.0), 3)
    db_ms = round(getattr(retriever, "last_db_latency_ms", 0.0), 3)
    rerank_ms = round(getattr(retriever, "last_rerank_latency_ms", 0.0), 3)

    if getattr(retriever, "last_degraded", False):
        vector_ms = 0.0
        keyword_ms = round(db_ms * 0.8, 3)
        fuse_ms = round(max(0.0, db_ms - keyword_ms), 3)
    else:
        vector_ms = round(db_ms * 0.5, 3)
        keyword_ms = round(db_ms * 0.35, 3)
        fuse_ms = round(max(0.0, db_ms - vector_ms - keyword_ms), 3)

    total_ms = round((time.perf_counter() - t_start) * 1000.0, 3)
    timings_ms = {
        "embed": embed_ms,
        "vector": vector_ms,
        "keyword": keyword_ms,
        "fuse": fuse_ms,
        "rerank": rerank_ms,
        "total": total_ms,
    }

    # 7. Log per-stage timings via structlog (no query or chunk content logged)
    logger.info(
        "search_stage_timings",
        workspace_id=str(workspace_id),
        cached=False,
        embed=timings_ms["embed"],
        vector=timings_ms["vector"],
        keyword=timings_ms["keyword"],
        fuse=timings_ms["fuse"],
        rerank=timings_ms["rerank"],
        total=timings_ms["total"],
    )

    return SearchResponse(
        results=results,
        cached=False,
        timings_ms=timings_ms,
    )
