import math
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.context.gemini import GeminiContextClient
from app.modules.context.models import TrelloCardEmbedding, TrelloCardSummary
from app.modules.context.schemas import (
    CardSummaryResponse,
    ContextAccount,
    ContextChunk,
    ContextClient,
    ContextIndexResponse,
    ContextItem,
    ContextMember,
    ContextSearchResponse,
    ContextSource,
    ContextSummariesResponse,
    SimilarCardResponse,
    WorkspaceContextResponse,
)
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientRecord,
    TrelloComment,
    TrelloMember,
    TrelloSource,
)
from app.modules.workspaces.models import Workspace

SUMMARY_PROMPT_VERSION = "v1"
MemberRoleTag = Literal["unknown", "client", "internal"]


class WorkspaceContextService:
    """Build an ordered, workspace-scoped context snapshot from connected sources."""

    def __init__(self, db: AsyncSession, workspace: Workspace) -> None:
        self.db = db
        self.workspace = workspace

    async def build(
        self,
        *,
        client_id: UUID | None,
        max_tokens: int,
    ) -> WorkspaceContextResponse:
        accounts = await self._load_accounts()
        sources = await self._load_sources()
        github_sources = await self._load_github_sources(client_id)
        source_ids = [source.id for source, _ in sources]
        cards = await self._load_cards(source_ids, client_id)
        clients_by_id = await self._load_clients(cards)
        github_client_ids = {
            repository.client_id
            for repository, _ in github_sources
            if repository.client_id is not None
        }
        missing_github_client_ids = github_client_ids - clients_by_id.keys()
        if missing_github_client_ids:
            result = await self.db.scalars(
                select(TrelloClientRecord).where(
                    TrelloClientRecord.workspace_id == self.workspace.id,
                    TrelloClientRecord.id.in_(missing_github_client_ids),
                )
            )
            clients_by_id.update({client.id: client for client in result.all()})
        card_ids = [card.id for card in cards]
        comments = await self._load_comments(card_ids)
        members_by_id = await self._load_members()
        summaries_by_card_id = await self._load_summaries(cards)

        if client_id is not None and not any(card.client_id == client_id for card in cards):
            client_exists = await self.db.scalar(
                select(TrelloClientRecord.id).where(
                    TrelloClientRecord.id == client_id,
                    TrelloClientRecord.workspace_id == self.workspace.id,
                )
            )
            if client_exists is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Client not found in this workspace.",
                )

        context_sources = [
            ContextSource(
                id=source.id,
                provider="trello",
                name=source.name,
                url=source.url,
                account_name=account_name,
                sync_status=source.sync_status,
                last_synced_at=source.last_synced_at,
                sync_error=source.sync_error,
            )
            for source, account_name in sources
        ]
        context_sources.extend(
            ContextSource(
                id=repository.id,
                provider="github",
                name=repository.full_name,
                url=repository.url,
                account_name=account_name,
                sync_status=repository.sync_status,
                last_synced_at=repository.last_synced_at,
                sync_error=repository.sync_error,
            )
            for repository, account_name in github_sources
        )
        source_by_id = {source.id: source for source, _ in sources}
        account_name_by_source = {source.id: account_name for source, account_name in sources}
        items: list[ContextItem] = []

        for source, _ in sources:
            items.append(
                ContextItem(
                    item_type="source",
                    source_id=source.id,
                    source_name=source.name,
                    title=source.name,
                    text=f"Trello board: {source.name}",
                    url=source.url,
                    metadata={
                        "provider": "trello",
                        "account_name": account_name_by_source[source.id],
                        "sync_status": source.sync_status,
                    },
                )
            )

        github_repo_ids = [repository.id for repository, _ in github_sources]
        for repository, account_name in github_sources:
            items.append(
                ContextItem(
                    item_type="source",
                    source_id=repository.id,
                    source_name=repository.full_name,
                    title=repository.full_name,
                    text=f"GitHub repository: {repository.full_name}",
                    url=repository.url,
                    metadata={
                        "provider": "github",
                        "account_name": account_name,
                        "default_branch": repository.default_branch,
                        "private": repository.private,
                        "client_id": str(repository.client_id) if repository.client_id else None,
                    },
                )
            )
        if github_repo_ids:
            commit_result = await self.db.scalars(
                select(GithubCommit)
                .where(
                    GithubCommit.workspace_id == self.workspace.id,
                    GithubCommit.repository_id.in_(github_repo_ids),
                )
                .order_by(GithubCommit.committed_at.desc(), GithubCommit.sha)
                .limit(1000)
            )
            repository_by_id = {
                repository.id: (repository, account_name)
                for repository, account_name in github_sources
            }
            for commit in commit_result.all():
                repository, _ = repository_by_id[commit.repository_id]
                message_lines = commit.message.splitlines()
                items.append(
                    ContextItem(
                        item_type="commit",
                        source_id=repository.id,
                        source_name=repository.full_name,
                        external_id=commit.sha,
                        client_id=repository.client_id,
                        client_name=(
                            clients_by_id[repository.client_id].name
                            if repository.client_id in clients_by_id
                            else None
                        ),
                        title=message_lines[0] if message_lines else commit.sha[:7],
                        text=commit.message,
                        url=commit.url,
                        occurred_at=commit.committed_at,
                        metadata={
                            "provider": "github",
                            "repository": repository.full_name,
                            "author": commit.author_name,
                            "author_login": commit.author_login,
                        },
                    )
                )

        comments_by_card: dict[UUID, list[TrelloComment]] = {}
        for comment in comments:
            comments_by_card.setdefault(comment.card_id, []).append(comment)

        for card in cards:
            source = source_by_id[card.source_id]
            client = clients_by_id.get(card.client_id) if card.client_id is not None else None
            member_names = [
                members_by_id[member_id].full_name or members_by_id[member_id].username
                for member_id in card.member_ids
                if member_id in members_by_id
            ]
            card_text = "\n".join(
                part
                for part in (
                    card.description.strip(),
                    f"List: {card.list_name}" if card.list_name else "",
                    "Labels: "
                    + ", ".join(label["name"] for label in card.labels if label.get("name"))
                    if card.labels
                    else "",
                    "Members: " + ", ".join(member_names) if member_names else "",
                )
                if part
            )
            items.append(
                ContextItem(
                    item_type="card",
                    source_id=source.id,
                    source_name=source.name,
                    client_id=client.id if client else None,
                    client_name=client.name if client else None,
                    card_id=card.id,
                    external_id=card.trello_card_id,
                    title=card.name,
                    text=card_text,
                    summary=summaries_by_card_id.get(card.id),
                    url=card.url,
                    occurred_at=card.last_activity_at,
                    metadata={
                        "list_id": card.list_id,
                        "list_name": card.list_name,
                        "labels": card.labels,
                        "member_ids": card.member_ids,
                        "due_at": card.due_at.isoformat() if card.due_at else None,
                        "closed": card.closed,
                    },
                )
            )
            for comment in comments_by_card.get(card.id, []):
                author = members_by_id.get(comment.author_id)
                items.append(
                    ContextItem(
                        item_type="comment",
                        source_id=source.id,
                        source_name=source.name,
                        client_id=client.id if client else None,
                        client_name=client.name if client else None,
                        card_id=card.id,
                        external_id=comment.trello_action_id,
                        title=card.name,
                        text=comment.text,
                        url=card.url,
                        occurred_at=comment.created_at_trello,
                        metadata={
                            "author_id": comment.author_id,
                            "author_name": (
                                author.full_name or author.username if author else "Unknown member"
                            ),
                        },
                    )
                )

        used_member_ids = {member_id for card in cards for member_id in card.member_ids}
        used_member_ids.update(comment.author_id for comment in comments if comment.author_id)
        if used_member_ids:
            for member in sorted(
                (
                    members_by_id[member_id]
                    for member_id in used_member_ids
                    if member_id in members_by_id
                ),
                key=lambda item: (item.full_name.casefold(), item.username.casefold()),
            ):
                items.append(
                    ContextItem(
                        item_type="person",
                        title=member.full_name or member.username,
                        text=member.full_name or member.username,
                        metadata={
                            "external_id": member.trello_member_id,
                            "username": member.username,
                            "classification": (
                                member.role_tag if member.role_tag != "unknown" else "unclassified"
                            ),
                        },
                    )
                )

        chunks = self._chunk_items(items, max_tokens)
        used_client_ids = {card.client_id for card in cards if card.client_id is not None}
        used_client_ids.update(
            repository.client_id
            for repository, _ in github_sources
            if repository.client_id is not None
        )
        context_clients = [
            ContextClient(id=client.id, name=client.name)
            for client in sorted(
                clients_by_id.values(),
                key=lambda item: item.name.casefold(),
            )
            if client.id in used_client_ids
        ]
        context_members = [
            ContextMember(
                id=member.id,
                external_id=member.trello_member_id,
                name=member.full_name or member.username,
                username=member.username,
                role_tag=cast(MemberRoleTag, member.role_tag),
            )
            for member in sorted(
                members_by_id.values(),
                key=lambda item: (item.full_name.casefold(), item.username.casefold()),
            )
            if member.trello_member_id in used_member_ids
        ]
        return WorkspaceContextResponse(
            workspace_id=self.workspace.id,
            workspace_name=self.workspace.name,
            generated_at=datetime.now(UTC),
            token_budget=max_tokens,
            estimated_tokens=sum(chunk.estimated_tokens for chunk in chunks),
            connected_accounts=accounts,
            sources=context_sources,
            clients=context_clients,
            members=context_members,
            item_count=len(items),
            chunks=chunks,
        )

    async def classify_member(
        self,
        member_id: UUID,
        role_tag: MemberRoleTag,
    ) -> ContextMember:
        member = await self.db.scalar(
            select(TrelloMember).where(
                TrelloMember.id == member_id,
                TrelloMember.workspace_id == self.workspace.id,
            )
        )
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this workspace.",
            )
        member.role_tag = role_tag
        await self.db.flush()
        return ContextMember(
            id=member.id,
            external_id=member.trello_member_id,
            name=member.full_name or member.username,
            username=member.username,
            role_tag=member.role_tag,
        )

    async def summarize_cards(
        self,
        *,
        client_id: UUID | None,
        max_cards: int,
    ) -> ContextSummariesResponse:
        cards = await self._load_included_cards(client_id)
        if client_id is not None and not cards:
            await self._validate_client(client_id)
        if not cards:
            return ContextSummariesResponse(
                processed=0,
                generated=0,
                cached=0,
                summaries=[],
            )
        cards = cards[:max_cards]
        comments = await self._load_comments([card.id for card in cards])
        comments_by_card: dict[UUID, list[TrelloComment]] = {}
        for comment in comments:
            comments_by_card.setdefault(comment.card_id, []).append(comment)

        results: list[CardSummaryResponse] = []
        generated = 0
        cached = 0
        async with AsyncExitStack() as stack:
            gemini: GeminiContextClient | None = None
            for card in cards:
                summary = await self.db.scalar(
                    select(TrelloCardSummary).where(
                        TrelloCardSummary.workspace_id == self.workspace.id,
                        TrelloCardSummary.card_id == card.id,
                        TrelloCardSummary.content_hash == card.content_hash,
                        TrelloCardSummary.model == settings.GEMINI_CONTEXT_MODEL,
                        TrelloCardSummary.prompt_version == SUMMARY_PROMPT_VERSION,
                    )
                )
                summary_text: str
                was_cached: bool
                if summary is None:
                    if gemini is None:
                        gemini = await stack.enter_async_context(GeminiContextClient())
                    source_text = self._card_source_text(card, comments_by_card.get(card.id, []))
                    text, input_tokens, output_tokens = await gemini.summarize(source_text)
                    statement = insert(TrelloCardSummary).values(
                        workspace_id=self.workspace.id,
                        card_id=card.id,
                        content_hash=card.content_hash,
                        model=settings.GEMINI_CONTEXT_MODEL,
                        prompt_version=SUMMARY_PROMPT_VERSION,
                        summary=text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    inserted_id = await self.db.scalar(
                        statement.on_conflict_do_nothing(
                            constraint="uq_card_summaries_cache_key"
                        ).returning(TrelloCardSummary.id)
                    )
                    if inserted_id is not None:
                        summary_text = text
                        generated += 1
                        was_cached = False
                    else:
                        summary = await self.db.scalar(
                            select(TrelloCardSummary).where(
                                TrelloCardSummary.workspace_id == self.workspace.id,
                                TrelloCardSummary.card_id == card.id,
                                TrelloCardSummary.content_hash == card.content_hash,
                                TrelloCardSummary.model == settings.GEMINI_CONTEXT_MODEL,
                                TrelloCardSummary.prompt_version == SUMMARY_PROMPT_VERSION,
                            )
                        )
                        if summary is None:
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Generated summary could not be saved.",
                            )
                        summary_text = summary.summary
                        cached += 1
                        was_cached = True
                else:
                    summary_text = summary.summary
                    cached += 1
                    was_cached = True
                results.append(
                    CardSummaryResponse(
                        card_id=card.id,
                        trello_card_id=card.trello_card_id,
                        title=card.name,
                        summary=summary_text,
                        content_hash=card.content_hash,
                        cached=was_cached,
                    )
                )
        return ContextSummariesResponse(
            processed=len(cards),
            generated=generated,
            cached=cached,
            summaries=results,
        )

    async def index_cards(
        self,
        *,
        client_id: UUID | None,
        max_cards: int,
    ) -> ContextIndexResponse:
        cards = await self._load_included_cards(client_id)
        if client_id is not None and not cards:
            await self._validate_client(client_id)
        if not cards:
            return ContextIndexResponse(indexed=0, already_indexed=0, remaining=0)

        current_keys = {
            (row.card_id, row.content_hash)
            for row in (
                await self.db.execute(
                    select(TrelloCardEmbedding.card_id, TrelloCardEmbedding.content_hash).where(
                        TrelloCardEmbedding.workspace_id == self.workspace.id,
                        TrelloCardEmbedding.model == settings.GEMINI_EMBEDDING_MODEL,
                        TrelloCardEmbedding.card_id.in_([card.id for card in cards]),
                    )
                )
            )
        }
        missing = [card for card in cards if (card.id, card.content_hash) not in current_keys]
        to_index = missing[:max_cards]
        if to_index:
            comments = await self._load_comments([card.id for card in to_index])
            comments_by_card: dict[UUID, list[TrelloComment]] = {}
            for comment in comments:
                comments_by_card.setdefault(comment.card_id, []).append(comment)
            async with GeminiContextClient() as gemini:
                for card in to_index:
                    vector = await gemini.embed(
                        self._card_source_text(card, comments_by_card.get(card.id, []))
                    )
                    statement = insert(TrelloCardEmbedding).values(
                        workspace_id=self.workspace.id,
                        card_id=card.id,
                        content_hash=card.content_hash,
                        model=settings.GEMINI_EMBEDDING_MODEL,
                        embedding=vector,
                    )
                    await self.db.execute(
                        statement.on_conflict_do_update(
                            constraint="uq_card_embeddings_cache_key",
                            set_={"embedding": statement.excluded.embedding},
                        )
                    )
        return ContextIndexResponse(
            indexed=len(to_index),
            already_indexed=len(cards) - len(missing),
            remaining=len(missing) - len(to_index),
        )

    async def search_similar(
        self,
        *,
        query: str,
        client_id: UUID | None,
        limit: int,
    ) -> ContextSearchResponse:
        if client_id is not None:
            await self._validate_client(client_id)
        sources = await self._load_sources()
        source_ids = [source.id for source, _ in sources]
        if not source_ids:
            return ContextSearchResponse(
                query=query,
                workspace_id=self.workspace.id,
                results=[],
            )
        has_indexed_cards = await self.db.scalar(
            select(TrelloCardEmbedding.id)
            .join(TrelloCard, TrelloCard.id == TrelloCardEmbedding.card_id)
            .join(TrelloSource, TrelloSource.id == TrelloCard.source_id)
            .where(
                TrelloCardEmbedding.workspace_id == self.workspace.id,
                TrelloCardEmbedding.model == settings.GEMINI_EMBEDDING_MODEL,
                TrelloCardEmbedding.content_hash == TrelloCard.content_hash,
                TrelloCard.workspace_id == self.workspace.id,
                TrelloSource.id.in_(source_ids),
            )
            .limit(1)
        )
        if has_indexed_cards is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Index this workspace's cards before searching related work.",
            )
        async with GeminiContextClient() as gemini:
            query_vector = await gemini.embed(query, query=True)

        distance = TrelloCardEmbedding.embedding.cosine_distance(query_vector)
        statement = (
            select(TrelloCard, TrelloClientRecord.name, distance.label("distance"))
            .join(TrelloCard, TrelloCard.id == TrelloCardEmbedding.card_id)
            .join(TrelloSource, TrelloSource.id == TrelloCard.source_id)
            .outerjoin(TrelloClientRecord, TrelloClientRecord.id == TrelloCard.client_id)
            .where(
                TrelloCardEmbedding.workspace_id == self.workspace.id,
                TrelloCard.workspace_id == self.workspace.id,
                TrelloCardEmbedding.model == settings.GEMINI_EMBEDDING_MODEL,
                TrelloCardEmbedding.content_hash == TrelloCard.content_hash,
                TrelloSource.id.in_(source_ids),
            )
        )
        if client_id is not None:
            statement = statement.where(TrelloCard.client_id == client_id)
        result = await self.db.execute(statement.order_by(distance).limit(limit))
        rows = result.all()
        search_results = [
            SimilarCardResponse(
                card_id=card.id,
                trello_card_id=card.trello_card_id,
                title=card.name,
                description=card.description,
                url=card.url,
                client_id=card.client_id,
                client_name=client_name,
                similarity=max(-1.0, min(1.0, 1.0 - float(distance_value))),
            )
            for card, client_name, distance_value in rows
        ]
        return ContextSearchResponse(
            query=query,
            workspace_id=self.workspace.id,
            results=search_results,
        )

    async def _load_included_cards(self, client_id: UUID | None) -> list[TrelloCard]:
        sources = await self._load_sources()
        source_ids = [source.id for source, _ in sources]
        cards = await self._load_cards(source_ids, client_id)
        return cards

    async def _validate_client(self, client_id: UUID) -> None:
        exists = await self.db.scalar(
            select(TrelloClientRecord.id).where(
                TrelloClientRecord.id == client_id,
                TrelloClientRecord.workspace_id == self.workspace.id,
            )
        )
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found in this workspace.",
            )

    @staticmethod
    def _card_source_text(card: TrelloCard, comments: list[TrelloComment]) -> str:
        pieces = [
            f"Title: {card.name}",
            f"Description: {card.description.strip()}",
            f"List: {card.list_name}",
            "Labels: " + ", ".join(label["name"] for label in card.labels if label.get("name")),
        ]
        pieces.extend(
            f"Comment ({comment.created_at_trello.isoformat()}): {comment.text}"
            for comment in comments
        )
        text = "\n".join(piece for piece in pieces if piece.strip())
        return text[:20000]

    async def _load_accounts(self) -> list[ContextAccount]:
        result = await self.db.execute(
            select(ProviderAccount)
            .join(
                WorkspaceConnection,
                WorkspaceConnection.provider_account_id == ProviderAccount.id,
            )
            .where(
                WorkspaceConnection.workspace_id == self.workspace.id,
                WorkspaceConnection.status == "active",
                ProviderAccount.status == "active",
            )
            .order_by(ProviderAccount.provider, ProviderAccount.external_username)
        )
        return [
            ContextAccount(
                id=account.id,
                provider=account.provider,
                account_name=account.external_username,
            )
            for account in result.scalars().unique().all()
        ]

    async def _load_sources(self) -> list[tuple[TrelloSource, str]]:
        result = await self.db.execute(
            select(TrelloSource, ProviderAccount.external_username)
            .join(
                WorkspaceConnection,
                WorkspaceConnection.id == TrelloSource.connection_id,
            )
            .join(
                ProviderAccount,
                ProviderAccount.id == WorkspaceConnection.provider_account_id,
            )
            .where(
                TrelloSource.workspace_id == self.workspace.id,
                TrelloSource.excluded.is_(False),
                WorkspaceConnection.workspace_id == self.workspace.id,
                WorkspaceConnection.provider == "trello",
                WorkspaceConnection.status == "active",
                ProviderAccount.status == "active",
            )
            .order_by(TrelloSource.name)
        )
        return [(source, account_name) for source, account_name in result.all()]

    async def _load_github_sources(
        self,
        client_id: UUID | None,
    ) -> list[tuple[GithubRepository, str]]:
        query = (
            select(GithubRepository, ProviderAccount.external_username)
            .join(
                WorkspaceConnection,
                WorkspaceConnection.id == GithubRepository.connection_id,
            )
            .join(
                ProviderAccount,
                ProviderAccount.id == WorkspaceConnection.provider_account_id,
            )
            .where(
                GithubRepository.workspace_id == self.workspace.id,
                GithubRepository.included.is_(True),
                WorkspaceConnection.workspace_id == self.workspace.id,
                WorkspaceConnection.provider == "github",
                WorkspaceConnection.status == "active",
                ProviderAccount.status == "active",
            )
        )
        if client_id is not None:
            query = query.where(GithubRepository.client_id == client_id)
        result = await self.db.execute(query.order_by(GithubRepository.full_name))
        return [(repository, account_name) for repository, account_name in result.all()]

    async def _load_cards(
        self,
        source_ids: list[UUID],
        client_id: UUID | None,
    ) -> list[TrelloCard]:
        if not source_ids:
            return []
        query = select(TrelloCard).where(
            TrelloCard.workspace_id == self.workspace.id,
            TrelloCard.source_id.in_(source_ids),
        )
        if client_id is not None:
            query = query.where(TrelloCard.client_id == client_id)
        result = await self.db.execute(
            query.order_by(TrelloCard.last_activity_at.desc().nullslast(), TrelloCard.name)
        )
        return list(result.scalars().all())

    async def _load_clients(
        self,
        cards: list[TrelloCard],
    ) -> dict[UUID, TrelloClientRecord]:
        client_ids = {card.client_id for card in cards if card.client_id is not None}
        if not client_ids:
            return {}
        result = await self.db.execute(
            select(TrelloClientRecord).where(
                TrelloClientRecord.workspace_id == self.workspace.id,
                TrelloClientRecord.id.in_(client_ids),
            )
        )
        return {client.id: client for client in result.scalars().all()}

    async def _load_comments(self, card_ids: list[UUID]) -> list[TrelloComment]:
        if not card_ids:
            return []
        result = await self.db.execute(
            select(TrelloComment)
            .where(
                TrelloComment.workspace_id == self.workspace.id,
                TrelloComment.card_id.in_(card_ids),
            )
            .order_by(TrelloComment.created_at_trello, TrelloComment.id)
        )
        return list(result.scalars().all())

    async def _load_summaries(self, cards: list[TrelloCard]) -> dict[UUID, str]:
        if not cards:
            return {}
        result = await self.db.execute(
            select(TrelloCardSummary).where(
                TrelloCardSummary.workspace_id == self.workspace.id,
                TrelloCardSummary.card_id.in_([card.id for card in cards]),
                TrelloCardSummary.model == settings.GEMINI_CONTEXT_MODEL,
                TrelloCardSummary.prompt_version == SUMMARY_PROMPT_VERSION,
            )
        )
        summaries = {
            (summary.card_id, summary.content_hash): summary.summary
            for summary in result.scalars().all()
        }
        return {
            card.id: summaries[(card.id, card.content_hash)]
            for card in cards
            if (card.id, card.content_hash) in summaries
        }

    async def _load_members(self) -> dict[str, TrelloMember]:
        result = await self.db.execute(
            select(TrelloMember)
            .where(TrelloMember.workspace_id == self.workspace.id)
            .order_by(TrelloMember.full_name)
        )
        return {member.trello_member_id: member for member in result.scalars().all()}

    @classmethod
    def _chunk_items(cls, items: list[ContextItem], max_tokens: int) -> list[ContextChunk]:
        chunks: list[ContextChunk] = []
        current_items: list[ContextItem] = []
        current_tokens = 0

        def flush() -> None:
            nonlocal current_items, current_tokens
            if current_items:
                chunks.append(
                    ContextChunk(
                        index=len(chunks) + 1,
                        estimated_tokens=current_tokens,
                        items=current_items,
                    )
                )
                current_items = []
                current_tokens = 0

        for item in items:
            for part in cls._fit_item(item, max_tokens):
                item_tokens = cls._estimate_tokens(part)
                if current_items and current_tokens + item_tokens > max_tokens:
                    flush()
                current_items.append(part)
                current_tokens += item_tokens
        flush()
        return chunks

    @classmethod
    def _fit_item(cls, item: ContextItem, max_tokens: int) -> list[ContextItem]:
        if cls._estimate_tokens(item) <= max_tokens:
            return [item]
        text = item.text
        parts: list[ContextItem] = []
        while text:
            low = 1
            high = len(text)
            fit = 0
            while low <= high:
                middle = (low + high) // 2
                candidate = item.model_copy(update={"text": text[:middle]})
                if cls._estimate_tokens(candidate) <= max_tokens:
                    fit = middle
                    low = middle + 1
                else:
                    high = middle - 1
            if fit == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Token budget is too small for a context item.",
                )
            parts.append(item.model_copy(update={"text": text[:fit]}))
            text = text[fit:]
        return parts

    @staticmethod
    def _estimate_tokens(item: ContextItem) -> int:
        serialized = item.model_dump_json()
        return max(1, math.ceil(len(serialized) / 4))
