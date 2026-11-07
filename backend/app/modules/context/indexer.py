"""Workspace-scoped indexing service for Trello sources and GitHub repositories.

No HTTP request/response dependencies and no raw card/comment/commit text in logs.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.context.chunker import (
    CHUNKER_VERSION,
    CardBodyInput,
    Chunk,
    CommentInput,
    CommitInput,
    chunk_card_body,
    chunk_comments,
    chunk_commits,
)
from app.modules.context.gemini import (
    MAX_EMBED_BATCH_SIZE,
    EmbeddingUnavailable,
    GeminiContextClient,
)
from app.modules.context.models import ContextChunkRecord, TrelloCardSummary
from app.modules.context.service import SUMMARY_PROMPT_VERSION
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientMapping,
    TrelloClientRecord,
    TrelloComment,
    TrelloMember,
    TrelloSource,
)
from app.modules.trello.rate_limiter import _get_loop_pool, _get_loop_redis

logger = get_logger("app.modules.context.indexer")

_ORIG_EMBED_BATCH = GeminiContextClient.embed_batch
_ORIG_SUMMARIZE = GeminiContextClient.summarize
_ORIG_SUMMARIZE_CARD = GeminiContextClient.summarize_card
_ORIG_POST = GeminiContextClient._post
_ORIG_SEND_ONCE = GeminiContextClient._send_once


def data_version_key(workspace_id: UUID) -> str:
    """Return the Redis key storing the workspace chunk data version counter."""
    return f"ws:{workspace_id}:data_version"


async def increment_workspace_data_version(
    workspace_id: UUID,
    *,
    redis: Redis | None = None,
) -> int | None:
    """Increment `ws:{workspace_id}:data_version` using the shared per-loop Redis pool."""
    key = data_version_key(workspace_id)
    try:
        client = redis if redis is not None else _get_loop_redis()
        value = await client.incr(key)
        return int(value)
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning(
            "workspace_data_version_increment_failed",
            workspace_id=str(workspace_id),
            error_type=type(exc).__name__,
        )
        return None


def resolve_card_client_id(
    card_labels: list[dict[str, str]],
    list_name: str,
    board_external_id: str,
    mapping_ids: dict[tuple[str, str], UUID],
) -> UUID | None:
    """Resolve client_id for a Trello card with precedence: label -> list -> board."""
    client_id = next(
        (
            mapping_ids[("label", str(label.get("name", "")).strip().casefold())]
            for label in sorted(
                (lbl for lbl in card_labels if isinstance(lbl, dict)),
                key=lambda item: str(item.get("name", "")).casefold(),
            )
            if ("label", str(label.get("name", "")).strip().casefold()) in mapping_ids
        ),
        None,
    )
    if client_id is None:
        client_id = mapping_ids.get(("list", (list_name or "").strip().casefold()))
    if client_id is None:
        client_id = mapping_ids.get(("board", board_external_id.casefold()))
    return client_id


def _format_card_summary_source_text(
    card: TrelloCard,
    comments: list[TrelloComment],
) -> str:
    pieces = [
        f"Title: {card.name}",
        f"Description: {card.description.strip()}",
        f"List: {card.list_name}",
        "Labels: "
        + ", ".join(
            str(label["name"])
            for label in (card.labels or [])
            if isinstance(label, dict) and label.get("name")
        ),
    ]
    pieces.extend(
        f"Comment ({comment.created_at_trello.isoformat()}): {comment.text}"
        for comment in comments
    )
    text = "\n".join(piece for piece in pieces if piece.strip())
    return text[:20000]


@dataclass
class IndexingResult:
    """Counts recorded during a source or repository indexing run."""

    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    embedded: int = 0
    failed_documents: int = 0
    failed_batches: int = 0
    summaries_generated: int = 0
    summaries_deleted: int = 0
    has_more_embeddings: bool = False
    has_more_summaries: bool = False

    @property
    def has_more(self) -> bool:
        """Return True if capped embeddings or summaries remain for a follow-up run."""
        return self.has_more_embeddings or self.has_more_summaries


class IndexingService:
    """Three-phase chunking, batched embedding, and card summarization service."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        gemini_client: GeminiContextClient | None = None,
        redis: Redis | None = None,
        batch_size: int = MAX_EMBED_BATCH_SIZE,
        on_batch_complete: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.db = db
        self._custom_gemini = gemini_client
        self._custom_redis = redis
        self.batch_size = max(1, batch_size)
        self._on_batch_complete = on_batch_complete

    @property
    def redis(self) -> Redis:
        if self._custom_redis is not None:
            return self._custom_redis
        return _get_loop_redis()

    @property
    def connection_pool(self) -> ConnectionPool:
        if self._custom_redis is not None and self._custom_redis.connection_pool is not None:
            return self._custom_redis.connection_pool
        return _get_loop_pool()

    async def increment_data_version(self, workspace_id: UUID) -> int | None:
        """Increment `ws:{workspace_id}:data_version` in Redis."""
        return await increment_workspace_data_version(
            workspace_id,
            redis=self._custom_redis,
        )

    def _build_gemini_for_embed(self) -> GeminiContextClient | None:
        if self._custom_gemini is not None:
            return self._custom_gemini
        embed_patched = GeminiContextClient.embed_batch is not _ORIG_EMBED_BATCH
        transport_patched = (
            GeminiContextClient._post is not _ORIG_POST
            or GeminiContextClient._send_once is not _ORIG_SEND_ONCE
        )
        if settings.GEMINI_API_KEY:
            return GeminiContextClient()
        if embed_patched or transport_patched:
            instance = GeminiContextClient.__new__(GeminiContextClient)
            instance._custom_client = None
            return instance
        return None

    def _build_gemini_for_summarize(self) -> GeminiContextClient | None:
        if self._custom_gemini is not None:
            return self._custom_gemini
        summarize_patched = (
            GeminiContextClient.summarize is not _ORIG_SUMMARIZE
            or GeminiContextClient.summarize_card is not _ORIG_SUMMARIZE_CARD
            or GeminiContextClient._post is not _ORIG_POST
            or GeminiContextClient._send_once is not _ORIG_SEND_ONCE
        )
        embed_only_patched = (
            GeminiContextClient.embed_batch is not _ORIG_EMBED_BATCH
            and not summarize_patched
        )
        if embed_only_patched:
            return None
        if settings.GEMINI_API_KEY:
            return GeminiContextClient()
        if summarize_patched:
            instance = GeminiContextClient.__new__(GeminiContextClient)
            instance._custom_client = None
            return instance
        return None

    async def index_source(
        self,
        source_id: UUID,
        *,
        force: bool = False,
    ) -> IndexingResult:
        """Index a Trello source in three separate phases: (a) diff + commit, (b) embed per batch, (c) summarize per card."""
        result = IndexingResult()
        source = await self.db.scalar(
            select(TrelloSource).where(TrelloSource.id == source_id)
        )
        if source is None:
            if self.db.in_transaction():
                await self.db.commit()
            return result

        workspace_id = source.workspace_id
        mappings = list(
            (
                await self.db.scalars(
                    select(TrelloClientMapping).where(
                        TrelloClientMapping.workspace_id == workspace_id,
                        TrelloClientMapping.source_id == source.id,
                    )
                )
            ).all()
        )
        mapping_ids: dict[tuple[str, str], UUID] = {
            (m.mapping_type, m.external_ref.strip().casefold()): m.client_id
            for m in mappings
        }

        cards = list(
            (
                await self.db.scalars(
                    select(TrelloCard)
                    .where(
                        TrelloCard.workspace_id == workspace_id,
                        TrelloCard.source_id == source.id,
                    )
                    .order_by(TrelloCard.id)
                )
            ).all()
        )

        if mappings:
            for card in cards:
                resolved_id = resolve_card_client_id(
                    card.labels or [],
                    card.list_name,
                    source.trello_board_id,
                    mapping_ids,
                )
                if card.client_id != resolved_id:
                    card.client_id = resolved_id

        clients_by_id: dict[UUID, TrelloClientRecord] = {
            c.id: c
            for c in (
                await self.db.scalars(
                    select(TrelloClientRecord).where(
                        TrelloClientRecord.workspace_id == workspace_id
                    )
                )
            ).all()
        }

        card_ids = [card.id for card in cards]
        comments_by_card: dict[UUID, list[TrelloComment]] = {}
        if card_ids:
            comments = list(
                (
                    await self.db.scalars(
                        select(TrelloComment)
                        .where(
                            TrelloComment.workspace_id == workspace_id,
                            TrelloComment.card_id.in_(card_ids),
                        )
                        .order_by(
                            TrelloComment.created_at_trello,
                            TrelloComment.trello_action_id,
                            TrelloComment.id,
                        )
                    )
                ).all()
            )
            for comment in comments:
                comments_by_card.setdefault(comment.card_id, []).append(comment)

        members_by_ext: dict[str, TrelloMember] = {
            m.trello_member_id: m
            for m in (
                await self.db.scalars(
                    select(TrelloMember).where(
                        TrelloMember.workspace_id == workspace_id
                    )
                )
            ).all()
        }

        # Phase (a): Diff chunks per document (savepoint per card), clear stale model embeddings,
        # delete stale card summaries, and commit Phase (a) before any Gemini call.
        for card in cards:
            try:
                async with self.db.begin_nested():
                    await self._diff_card_chunks(
                        workspace_id=workspace_id,
                        source=source,
                        card=card,
                        card_comments=comments_by_card.get(card.id, []),
                        clients_by_id=clients_by_id,
                        members_by_ext=members_by_ext,
                        force=force,
                        result=result,
                    )
            except Exception as exc:
                result.failed_documents += 1
                logger.warning(
                    "index_source_card_failed",
                    workspace_id=str(workspace_id),
                    source_id=str(source.id),
                    card_id=str(card.id),
                    error_type=type(exc).__name__,
                )

        await self._clear_stale_model_embeddings(
            workspace_id=workspace_id,
            source_id=source.id,
            repository_id=None,
            result=result,
        )
        pending_chunks = await self._load_pending_chunks(
            workspace_id=workspace_id,
            source_id=source.id,
            repository_id=None,
            result=result,
        )
        pending_summaries = await self._prepare_card_summaries(
            workspace_id=workspace_id,
            cards=cards,
            comments_by_card=comments_by_card,
            result=result,
        )
        await self.db.commit()

        # Phase (b): Embed unembedded chunks in batches with no open transaction during Gemini calls,
        # committing each batch separately.
        await self._embed_pending_chunks(
            workspace_id=workspace_id,
            source_id=source.id,
            repository_id=None,
            result=result,
            preloaded_pending=pending_chunks,
        )

        # Phase (c): Generate card summaries outside any transaction, inserting and committing per card.
        await self._refresh_card_summaries(
            workspace_id=workspace_id,
            source_id=source.id,
            cards=cards,
            comments_by_card=comments_by_card,
            result=result,
            preloaded_missing=pending_summaries,
        )

        if result.inserted > 0 or result.updated > 0 or result.deleted > 0 or result.embedded > 0:
            await self.increment_data_version(workspace_id)

        return result

    async def _diff_card_chunks(
        self,
        *,
        workspace_id: UUID,
        source: TrelloSource,
        card: TrelloCard,
        card_comments: list[TrelloComment],
        clients_by_id: dict[UUID, TrelloClientRecord],
        members_by_ext: dict[str, TrelloMember],
        force: bool,
        result: IndexingResult,
    ) -> None:
        client_name = (
            clients_by_id[card.client_id].name
            if card.client_id is not None and card.client_id in clients_by_id
            else None
        )
        label_names = [
            str(lbl.get("name", "")).strip()
            for lbl in (card.labels or [])
            if isinstance(lbl, dict) and str(lbl.get("name", "")).strip()
        ]
        body_input = CardBodyInput(
            client_name=client_name,
            board_name=source.name,
            list_name=card.list_name,
            card_title=card.name,
            description=card.description or "",
            labels=label_names,
            checklists=(),
            occurred_at=card.last_activity_at,
            metadata={
                "card_id": str(card.id),
                "trello_card_id": card.trello_card_id,
                "list_id": card.list_id,
                "list_name": card.list_name,
                "labels": label_names,
                "closed": card.closed,
                "url": card.url,
            },
        )
        body_chunks = chunk_card_body(body_input)

        comment_inputs = [
            CommentInput(
                comment_id=str(c.id),
                author_name=(
                    (
                        members_by_ext[c.author_id].full_name
                        or members_by_ext[c.author_id].username
                    )
                    if c.author_id in members_by_ext
                    else (c.author_id or "Unknown")
                ),
                created_at=c.created_at_trello,
                text=c.text,
            )
            for c in card_comments
        ]
        comment_chunks = chunk_comments(
            comment_inputs,
            client_name=client_name,
            board_name=source.name,
            list_name=card.list_name,
            card_title=card.name,
        )

        desired_by_key: dict[tuple[UUID, str, int], Chunk] = {
            (card.id, ch.kind, ch.ordinal): ch
            for ch in (*body_chunks, *comment_chunks)
        }

        existing_rows = list(
            (
                await self.db.scalars(
                    select(ContextChunkRecord).where(
                        ContextChunkRecord.workspace_id == workspace_id,
                        ContextChunkRecord.card_id == card.id,
                    )
                )
            ).all()
        )
        existing_by_key: dict[tuple[UUID, str, int], ContextChunkRecord] = {
            (card.id, row.chunk_kind, row.ordinal): row
            for row in existing_rows
        }

        for key, row in existing_by_key.items():
            if key not in desired_by_key:
                await self.db.delete(row)
                result.deleted += 1

        target_model = settings.GEMINI_EMBEDDING_MODEL

        for key, ch in desired_by_key.items():
            existing_row = existing_by_key.get(key)
            if existing_row is None:
                self.db.add(
                    ContextChunkRecord(
                        workspace_id=workspace_id,
                        client_id=card.client_id,
                        source_id=source.id,
                        repository_id=None,
                        source_type="trello",
                        card_id=card.id,
                        group_key=None,
                        chunk_kind=ch.kind,
                        ordinal=ch.ordinal,
                        text=ch.text,
                        token_estimate=ch.token_estimate,
                        embedding=None,
                        embedding_model=None,
                        chunker_version=CHUNKER_VERSION,
                        content_hash=ch.content_hash,
                        occurred_at=ch.occurred_at,
                        chunk_metadata=ch.metadata,
                    )
                )
                result.inserted += 1
            elif (
                existing_row.content_hash != ch.content_hash
                or existing_row.chunker_version != CHUNKER_VERSION
            ):
                existing_row.text = ch.text
                existing_row.token_estimate = ch.token_estimate
                existing_row.chunker_version = CHUNKER_VERSION
                existing_row.content_hash = ch.content_hash
                existing_row.occurred_at = ch.occurred_at
                existing_row.chunk_metadata = ch.metadata
                existing_row.client_id = card.client_id
                existing_row.source_id = source.id
                existing_row.embedding = None
                existing_row.embedding_model = None
                result.updated += 1
            else:
                changed = False
                if existing_row.client_id != card.client_id:
                    existing_row.client_id = card.client_id
                    changed = True
                if existing_row.source_id != source.id:
                    existing_row.source_id = source.id
                    changed = True
                if force or (
                    existing_row.embedding is not None
                    and existing_row.embedding_model != target_model
                ):
                    existing_row.embedding = None
                    existing_row.embedding_model = None
                    changed = True
                if changed:
                    result.updated += 1
                else:
                    result.unchanged += 1

        await self.db.flush()

    async def _prepare_card_summaries(
        self,
        *,
        workspace_id: UUID,
        cards: list[TrelloCard],
        comments_by_card: dict[UUID, list[TrelloComment]],
        result: IndexingResult,
    ) -> list[tuple[UUID, str, str]]:
        if not cards:
            return []

        card_ids = [card.id for card in cards]
        # Delete stale summaries for older content hashes of each card
        for card in cards:
            del_res = await self.db.execute(
                delete(TrelloCardSummary).where(
                    TrelloCardSummary.workspace_id == workspace_id,
                    TrelloCardSummary.card_id == card.id,
                    TrelloCardSummary.content_hash != card.content_hash,
                )
            )
            result.summaries_deleted += int(getattr(del_res, "rowcount", 0) or 0)
        await self.db.flush()

        existing_pairs = {
            (row.card_id, row.content_hash)
            for row in (
                await self.db.execute(
                    select(
                        TrelloCardSummary.card_id,
                        TrelloCardSummary.content_hash,
                    ).where(
                        TrelloCardSummary.workspace_id == workspace_id,
                        TrelloCardSummary.card_id.in_(card_ids),
                        TrelloCardSummary.model == settings.GEMINI_CONTEXT_MODEL,
                        TrelloCardSummary.prompt_version == SUMMARY_PROMPT_VERSION,
                    )
                )
            ).all()
        }

        missing_cards = [
            card for card in cards if (card.id, card.content_hash) not in existing_pairs
        ]
        if not missing_cards:
            return []

        max_summaries = max(1, int(settings.INDEX_MAX_SUMMARIES_PER_RUN))
        if len(missing_cards) > max_summaries:
            result.has_more_summaries = True
            missing_cards = missing_cards[:max_summaries]

        return [
            (
                card.id,
                card.content_hash,
                _format_card_summary_source_text(card, comments_by_card.get(card.id, [])),
            )
            for card in missing_cards
        ]

    async def _refresh_card_summaries(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID,
        cards: list[TrelloCard],
        comments_by_card: dict[UUID, list[TrelloComment]],
        result: IndexingResult,
        preloaded_missing: list[tuple[UUID, str, str]] | None = None,
    ) -> None:
        if preloaded_missing is None:
            preloaded_missing = await self._prepare_card_summaries(
                workspace_id=workspace_id,
                cards=cards,
                comments_by_card=comments_by_card,
                result=result,
            )
            if self.db.in_transaction():
                await self.db.commit()

        if not preloaded_missing:
            return

        try:
            gemini = self._build_gemini_for_summarize()
        except Exception as exc:
            result.has_more_summaries = False
            logger.warning(
                "index_summaries_client_unavailable",
                workspace_id=str(workspace_id),
                source_id=str(source_id),
                missing_count=len(preloaded_missing),
                error_type=type(exc).__name__,
            )
            return

        if gemini is None:
            result.has_more_summaries = False
            return

        if self.db.in_transaction():
            await self.db.commit()

        for card_id, content_hash, source_text in preloaded_missing:
            try:
                summarize_fn = getattr(gemini, "summarize", None)
                if summarize_fn is None:
                    continue
                if self.db.in_transaction():
                    await self.db.commit()
                if type(gemini).summarize is not _ORIG_SUMMARIZE:
                    async with gemini.semaphore:
                        summary_text, input_tokens, output_tokens = await gemini.summarize(
                            source_text
                        )
                else:
                    summary_text, input_tokens, output_tokens = await gemini.summarize(
                        source_text
                    )
                stmt = (
                    insert(TrelloCardSummary)
                    .values(
                        workspace_id=workspace_id,
                        card_id=card_id,
                        content_hash=content_hash,
                        model=settings.GEMINI_CONTEXT_MODEL,
                        prompt_version=SUMMARY_PROMPT_VERSION,
                        summary=summary_text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    .on_conflict_do_nothing(constraint="uq_card_summaries_cache_key")
                    .returning(TrelloCardSummary.id)
                )
                inserted_id = await self.db.scalar(stmt)
                await self.db.commit()
                if inserted_id is not None:
                    result.summaries_generated += 1
                if self._on_batch_complete is not None:
                    await self._on_batch_complete()
            except Exception as exc:
                if self.db.in_transaction():
                    await self.db.rollback()
                logger.warning(
                    "index_card_summary_failed",
                    workspace_id=str(workspace_id),
                    source_id=str(source_id),
                    card_id=str(card_id),
                    error_type=type(exc).__name__,
                )

    async def index_repository(
        self,
        repository_id: UUID,
        *,
        force: bool = False,
    ) -> IndexingResult:
        """Index a GitHub repository in separate phases: (a) diff + commit, (b) embed per batch."""
        result = IndexingResult()
        repo = await self.db.scalar(
            select(GithubRepository).where(GithubRepository.id == repository_id)
        )
        if repo is None:
            if self.db.in_transaction():
                await self.db.commit()
            return result

        workspace_id = repo.workspace_id
        client_name: str | None = None
        if repo.client_id is not None:
            client_record = await self.db.scalar(
                select(TrelloClientRecord).where(
                    TrelloClientRecord.workspace_id == workspace_id,
                    TrelloClientRecord.id == repo.client_id,
                )
            )
            if client_record is not None:
                client_name = client_record.name

        commits = list(
            (
                await self.db.scalars(
                    select(GithubCommit)
                    .where(
                        GithubCommit.workspace_id == workspace_id,
                        GithubCommit.repository_id == repo.id,
                    )
                    .order_by(GithubCommit.committed_at, GithubCommit.sha, GithubCommit.id)
                )
            ).all()
        )

        commit_inputs = [
            CommitInput(
                commit_id=str(c.id),
                sha=c.sha,
                author_name=c.author_name or c.author_login or "Unknown",
                committed_at=c.committed_at,
                message=c.message,
            )
            for c in commits
        ]

        # Phase (a): Diff chunks per repository inside savepoint, clear stale model embeddings, and commit.
        try:
            async with self.db.begin_nested():
                desired_chunks = chunk_commits(
                    commit_inputs,
                    client_name=client_name,
                    repo_name=repo.full_name,
                )
                desired_by_key: dict[tuple[UUID, str, str, int], Chunk] = {
                    (repo.id, ch.kind, str(ch.group_key), ch.ordinal): ch
                    for ch in desired_chunks
                    if ch.group_key is not None
                }

                existing_rows = list(
                    (
                        await self.db.scalars(
                            select(ContextChunkRecord).where(
                                ContextChunkRecord.workspace_id == workspace_id,
                                ContextChunkRecord.repository_id == repo.id,
                            )
                        )
                    ).all()
                )
                existing_by_key: dict[tuple[UUID, str, str, int], ContextChunkRecord] = {
                    (repo.id, row.chunk_kind, str(row.group_key), row.ordinal): row
                    for row in existing_rows
                    if row.group_key is not None
                }

                for key, row in existing_by_key.items():
                    if key not in desired_by_key:
                        await self.db.delete(row)
                        result.deleted += 1

                target_model = settings.GEMINI_EMBEDDING_MODEL

                for key, ch in desired_by_key.items():
                    existing_row = existing_by_key.get(key)
                    if existing_row is None:
                        self.db.add(
                            ContextChunkRecord(
                                workspace_id=workspace_id,
                                client_id=repo.client_id,
                                source_id=None,
                                repository_id=repo.id,
                                source_type="github",
                                card_id=None,
                                group_key=ch.group_key,
                                chunk_kind=ch.kind,
                                ordinal=ch.ordinal,
                                text=ch.text,
                                token_estimate=ch.token_estimate,
                                embedding=None,
                                embedding_model=None,
                                chunker_version=CHUNKER_VERSION,
                                content_hash=ch.content_hash,
                                occurred_at=ch.occurred_at,
                                chunk_metadata=ch.metadata,
                            )
                        )
                        result.inserted += 1
                    elif (
                        existing_row.content_hash != ch.content_hash
                        or existing_row.chunker_version != CHUNKER_VERSION
                    ):
                        existing_row.text = ch.text
                        existing_row.token_estimate = ch.token_estimate
                        existing_row.chunker_version = CHUNKER_VERSION
                        existing_row.content_hash = ch.content_hash
                        existing_row.occurred_at = ch.occurred_at
                        existing_row.chunk_metadata = ch.metadata
                        existing_row.client_id = repo.client_id
                        existing_row.embedding = None
                        existing_row.embedding_model = None
                        result.updated += 1
                    else:
                        changed = False
                        if existing_row.client_id != repo.client_id:
                            existing_row.client_id = repo.client_id
                            changed = True
                        if force or (
                            existing_row.embedding is not None
                            and existing_row.embedding_model != target_model
                        ):
                            existing_row.embedding = None
                            existing_row.embedding_model = None
                            changed = True
                        if changed:
                            result.updated += 1
                        else:
                            result.unchanged += 1

                await self.db.flush()
        except Exception as exc:
            result.failed_documents += 1
            logger.warning(
                "index_repository_diff_failed",
                workspace_id=str(workspace_id),
                repository_id=str(repo.id),
                error_type=type(exc).__name__,
            )

        await self._clear_stale_model_embeddings(
            workspace_id=workspace_id,
            source_id=None,
            repository_id=repo.id,
            result=result,
        )
        pending_chunks = await self._load_pending_chunks(
            workspace_id=workspace_id,
            source_id=None,
            repository_id=repo.id,
            result=result,
        )
        await self.db.commit()

        # Phase (b): Embed pending chunks in batches with no open transaction during Gemini calls.
        await self._embed_pending_chunks(
            workspace_id=workspace_id,
            source_id=None,
            repository_id=repo.id,
            result=result,
            preloaded_pending=pending_chunks,
        )

        if result.inserted > 0 or result.updated > 0 or result.deleted > 0 or result.embedded > 0:
            await self.increment_data_version(workspace_id)

        return result

    async def _clear_stale_model_embeddings(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID | None,
        repository_id: UUID | None,
        result: IndexingResult,
    ) -> None:
        target_model = settings.GEMINI_EMBEDDING_MODEL
        stale_model_stmt = (
            update(ContextChunkRecord)
            .where(
                ContextChunkRecord.workspace_id == workspace_id,
                ContextChunkRecord.embedding.is_not(None),
                ContextChunkRecord.embedding_model.is_distinct_from(target_model),
            )
            .values(embedding=None, embedding_model=None)
        )
        if source_id is not None:
            stale_model_stmt = stale_model_stmt.where(ContextChunkRecord.source_id == source_id)
        if repository_id is not None:
            stale_model_stmt = stale_model_stmt.where(
                ContextChunkRecord.repository_id == repository_id
            )
        stale_res = await self.db.execute(stale_model_stmt)
        stale_cleared = int(getattr(stale_res, "rowcount", 0) or 0)
        if stale_cleared > 0:
            result.updated += stale_cleared
            await self.db.flush()

    async def _load_pending_chunks(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID | None,
        repository_id: UUID | None,
        result: IndexingResult,
    ) -> list[ContextChunkRecord]:
        max_embed = max(1, int(settings.INDEX_MAX_EMBED_PER_RUN))
        unembedded_stmt = select(ContextChunkRecord).where(
            ContextChunkRecord.workspace_id == workspace_id,
            ContextChunkRecord.embedding.is_(None),
        )
        if source_id is not None:
            unembedded_stmt = unembedded_stmt.where(ContextChunkRecord.source_id == source_id)
        if repository_id is not None:
            unembedded_stmt = unembedded_stmt.where(
                ContextChunkRecord.repository_id == repository_id
            )
        unembedded_stmt = unembedded_stmt.order_by(
            ContextChunkRecord.card_id.nulls_last(),
            ContextChunkRecord.group_key.nulls_first(),
            ContextChunkRecord.chunk_kind,
            ContextChunkRecord.ordinal,
            ContextChunkRecord.id,
        ).limit(max_embed + 1)

        rows = list((await self.db.scalars(unembedded_stmt)).all())
        if len(rows) > max_embed:
            result.has_more_embeddings = True
            rows = rows[:max_embed]
        return rows

    async def _embed_pending_chunks(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID | None,
        repository_id: UUID | None,
        result: IndexingResult,
        preloaded_pending: list[ContextChunkRecord] | None = None,
    ) -> None:
        target_model = settings.GEMINI_EMBEDDING_MODEL

        if preloaded_pending is None:
            await self._clear_stale_model_embeddings(
                workspace_id=workspace_id,
                source_id=source_id,
                repository_id=repository_id,
                result=result,
            )
            pending = await self._load_pending_chunks(
                workspace_id=workspace_id,
                source_id=source_id,
                repository_id=repository_id,
                result=result,
            )
            if self.db.in_transaction():
                await self.db.commit()
        else:
            pending = preloaded_pending

        if not pending:
            return

        try:
            gemini = self._build_gemini_for_embed()
        except Exception as exc:
            result.failed_batches += 1
            result.has_more_embeddings = False
            logger.warning(
                "index_embed_client_unavailable",
                workspace_id=str(workspace_id),
                source_id=str(source_id) if source_id else None,
                repository_id=str(repository_id) if repository_id else None,
                pending_count=len(pending),
                error_type=type(exc).__name__,
            )
            return

        if gemini is None:
            result.has_more_embeddings = False
            return

        if self.db.in_transaction():
            await self.db.commit()

        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            try:
                if self.db.in_transaction():
                    await self.db.commit()
                vectors = await gemini.embed_batch([row.text for row in batch])
                if len(vectors) != len(batch):
                    raise EmbeddingUnavailable(
                        "Gemini returned a batch with mismatched vector count."
                    )
                for row, vector in zip(batch, vectors, strict=True):
                    row.embedding = vector
                    row.embedding_model = target_model
                await self.db.commit()
                result.embedded += len(batch)
                if self._on_batch_complete is not None:
                    await self._on_batch_complete()
            except Exception as exc:
                if self.db.in_transaction():
                    await self.db.rollback()
                result.failed_batches += 1
                logger.warning(
                    "index_embed_batch_failed",
                    workspace_id=str(workspace_id),
                    source_id=str(source_id) if source_id else None,
                    repository_id=str(repository_id) if repository_id else None,
                    batch_size=len(batch),
                    error_type=type(exc).__name__,
                )

    async def remap_card_client(
        self,
        workspace_id: UUID,
        card_id: UUID,
        new_client_id: UUID | None,
    ) -> int:
        """Update a card's client_id and its chunks.client_id in the same transaction."""
        card = await self.db.scalar(
            select(TrelloCard).where(
                TrelloCard.workspace_id == workspace_id,
                TrelloCard.id == card_id,
            )
        )
        if card is None:
            return 0
        card.client_id = new_client_id
        upd = await self.db.execute(
            update(ContextChunkRecord)
            .where(
                ContextChunkRecord.workspace_id == workspace_id,
                ContextChunkRecord.card_id == card_id,
                ContextChunkRecord.client_id.is_distinct_from(new_client_id),
            )
            .values(client_id=new_client_id)
        )
        await self.db.flush()
        updated_rows = int(getattr(upd, "rowcount", 0) or 0)
        if updated_rows > 0:
            await self.increment_data_version(workspace_id)
        return updated_rows

    async def remap_repository_client(
        self,
        workspace_id: UUID,
        repository_id: UUID,
        new_client_id: UUID | None,
    ) -> int:
        """Update a repository's client_id and its chunks.client_id in the same transaction."""
        repo = await self.db.scalar(
            select(GithubRepository).where(
                GithubRepository.workspace_id == workspace_id,
                GithubRepository.id == repository_id,
            )
        )
        if repo is None:
            return 0
        repo.client_id = new_client_id
        upd = await self.db.execute(
            update(ContextChunkRecord)
            .where(
                ContextChunkRecord.workspace_id == workspace_id,
                ContextChunkRecord.repository_id == repository_id,
                ContextChunkRecord.client_id.is_distinct_from(new_client_id),
            )
            .values(client_id=new_client_id)
        )
        await self.db.flush()
        updated_rows = int(getattr(upd, "rowcount", 0) or 0)
        if updated_rows > 0:
            await self.increment_data_version(workspace_id)
        return updated_rows

    async def rename_client(
        self,
        workspace_id: UUID,
        client_id: UUID,
        new_name: str,
    ) -> dict[str, list[UUID]]:
        """Rename a client and enqueue index tasks for affected sources and repositories."""
        from app.workers.tasks import (
            dispatch_task,
            index_repository_task,
            index_source_task,
        )

        clean_name = new_name.strip()
        client = await self.db.scalar(
            select(TrelloClientRecord).where(
                TrelloClientRecord.workspace_id == workspace_id,
                TrelloClientRecord.id == client_id,
            )
        )
        if client is None or not clean_name:
            return {"sources": [], "repositories": []}

        if client.name == clean_name:
            return {"sources": [], "repositories": []}

        client.name = clean_name
        await self.db.flush()

        card_source_ids = set(
            (
                await self.db.scalars(
                    select(TrelloCard.source_id)
                    .where(
                        TrelloCard.workspace_id == workspace_id,
                        TrelloCard.client_id == client_id,
                    )
                    .distinct()
                )
            ).all()
        )
        mapping_source_ids = set(
            (
                await self.db.scalars(
                    select(TrelloClientMapping.source_id)
                    .where(
                        TrelloClientMapping.workspace_id == workspace_id,
                        TrelloClientMapping.client_id == client_id,
                    )
                    .distinct()
                )
            ).all()
        )
        chunk_source_ids = set(
            (
                await self.db.scalars(
                    select(ContextChunkRecord.source_id)
                    .where(
                        ContextChunkRecord.workspace_id == workspace_id,
                        ContextChunkRecord.client_id == client_id,
                        ContextChunkRecord.source_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
        )
        affected_sources = sorted(
            (card_source_ids | mapping_source_ids | {s for s in chunk_source_ids if s is not None}),
            key=str,
        )

        repo_ids = set(
            (
                await self.db.scalars(
                    select(GithubRepository.id).where(
                        GithubRepository.workspace_id == workspace_id,
                        GithubRepository.client_id == client_id,
                    )
                )
            ).all()
        )
        chunk_repo_ids = set(
            (
                await self.db.scalars(
                    select(ContextChunkRecord.repository_id)
                    .where(
                        ContextChunkRecord.workspace_id == workspace_id,
                        ContextChunkRecord.client_id == client_id,
                        ContextChunkRecord.repository_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
        )
        affected_repos = sorted(
            repo_ids | {r for r in chunk_repo_ids if r is not None},
            key=str,
        )

        for sid in affected_sources:
            dispatch_task(index_source_task, str(sid))
        for rid in affected_repos:
            dispatch_task(index_repository_task, str(rid))

        return {"sources": affected_sources, "repositories": affected_repos}

    async def rename_board(
        self,
        workspace_id: UUID,
        source_id: UUID,
        new_name: str,
    ) -> bool:
        """Rename a Trello source (board) and enqueue index_source_task so chunk headers are rebuilt."""
        from app.workers.tasks import dispatch_task, index_source_task

        clean_name = new_name.strip()
        source = await self.db.scalar(
            select(TrelloSource).where(
                TrelloSource.workspace_id == workspace_id,
                TrelloSource.id == source_id,
            )
        )
        if source is None or not clean_name:
            return False
        if source.name == clean_name:
            return False
        source.name = clean_name
        await self.db.flush()
        dispatch_task(index_source_task, str(source.id))
        return True
