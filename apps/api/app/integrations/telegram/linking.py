"""Ownership linking between a TermRail workspace and a Telegram Business connection.

Flow (either order of steps 2 and 3 works):
1. A signed-in OWNER/MANAGER creates a one-time link intent (random nonce, 10 min TTL, single use).
2. They open t.me/<bot>?start=<nonce>; Telegram delivers `/start <nonce>` from their Telegram account,
   proving which Telegram user id belongs to this TermRail user. The intent becomes VERIFIED.
3. They add the bot in Telegram > Settings > Business > Chatbots; Telegram sends `business_connection`.
A connection is claimed for the workspace ONLY when BusinessConnection.user.id equals the Telegram user id
proven in step 2. Usernames and display names are never trusted for matching; a connection id can never be
entered by hand. Until claimed, a connection is UNCLAIMED and nothing it delivers is stored.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import Conflict, ServiceUnavailable
from app.db.models import (
    TelegramBusinessConnection,
    TelegramChatBinding,
    TelegramLinkIntent,
    User,
)
from app.domains import audit

START_PREFIX = "/start"


def nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def require_configured() -> None:
    s = get_settings()
    if not s.telegram_enabled:
        raise ServiceUnavailable("Telegram integration is not configured on this server", code="TELEGRAM_DISABLED")


def deep_link(nonce: str) -> str:
    return f"https://t.me/{get_settings().telegram_bot_username}?start={nonce}"


async def workspace_connection(session: AsyncSession, workspace_id: uuid.UUID) -> TelegramBusinessConnection | None:
    """The workspace's live connection (CONNECTED or ACCESS_REVOKED); at most one by DB constraint."""
    return await session.scalar(
        select(TelegramBusinessConnection).where(
            TelegramBusinessConnection.workspace_id == workspace_id,
            TelegramBusinessConnection.status.in_(("CONNECTED", "ACCESS_REVOKED")),
        )
    )


async def create_intent(session: AsyncSession, *, workspace_id: uuid.UUID, user: User) -> tuple[TelegramLinkIntent, str]:
    require_configured()
    if await workspace_connection(session, workspace_id) is not None:
        raise Conflict("This workspace already has a Telegram connection; disconnect it first", code="ALREADY_CONNECTED")
    now = utcnow()
    # A new intent supersedes this user's earlier unfinished ones (only one link in flight).
    await session.execute(
        update(TelegramLinkIntent)
        .where(
            TelegramLinkIntent.workspace_id == workspace_id,
            TelegramLinkIntent.initiated_by == user.id,
            TelegramLinkIntent.status.in_(("PENDING", "VERIFIED")),
        )
        .values(status="EXPIRED")
    )
    nonce = secrets.token_urlsafe(24)  # 32 chars of [A-Za-z0-9_-], within Telegram's 64-char start limit
    intent = TelegramLinkIntent(
        workspace_id=workspace_id,
        initiated_by=user.id,
        nonce_hash=nonce_hash(nonce),
        status="PENDING",
        expires_at=now + timedelta(seconds=get_settings().telegram_link_ttl_seconds),
    )
    session.add(intent)
    await session.flush()
    audit.record(
        session,
        workspace_id=workspace_id,
        actor_id=user.id,
        event_type="telegram.link_intent_created",
        object_type="telegram_link_intent",
        object_id=intent.id,
    )
    await session.commit()
    return intent, nonce


def parse_start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split()
    if len(parts) != 2 or parts[0].split("@", 1)[0] != START_PREFIX:
        return None
    nonce = parts[1]
    if not (8 <= len(nonce) <= 64) or not all(c.isalnum() or c in "_-" for c in nonce):
        return None
    return nonce


async def handle_start(
    session: AsyncSession, *, nonce: str, telegram_user_id: int, telegram_username: str | None
) -> str:
    """Process `/start <nonce>` from a private chat with the bot. Returns an outcome code (no content)."""
    intent = await session.scalar(
        select(TelegramLinkIntent).where(TelegramLinkIntent.nonce_hash == nonce_hash(nonce)).with_for_update()
    )
    now = utcnow()
    if intent is None:
        return "LINK_UNKNOWN_NONCE"
    if intent.status != "PENDING":
        return "LINK_NONCE_ALREADY_USED"  # single use
    if intent.expires_at <= now:
        intent.status = "EXPIRED"
        return "LINK_EXPIRED"
    intent.status = "VERIFIED"
    intent.telegram_user_id = telegram_user_id
    intent.telegram_username = (telegram_username or "")[:64] or None
    intent.verified_at = now
    audit.record(
        session,
        workspace_id=intent.workspace_id,
        actor_type="SYSTEM",
        event_type="telegram.owner_verified",
        object_type="telegram_link_intent",
        object_id=intent.id,
    )
    # The owner may have connected the bot in Telegram before opening the link.
    pending = await session.scalar(
        select(TelegramBusinessConnection)
        .where(
            TelegramBusinessConnection.telegram_user_id == telegram_user_id,
            TelegramBusinessConnection.status.in_(("UNCLAIMED", "DISCONNECTED")),
            TelegramBusinessConnection.is_enabled.is_(True),
            TelegramBusinessConnection.bot_id == get_settings().telegram_bot_id,
        )
        .order_by(TelegramBusinessConnection.updated_at.desc())
        .limit(1)
        .with_for_update()
    )
    if pending is not None:
        return await _claim(session, connection=pending, intent=intent)
    return "LINK_VERIFIED"


async def _verified_intent_for(session: AsyncSession, telegram_user_id: int) -> TelegramLinkIntent | None:
    window = timedelta(hours=get_settings().telegram_claim_window_hours)
    return await session.scalar(
        select(TelegramLinkIntent)
        .where(
            TelegramLinkIntent.status == "VERIFIED",
            TelegramLinkIntent.telegram_user_id == telegram_user_id,
            TelegramLinkIntent.verified_at > utcnow() - window,
        )
        .order_by(TelegramLinkIntent.verified_at.desc())
        .limit(1)
        .with_for_update()
    )


async def _claim(session: AsyncSession, *, connection: TelegramBusinessConnection, intent: TelegramLinkIntent) -> str:
    """Attach `connection` to the intent's workspace if the proven Telegram identity matches."""
    if connection.telegram_user_id != intent.telegram_user_id:
        return "LINK_IDENTITY_MISMATCH"
    if connection.workspace_id is not None and connection.workspace_id != intent.workspace_id:
        if connection.status in ("CONNECTED", "ACCESS_REVOKED"):
            # Never silently move a live connection between tenants: it must be disconnected there first.
            intent.status = "CONFLICT"
            audit.record(
                session,
                workspace_id=intent.workspace_id,
                actor_type="SYSTEM",
                event_type="telegram.link_conflict",
                object_type="telegram_link_intent",
                object_id=intent.id,
            )
            return "LINK_CONNECTED_ELSEWHERE"
    if await workspace_connection(session, intent.workspace_id) not in (None, connection):
        intent.status = "CONFLICT"
        return "LINK_WORKSPACE_ALREADY_CONNECTED"
    if connection.workspace_id is not None and connection.workspace_id != intent.workspace_id:
        # A previously DISCONNECTED connection moves to a new tenant: the old row (and the old tenant's
        # bindings/messages that reference it) stays with the old workspace under an archived id; the new
        # workspace gets a fresh row. History is never re-parented across tenants.
        original_id = connection.business_connection_id
        connection.business_connection_id = f"{original_id[:150]}~archived~{connection.id.hex}"
        await session.flush()
        fresh = TelegramBusinessConnection(
            bot_id=connection.bot_id,
            business_connection_id=original_id,
            telegram_user_id=connection.telegram_user_id,
            telegram_username=connection.telegram_username,
            status="UNCLAIMED",
            is_enabled=connection.is_enabled,
            rights=dict(connection.rights or {}),
            last_event_at=connection.last_event_at,
        )
        session.add(fresh)
        await session.flush()
        connection = fresh
    now = utcnow()
    connection.workspace_id = intent.workspace_id
    connection.linked_by = intent.initiated_by
    connection.status = "CONNECTED" if connection.is_enabled else "ACCESS_REVOKED"
    connection.linked_at = now
    connection.revoked_at = None if connection.is_enabled else now
    intent.status = "CLAIMED"
    intent.claimed_connection_id = connection.id
    await session.flush()
    audit.record(
        session,
        workspace_id=intent.workspace_id,
        actor_type="SYSTEM",
        event_type="telegram.connection_linked",
        object_type="telegram_connection",
        object_id=connection.id,
        metadata={"on_behalf_of": str(intent.initiated_by), "enabled": connection.is_enabled},
    )
    return "LINK_CLAIMED"


async def handle_business_connection(
    session: AsyncSession,
    *,
    bot_id: int,
    connection_id: str,
    telegram_user_id: int,
    telegram_username: str | None,
    is_enabled: bool,
    rights: dict[str, Any],
) -> str:
    now = utcnow()
    conn = await session.scalar(
        select(TelegramBusinessConnection)
        .where(
            TelegramBusinessConnection.bot_id == bot_id,
            TelegramBusinessConnection.business_connection_id == connection_id,
        )
        .with_for_update()
    )
    if conn is None:
        conn = TelegramBusinessConnection(
            bot_id=bot_id,
            business_connection_id=connection_id,
            telegram_user_id=telegram_user_id,
            status="UNCLAIMED",
            is_enabled=is_enabled,
            rights=rights,
        )
        session.add(conn)
        await session.flush()
    elif conn.telegram_user_id != telegram_user_id:
        # A connection id belongs to one Telegram account; a different owner is a protocol anomaly.
        return "CONNECTION_OWNER_CHANGED_IGNORED"
    conn.telegram_username = (telegram_username or "")[:64] or None
    conn.rights = rights
    conn.last_event_at = now
    was_enabled = conn.is_enabled
    conn.is_enabled = is_enabled

    if conn.status == "UNCLAIMED" or conn.status == "DISCONNECTED":
        if not is_enabled:
            return "CONNECTION_DISABLED_UNCLAIMED"
        intent = await _verified_intent_for(session, telegram_user_id)
        if intent is None:
            if conn.status == "DISCONNECTED":
                return "CONNECTION_DISCONNECTED_IGNORED"
            return "CONNECTION_UNCLAIMED"
        return await _claim(session, connection=conn, intent=intent)

    assert conn.workspace_id is not None
    if not is_enabled and conn.status == "CONNECTED":
        await revoke_access(session, conn, reason="TELEGRAM_DISABLED")
        return "CONNECTION_REVOKED"
    if is_enabled and conn.status == "ACCESS_REVOKED":
        conn.status = "CONNECTED"
        conn.revoked_at = None
        audit.record(
            session,
            workspace_id=conn.workspace_id,
            actor_type="SYSTEM",
            event_type="telegram.connection_restored",
            object_type="telegram_connection",
            object_id=conn.id,
        )
        # Monitoring stays as configured but every chat must be re-confirmed: fail closed.
        return "CONNECTION_RESTORED"
    if was_enabled != is_enabled:
        return "CONNECTION_UPDATED"
    audit.record(
        session,
        workspace_id=conn.workspace_id,
        actor_type="SYSTEM",
        event_type="telegram.connection_rights_changed",
        object_type="telegram_connection",
        object_id=conn.id,
        metadata={"rights": sorted(k for k, v in rights.items() if v)},
    )
    return "CONNECTION_UPDATED"


async def revoke_access(session: AsyncSession, conn: TelegramBusinessConnection, *, reason: str) -> None:
    """Telegram-side disable/removal: stop ingestion and drop un-analysed buffers immediately."""
    from app.integrations.telegram import batching

    conn.status = "ACCESS_REVOKED"
    conn.revoked_at = utcnow()
    bindings = (
        await session.scalars(
            select(TelegramChatBinding).where(
                TelegramChatBinding.connection_id == conn.id, TelegramChatBinding.active.is_(True)
            )
        )
    ).all()
    for b in bindings:
        if b.monitoring_enabled:
            b.monitoring_enabled = False
            b.disabled_at = utcnow()
            b.version += 1
        await batching.cancel_open_batch(session, b, reason=reason)
    assert conn.workspace_id is not None
    audit.record(
        session,
        workspace_id=conn.workspace_id,
        actor_type="SYSTEM",
        event_type="telegram.connection_revoked",
        object_type="telegram_connection",
        object_id=conn.id,
        metadata={"reason": reason, "bindings_paused": len(bindings)},
    )


async def disconnect(session: AsyncSession, *, workspace_id: uuid.UUID, user: User) -> None:
    from app.integrations.telegram import batching

    conn = await session.scalar(
        select(TelegramBusinessConnection)
        .where(
            TelegramBusinessConnection.workspace_id == workspace_id,
            TelegramBusinessConnection.status.in_(("CONNECTED", "ACCESS_REVOKED")),
        )
        .with_for_update()
    )
    await session.execute(
        update(TelegramLinkIntent)
        .where(TelegramLinkIntent.workspace_id == workspace_id, TelegramLinkIntent.status.in_(("PENDING", "VERIFIED")))
        .values(status="EXPIRED")
    )
    if conn is None:
        await session.commit()
        return
    bindings = (
        await session.scalars(
            select(TelegramChatBinding).where(
                TelegramChatBinding.connection_id == conn.id, TelegramChatBinding.active.is_(True)
            )
        )
    ).all()
    for b in bindings:
        await batching.cancel_open_batch(session, b, reason="DISCONNECTED")
        b.monitoring_enabled = False
        b.active = False
        b.disabled_at = utcnow()
        b.version += 1
    conn.status = "DISCONNECTED"
    conn.revoked_at = utcnow()
    audit.record(
        session,
        workspace_id=workspace_id,
        actor_id=user.id,
        event_type="telegram.connection_disconnected",
        object_type="telegram_connection",
        object_id=conn.id,
        metadata={"bindings_closed": len(bindings)},
    )
    await session.commit()
