import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.trello.client import TrelloClient
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientMapping,
    TrelloClientRecord,
    TrelloComment,
    TrelloMember,
    TrelloSource,
)


def _parse_trello_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


async def sync_source_data(
    db: AsyncSession,
    source: TrelloSource,
    client: TrelloClient,
) -> None:
    """Fetch and idempotently upsert a Trello board's cards, comments, and members."""
    board_id = source.trello_board_id
    workspace_id = source.workspace_id
    board, lists, cards, members, actions = await _fetch_board(client, board_id)

    if board.get("name"):
        source.name = str(board["name"])

    list_names = {
        str(item["id"]): str(item.get("name", ""))
        for item in lists
        if isinstance(item.get("id"), str)
    }
    mappings = list(
        (
            await db.execute(
                select(TrelloClientMapping).where(
                    TrelloClientMapping.workspace_id == workspace_id,
                    TrelloClientMapping.source_id == source.id,
                )
            )
        )
        .scalars()
        .all()
    )
    client_by_mapping = {mapping.id: mapping.client_id for mapping in mappings}
    mapping_ids: dict[tuple[str, str], uuid.UUID] = {}
    for mapping in mappings:
        normalized = mapping.external_ref.strip().casefold()
        mapping_ids[(mapping.mapping_type, normalized)] = client_by_mapping[mapping.id]

    comments_by_external_card: dict[str, list[dict[str, str]]] = {}
    for action in actions:
        data = action.get("data")
        if not isinstance(data, dict):
            continue
        action_card = data.get("card")
        if not isinstance(action_card, dict) or not isinstance(action_card.get("id"), str):
            continue
        comments_by_external_card.setdefault(action_card["id"], []).append(
            {
                "text": str(data.get("text", "")),
                "author_id": str(action.get("idMemberCreator", "")),
                "created_at": str(action.get("date", "")),
            }
        )

    card_values: list[dict[str, Any]] = []
    for card in cards:
        card_id = card.get("id")
        list_id = card.get("idList")
        if not isinstance(card_id, str) or not isinstance(list_id, str):
            continue
        labels = [
            {"id": str(label.get("id", "")), "name": str(label.get("name", ""))}
            for label in card.get("labels", [])
            if isinstance(label, dict)
        ]
        member_ids = [value for value in card.get("idMembers", []) if isinstance(value, str)]
        list_name = list_names.get(list_id, "")
        client_id = next(
            (
                mapping_ids[("label", label["name"].strip().casefold())]
                for label in sorted(labels, key=lambda item: item["name"].casefold())
                if ("label", label["name"].strip().casefold()) in mapping_ids
            ),
            None,
        )
        if client_id is None:
            client_id = mapping_ids.get(("list", list_name.strip().casefold()))
        if client_id is None:
            client_id = mapping_ids.get(("board", board_id.casefold()))

        content = {
            "name": str(card.get("name", "")),
            "description": str(card.get("desc", "")),
            "list_id": list_id,
            "list_name": list_name,
            "labels": labels,
            "member_ids": member_ids,
            "due_at": card.get("due"),
            "closed": bool(card.get("closed", False)),
        }
        card_values.append(
            {
                "workspace_id": workspace_id,
                "source_id": source.id,
                "client_id": client_id,
                "trello_card_id": card_id,
                **content,
                "due_at": _parse_trello_date(card.get("due")),
                "last_activity_at": _parse_trello_date(card.get("dateLastActivity")),
                "url": str(card.get("url", "")),
                "content_hash": hashlib.sha256(
                    json.dumps(
                        {
                            "card": content,
                            "comments": sorted(
                                comments_by_external_card.get(card_id, []),
                                key=lambda item: (
                                    item["created_at"],
                                    item["author_id"],
                                    item["text"],
                                ),
                            ),
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest(),
            }
        )
    if card_values:
        statement = insert(TrelloCard).values(card_values)
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_cards_workspace_external",
                set_={
                    column: getattr(statement.excluded, column)
                    for column in (
                        "source_id",
                        "client_id",
                        "name",
                        "description",
                        "list_id",
                        "list_name",
                        "labels",
                        "member_ids",
                        "due_at",
                        "last_activity_at",
                        "closed",
                        "url",
                        "content_hash",
                    )
                },
            )
        )

    synced_card_ids = {value["trello_card_id"] for value in card_values}
    stale_cards = delete(TrelloCard).where(TrelloCard.source_id == source.id)
    if synced_card_ids:
        stale_cards = stale_cards.where(TrelloCard.trello_card_id.not_in(synced_card_ids))
    await db.execute(stale_cards)

    if members:
        member_values = [
            {
                "workspace_id": workspace_id,
                "trello_member_id": str(member["id"]),
                "username": str(member.get("username", "")),
                "full_name": str(member.get("fullName", "")),
            }
            for member in members
            if isinstance(member.get("id"), str)
        ]
        if member_values:
            statement = insert(TrelloMember).values(member_values)
            await db.execute(
                statement.on_conflict_do_update(
                    constraint="uq_members_workspace_external",
                    set_={
                        "username": statement.excluded.username,
                        "full_name": statement.excluded.full_name,
                    },
                )
            )

    card_ids = {
        row.trello_card_id: row.id
        for row in (
            await db.execute(
                select(TrelloCard).where(
                    TrelloCard.workspace_id == workspace_id,
                    TrelloCard.source_id == source.id,
                )
            )
        )
        .scalars()
        .all()
    }
    comment_values = []
    for action in actions:
        data = action.get("data")
        action_id = action.get("id")
        if not isinstance(data, dict) or not isinstance(action_id, str):
            continue
        action_card = data.get("card")
        if not isinstance(action_card, dict) or not isinstance(action_card.get("id"), str):
            continue
        card_pk = card_ids.get(action_card["id"])
        if card_pk is None:
            continue
        creator = action.get("idMemberCreator")
        comment_values.append(
            {
                "workspace_id": workspace_id,
                "card_id": card_pk,
                "trello_action_id": action_id,
                "author_id": creator if isinstance(creator, str) else "",
                "text": str(data.get("text", "")),
                "created_at_trello": _parse_trello_date(action.get("date")) or datetime.now(UTC),
            }
        )
    if comment_values:
        statement = insert(TrelloComment).values(comment_values)
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_comments_workspace_action",
                set_={
                    "card_id": statement.excluded.card_id,
                    "author_id": statement.excluded.author_id,
                    "text": statement.excluded.text,
                    "created_at_trello": statement.excluded.created_at_trello,
                },
            )
        )

    if settings.TRELLO_WEBHOOK_CALLBACK_URL and not source.webhook_id:
        if not settings.TRELLO_WEBHOOK_CALLBACK_URL.startswith("https://"):
            raise ValueError("Trello webhook callback URL must use public HTTPS.")
        if not settings.TRELLO_WEBHOOK_SECRET:
            raise ValueError("Trello webhook secret is not configured.")
        webhook = await client.create_board_webhook(
            board_id,
            settings.TRELLO_WEBHOOK_CALLBACK_URL,
        )
        source.webhook_id = str(webhook["id"])


async def _fetch_board(
    client: TrelloClient,
    board_id: str,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    board = await client.get_board(board_id)
    lists = await client.list_board_lists(board_id)
    cards = await client.list_board_cards(board_id)
    members = await client.list_board_members(board_id)
    actions = await client.list_board_comments(board_id)
    return board, lists, cards, members, actions


async def enqueue_source_sync(source_id: uuid.UUID) -> None:
    from app.workers.tasks import sync_trello_source

    sync_trello_source.delay(str(source_id))


async def list_mapping_responses(db: AsyncSession, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            TrelloClientMapping.source_id,
            TrelloClientMapping.mapping_type,
            TrelloClientMapping.external_ref,
            TrelloClientRecord.name,
            TrelloSource.trello_board_id,
            TrelloSource.name.label("board_name"),
        )
        .join(TrelloClientRecord, TrelloClientMapping.client_id == TrelloClientRecord.id)
        .join(TrelloSource, TrelloClientMapping.source_id == TrelloSource.id)
        .where(TrelloClientMapping.workspace_id == workspace_id)
        .order_by(TrelloSource.name, TrelloClientRecord.name)
    )
    return [
        {
            "source_id": row.source_id,
            "board_id": row.trello_board_id,
            "board_name": row.board_name,
            "mapping_type": row.mapping_type,
            "external_ref": row.external_ref,
            "client_name": row.name,
        }
        for row in result
    ]


async def replace_client_mappings(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    mappings: list[dict[str, str]],
) -> int:
    sources = list(
        (
            await db.execute(
                select(TrelloSource).where(
                    TrelloSource.workspace_id == workspace_id,
                    TrelloSource.connection_id == connection_id,
                )
            )
        )
        .scalars()
        .all()
    )
    source_by_board = {source.trello_board_id: source for source in sources if not source.excluded}
    normalized_items: list[tuple[TrelloSource, str, str, str]] = []
    unique_keys: set[tuple[str, str, str]] = set()
    for item in mappings:
        source = source_by_board.get(item["board_id"])
        mapping_type = item["mapping_type"]
        external_ref = item["external_ref"].strip()
        client_name = item["client_name"].strip()
        if not source or not client_name or not external_ref:
            raise ValueError("Mappings must reference an included board and have complete values.")
        if mapping_type not in {"board", "label", "list"}:
            raise ValueError("Mapping type must be board, label, or list.")
        if mapping_type == "board":
            external_ref = source.trello_board_id
        unique_key = (str(source.id), mapping_type, external_ref.casefold())
        if unique_key in unique_keys:
            raise ValueError("A Trello value can only be mapped once per board.")
        unique_keys.add(unique_key)
        normalized_items.append((source, mapping_type, external_ref, client_name))

    source_ids = [source.id for source in sources]
    if source_ids:
        await db.execute(
            delete(TrelloClientMapping).where(
                TrelloClientMapping.workspace_id == workspace_id,
                TrelloClientMapping.source_id.in_(source_ids),
            )
        )
    client_ids: dict[str, uuid.UUID] = {}
    for _, _, _, name in normalized_items:
        if name.casefold() in client_ids:
            continue
        statement = (
            insert(TrelloClientRecord)
            .values(workspace_id=workspace_id, name=name)
            .on_conflict_do_update(
                constraint="uq_clients_workspace_name",
                set_={"name": name},
            )
            .returning(TrelloClientRecord.id)
        )
        result = await db.execute(statement)
        client_ids[name.casefold()] = result.scalar_one()
    if normalized_items:
        db.add_all(
            [
                TrelloClientMapping(
                    workspace_id=workspace_id,
                    source_id=source.id,
                    client_id=client_ids[client_name.casefold()],
                    mapping_type=mapping_type,
                    external_ref=external_ref,
                )
                for source, mapping_type, external_ref, client_name in normalized_items
            ]
        )
    await db.flush()
    return len(normalized_items)


async def sources_for_sync(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> list[TrelloSource]:
    result = await db.execute(
        select(TrelloSource).where(
            TrelloSource.workspace_id == workspace_id,
            TrelloSource.connection_id == connection_id,
            TrelloSource.excluded.is_(False),
        )
    )
    return list(result.scalars().all())
