"""Conversation and message persistence (D14, D17).

Named `store`, not `repository`: import-linter's `conversation-no-repository`
contract forbids `app.domains.conversation` from reaching
`app.domains.*.repository` (by shape), and that wildcard would also match a
`app.domains.conversation.repository` module if this one were named that.
This is conversation's own data (not bank data reached through the tools
registry), so it is read and written directly, over `app.core.db` -- the
only internal import this module takes.

D6: `app.messages.content` is Fernet-encrypted (`add_message` encrypts,
`list_messages` decrypts) and `content_masked` holds the tokenized text.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import get_engine
from app.domains.safety.vault import decrypt_text, encrypt_text

__all__ = [
    "ConversationRow",
    "MessageRow",
    "add_message",
    "close_conversation",
    "create_conversation",
    "get_conversation",
    "list_messages",
]


class ConversationRow(BaseModel):
    """One `app.conversations` row (frozen: this module is the only writer)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    customer_id: str
    language: str | None
    mode: str
    status: str


class MessageRow(BaseModel):
    """One `app.messages` row (frozen: this module is the only writer)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    conversation_id: UUID
    turn_id: UUID | None
    role: str
    content: str
    ui_payload: dict[str, Any] | list[dict[str, Any]] | None
    created_at: datetime


async def create_conversation(customer_id: str, language: str) -> UUID:
    """Insert one `app.conversations` row and return its id. The id is
    generated here, in Python (`uuid4()`), not by the database: the `id`
    column has no server default, same convention as `identity.provision`'s
    `account_id`.
    """
    conversation_id = uuid4()
    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO app.conversations (id, customer_id, language)
                VALUES (:id, :customer_id, :language)
                """
            ),
            {"id": conversation_id, "customer_id": customer_id, "language": language},
        )
    return conversation_id


async def close_conversation(conversation_id: UUID) -> None:
    """Mark a conversation `closed` once the customer said goodbye
    (`ui.conversation_closed`); `post_message` then refuses new turns on it.
    """
    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                "UPDATE app.conversations SET status = 'closed', closed_at = now() "
                "WHERE id = :conversation_id"
            ),
            {"conversation_id": conversation_id},
        )


async def get_conversation(conversation_id: UUID) -> ConversationRow | None:
    """One `app.conversations` row by id, or `None` if it doesn't exist."""
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, customer_id, language, mode, status
                FROM app.conversations
                WHERE id = :conversation_id
                """
            ),
            {"conversation_id": conversation_id},
        )
        row = result.mappings().first()
    if row is None:
        return None
    return ConversationRow(
        id=row["id"],
        customer_id=row["customer_id"],
        language=row["language"],
        mode=row["mode"],
        status=row["status"],
    )


async def add_message(
    conversation_id: UUID,
    turn_id: UUID,
    role: str,
    content: str,
    content_masked: str,
    ui_payload: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> UUID:
    """Insert one `app.messages` row and return its id. The id is generated
    here, in Python (`uuid4()`), not by the database (no server default,
    same convention as `create_conversation`). `content` is stored encrypted
    (D6); `content_masked` is the tokenized form, stored as is.

    `ui_payload` accepts a list too (T11): the turn runner persists the
    dumped `UIEvent` list as-is, one JSON array in the JSONB column, not
    wrapped in an object.
    """
    message_id = uuid4()
    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO app.messages (
                    id, conversation_id, turn_id, role, content, content_masked, ui_payload
                )
                VALUES (
                    :id, :conversation_id, :turn_id, :role, :content, :content_masked,
                    :ui_payload
                )
                """
            ).bindparams(
                # `ui_payload` needs an explicit JSONB bind type: asyncpg's
                # jsonb codec only accepts an already-encoded string, and a
                # bare Python dict param fails with an opaque `DataError`.
                bindparam("ui_payload", type_=JSONB)
            ),
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "role": role,
                "content": encrypt_text(content),
                "content_masked": content_masked,
                "ui_payload": ui_payload,
            },
        )
    return message_id


async def list_messages(conversation_id: UUID) -> list[MessageRow]:
    """Every `app.messages` row for one conversation, oldest first."""
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, conversation_id, turn_id, role, content, ui_payload, created_at
                FROM app.messages
                WHERE conversation_id = :conversation_id
                ORDER BY created_at
                """
            ),
            {"conversation_id": conversation_id},
        )
        rows = result.mappings().all()
    return [
        MessageRow(
            id=row["id"],
            conversation_id=row["conversation_id"],
            turn_id=row["turn_id"],
            role=row["role"],
            content=decrypt_text(row["content"]),
            ui_payload=row["ui_payload"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
