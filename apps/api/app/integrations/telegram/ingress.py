"""Webhook update processing. Runs inside ONE database transaction together with the idempotency receipt,
so an update is either fully applied and acknowledged (2xx) or rolled back and redelivered by Telegram.

Identity always comes from our own records keyed by `business_connection_id`; nothing in the payload can
name a workspace or project. Message bodies are persisted only for an actively monitored, bound chat.
Logged/returned outcome codes never contain message content.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.db.models import (
    TelegramBusinessConnection,
    TelegramChatBinding,
    TelegramChatCandidate,
    TelegramMessage,
    TelegramUpdateReceipt,
)
from app.integrations.telegram import batching, crypto, linking, signals
from app.integrations.telegram.schemas import TgBusinessMessagesDeleted, TgMessage, TgUpdate

SUPPORTED_CHAT_TYPES = {"private"}  # MVP: one-to-one client chats only


async def process_update(session: AsyncSession, update: TgUpdate, *, bot_id: int) -> str:
    kind = update.kind
    receipt_id = (
        await session.execute(
            insert(TelegramUpdateReceipt)
            .values(
                id=uuid.uuid4(),
                bot_id=bot_id,
                update_id=update.update_id,
                update_type=kind,
                outcome="RECEIVED",
                received_at=utcnow(),
            )
            .on_conflict_do_nothing(constraint="uq_tg_receipts_bot_update")
            .returning(TelegramUpdateReceipt.id)
        )
    ).scalar_one_or_none()
    if receipt_id is None:
        return "DUPLICATE_UPDATE"
    outcome = await _dispatch(session, update, bot_id)
    receipt = await session.get(TelegramUpdateReceipt, receipt_id)
    assert receipt is not None
    receipt.outcome = outcome[:40]
    return outcome


async def _dispatch(session: AsyncSession, update: TgUpdate, bot_id: int) -> str:
    if update.business_connection is not None:
        bc = update.business_connection
        rights = dict(bc.rights or {})
        if bc.can_reply is not None and "can_reply" not in rights:
            rights["can_reply"] = bc.can_reply
        return await linking.handle_business_connection(
            session,
            bot_id=bot_id,
            connection_id=bc.id,
            telegram_user_id=bc.user.id,
            telegram_username=bc.user.username,
            is_enabled=bc.is_enabled,
            rights=rights,
        )
    if update.business_message is not None:
        return await _ingest(session, update.business_message, bot_id=bot_id, edited=False)
    if update.edited_business_message is not None:
        return await _ingest(session, update.edited_business_message, bot_id=bot_id, edited=True)
    if update.deleted_business_messages is not None:
        return await _deleted(session, update.deleted_business_messages, bot_id=bot_id)
    if update.message is not None:
        m = update.message
        if m.chat.type != "private" or m.from_ is None or m.from_.is_bot:
            return "IGNORED_MESSAGE"
        nonce = linking.parse_start_payload(m.text)
        if nonce is None:
            return "IGNORED_MESSAGE"  # ordinary chats with the bot are neither stored nor answered
        return await linking.handle_start(
            session, nonce=nonce, telegram_user_id=m.from_.id, telegram_username=m.from_.username
        )
    return "IGNORED_UNSUPPORTED"


async def _connection(session: AsyncSession, bot_id: int, connection_id: str | None) -> TelegramBusinessConnection | None:
    if not connection_id:
        return None
    return await session.scalar(
        select(TelegramBusinessConnection).where(
            TelegramBusinessConnection.bot_id == bot_id,
            TelegramBusinessConnection.business_connection_id == connection_id,
        )
    )


async def _existing(session: AsyncSession, conn_id: object, chat_id: int, message_id: int) -> TelegramMessage | None:
    return await session.scalar(
        select(TelegramMessage)
        .where(
            TelegramMessage.connection_id == conn_id,
            TelegramMessage.chat_id == chat_id,
            TelegramMessage.message_id == message_id,
        )
        .with_for_update()
    )


async def _ingest(session: AsyncSession, msg: TgMessage, *, bot_id: int, edited: bool) -> str:
    conn = await _connection(session, bot_id, msg.business_connection_id)
    if conn is None or conn.status != "CONNECTED" or not conn.is_enabled:
        return "IGNORED_CONNECTION_INACTIVE"  # unclaimed/revoked: nothing is stored
    if msg.chat.type not in SUPPORTED_CHAT_TYPES:
        return "IGNORED_CHAT_TYPE"
    assert conn.workspace_id is not None
    now = utcnow()
    conn.last_event_at = now
    # Minimal metadata so the owner can pick this chat; never message text.
    await session.execute(
        insert(TelegramChatCandidate)
        .values(
            id=uuid.uuid4(),
            workspace_id=conn.workspace_id,
            connection_id=conn.id,
            chat_id=msg.chat.id,
            chat_type=msg.chat.type,
            display_name=msg.chat.display_name,
            first_seen_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_tg_candidates_connection_chat",
            set_={"last_seen_at": now, "display_name": msg.chat.display_name},
        )
    )
    binding = await session.scalar(
        select(TelegramChatBinding).where(
            TelegramChatBinding.connection_id == conn.id,
            TelegramChatBinding.chat_id == msg.chat.id,
            TelegramChatBinding.active.is_(True),
        )
    )
    existing = await _existing(session, conn.id, msg.chat.id, msg.message_id)
    monitored = binding is not None and binding.monitoring_enabled
    text = msg.readable_text

    if edited:
        if existing is None or existing.deleted_at is not None:
            return "IGNORED_EDIT_UNKNOWN"  # edits of messages from before monitoring are not imported
        new_hash = crypto.text_hash(text) if text else None
        if new_hash == existing.text_hash:
            return "EDIT_NO_CHANGE"
        existing.content_version += 1
        existing.edited_at = now
        existing.text_hash = new_hash
        existing.text_length = len(text)
        if monitored and text:
            existing.text_ciphertext = crypto.encrypt(text)
        else:  # monitoring paused: do not keep new content, and the old version is no longer current
            existing.text_ciphertext = None
            existing.purged_at = now
        await signals.invalidate_message_evidence(session, existing, "CHANGED")
        return "MESSAGE_EDITED"

    if not monitored:
        return "METADATA_ONLY"
    assert binding is not None
    if existing is not None:
        return "DUPLICATE_MESSAGE"
    direction = "OUTBOUND" if msg.from_ is not None and msg.from_.id == conn.telegram_user_id else "INBOUND"
    row = TelegramMessage(
        workspace_id=binding.workspace_id,
        binding_id=binding.id,
        connection_id=conn.id,
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        direction=direction,
        text_ciphertext=crypto.encrypt(text) if text else None,
        text_hash=crypto.text_hash(text) if text else None,
        text_length=len(text),
        has_unsupported_media=msg.has_media,  # attachments are never downloaded in P0
        content_version=1,
        sent_at=datetime.fromtimestamp(msg.date, UTC),
        received_at=now,
    )
    session.add(row)
    await session.flush()
    if text:
        await batching.append_message(session, binding, row)
        return "MESSAGE_STORED"
    return "MESSAGE_MEDIA_ONLY"


async def _deleted(session: AsyncSession, upd: TgBusinessMessagesDeleted, *, bot_id: int) -> str:
    conn = await _connection(session, bot_id, upd.business_connection_id)
    if conn is None or conn.workspace_id is None:
        return "IGNORED_CONNECTION_INACTIVE"
    now = utcnow()
    n = 0
    for mid in upd.message_ids[:1000]:
        existing = await _existing(session, conn.id, upd.chat.id, mid)
        if existing is None or existing.deleted_at is not None:
            continue
        existing.deleted_at = now
        existing.text_ciphertext = None  # tombstone: the body is physically removed
        existing.purged_at = now
        await signals.invalidate_message_evidence(session, existing, "REVOKED")
        n += 1
    return "MESSAGES_DELETED" if n else "DELETE_NO_MATCH"
