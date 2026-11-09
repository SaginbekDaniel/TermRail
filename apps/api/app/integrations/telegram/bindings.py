"""Project <-> chat binding and the monitoring switch (the second half of the double allowlist:
the owner allowed the chat in Telegram, and explicitly picks + enables it here)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, Unprocessable
from app.db.models import (
    CommercialSignal,
    Project,
    SignalMessageEvidence,
    TelegramBatch,
    TelegramBusinessConnection,
    TelegramChatBinding,
    TelegramChatCandidate,
    TelegramMessage,
    User,
)
from app.domains import audit, scope
from app.integrations.telegram import batching, linking


def monitoring_settings() -> dict[str, Any]:
    """Effective, non-negotiable MVP settings (shown read-only in the UI)."""
    s = get_settings()
    return {
        "mode": "smart",
        "selected_chats_only": True,
        "duplicate_suppression": True,
        "drafts_only": True,
        "message_debounce_seconds": s.telegram_message_debounce_seconds,
        "max_batch_window_seconds": s.telegram_max_batch_window_seconds,
        "max_batch_messages": s.telegram_max_batch_messages,
        "notifications": "significant_findings_only",
        "process_history_on_connect": False,
        "process_attachments": False,
        "auto_send_messages": False,
        "require_approved_baseline": True,
        "require_human_review_for_change": True,
    }


@dataclass
class BindingState:
    status: str  # UNBOUND | AWAITING_CHAT | NEEDS_BASELINE | READY | MONITORING | PAUSED
    binding: TelegramChatBinding | None
    connection: TelegramBusinessConnection | None
    has_baseline: bool
    last_batch: TelegramBatch | None


async def active_binding(session: AsyncSession, project_id: uuid.UUID) -> TelegramChatBinding | None:
    return await session.scalar(
        select(TelegramChatBinding).where(
            TelegramChatBinding.project_id == project_id, TelegramChatBinding.active.is_(True)
        )
    )


async def state(session: AsyncSession, project: Project) -> BindingState:
    conn = await linking.workspace_connection(session, project.workspace_id)
    binding = await active_binding(session, project.id)
    has_baseline = await scope.current_approved(session, project.id) is not None
    last_batch = None
    if binding is not None:
        last_batch = await session.scalar(
            select(TelegramBatch)
            .where(TelegramBatch.binding_id == binding.id)
            .order_by(TelegramBatch.created_at.desc())
            .limit(1)
        )
    if binding is None:
        status = "AWAITING_CHAT" if conn is not None and conn.status == "CONNECTED" else "UNBOUND"
    elif not has_baseline:
        status = "NEEDS_BASELINE"
    elif binding.monitoring_enabled and conn is not None and conn.status == "CONNECTED" and conn.is_enabled:
        status = "MONITORING"
    elif binding.monitoring_enabled or (conn is not None and conn.status != "CONNECTED"):
        status = "PAUSED"
    else:
        status = "READY"
    return BindingState(status, binding, conn, has_baseline, last_batch)


async def eligible_chats(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[tuple[TelegramChatCandidate, uuid.UUID | None]]:
    """Chats Telegram actually delivered to this workspace's connection, with the project each is bound to."""
    conn = await linking.workspace_connection(session, workspace_id)
    if conn is None:
        return []
    rows = (
        await session.execute(
            select(TelegramChatCandidate, TelegramChatBinding.project_id)
            .outerjoin(
                TelegramChatBinding,
                (TelegramChatBinding.connection_id == TelegramChatCandidate.connection_id)
                & (TelegramChatBinding.chat_id == TelegramChatCandidate.chat_id)
                & TelegramChatBinding.active.is_(True),
            )
            .where(TelegramChatCandidate.connection_id == conn.id, TelegramChatCandidate.chat_type == "private")
            .order_by(TelegramChatCandidate.last_seen_at.desc())
            .limit(200)
        )
    ).all()
    return [(c, pid) for c, pid in rows]


async def bind_chat(session: AsyncSession, *, project: Project, user: User, chat_id: int) -> TelegramChatBinding:
    linking.require_configured()
    if project.status != "ACTIVE":
        raise Conflict("Archived projects cannot be monitored", code="PROJECT_ARCHIVED")
    conn = await linking.workspace_connection(session, project.workspace_id)
    if conn is None or conn.status != "CONNECTED":
        raise Conflict("Connect Telegram Business first", code="TELEGRAM_NOT_CONNECTED")
    candidate = await session.scalar(
        select(TelegramChatCandidate).where(
            TelegramChatCandidate.connection_id == conn.id,
            TelegramChatCandidate.chat_id == chat_id,
            TelegramChatCandidate.chat_type == "private",
        )
    )
    if candidate is None:
        # A chat id cannot be guessed into monitoring: it must have been observed through this connection.
        raise NotFound("This chat has not been shared with TermRail", code="CHAT_NOT_ELIGIBLE")
    if await active_binding(session, project.id) is not None:
        raise Conflict("This project already monitors a chat; remove it first", code="PROJECT_ALREADY_BOUND")
    taken = await session.scalar(
        select(TelegramChatBinding).where(
            TelegramChatBinding.connection_id == conn.id,
            TelegramChatBinding.chat_id == chat_id,
            TelegramChatBinding.active.is_(True),
        )
    )
    if taken is not None:
        raise Conflict("This chat is already linked to another project", code="CHAT_ALREADY_BOUND")
    binding = TelegramChatBinding(
        workspace_id=project.workspace_id,
        project_id=project.id,
        connection_id=conn.id,
        chat_id=chat_id,
        display_name=candidate.display_name,
        active=True,
        monitoring_enabled=False,
        settings=monitoring_settings(),
        created_by=user.id,
    )
    session.add(binding)
    await session.flush()
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="telegram.chat_bound",
        object_type="telegram_binding",
        object_id=binding.id,
    )
    await session.commit()
    return binding


async def _locked_binding(session: AsyncSession, project: Project, expected_version: int | None) -> TelegramChatBinding:
    binding = await session.scalar(
        select(TelegramChatBinding)
        .where(TelegramChatBinding.project_id == project.id, TelegramChatBinding.active.is_(True))
        .with_for_update()
    )
    if binding is None:
        raise NotFound("No chat is linked to this project", code="NOT_BOUND")
    if expected_version is not None and binding.version != expected_version:
        raise Conflict("Telegram settings changed; reload", code="STALE_BINDING")
    return binding


async def set_monitoring(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    enabled: bool,
    privacy_acknowledged: bool,
    expected_version: int | None,
) -> TelegramChatBinding:
    binding = await _locked_binding(session, project, expected_version)
    if enabled:
        if project.status != "ACTIVE":
            raise Conflict("Archived projects cannot be monitored", code="PROJECT_ARCHIVED")
        if await scope.current_approved(session, project.id) is None:
            raise Conflict("Approve the project's scope baseline before monitoring", code="BASELINE_REQUIRED")
        conn = await session.get(TelegramBusinessConnection, binding.connection_id)
        if conn is None or conn.status != "CONNECTED" or not conn.is_enabled:
            raise Conflict("The Telegram connection is not active", code="TELEGRAM_NOT_CONNECTED")
        if not privacy_acknowledged:
            raise Unprocessable("Confirm the privacy notice to start monitoring", code="CONSENT_REQUIRED")
        if not binding.monitoring_enabled:
            binding.monitoring_enabled = True
            binding.consent_by = user.id
            binding.consent_at = utcnow()
            binding.enabled_at = utcnow()
            binding.settings = monitoring_settings()
    elif binding.monitoring_enabled:
        binding.monitoring_enabled = False
        binding.disabled_at = utcnow()
        await batching.cancel_open_batch(session, binding, reason="MONITORING_PAUSED")
    binding.version += 1
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="telegram.monitoring_enabled" if enabled else "telegram.monitoring_paused",
        object_type="telegram_binding",
        object_id=binding.id,
    )
    await session.commit()
    return binding


async def unbind(session: AsyncSession, *, project: Project, user: User) -> None:
    binding = await _locked_binding(session, project, None)
    await batching.cancel_open_batch(session, binding, reason="UNBOUND")
    binding.monitoring_enabled = False
    binding.active = False
    binding.disabled_at = utcnow()
    binding.version += 1
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="telegram.chat_unbound",
        object_type="telegram_binding",
        object_id=binding.id,
    )
    await session.commit()


async def purge_project_data(session: AsyncSession, *, project: Project, user: User) -> int:
    """Physically remove stored Telegram message bodies of this project and invalidate their evidence.
    Non-content metadata (ids, hashes, timestamps) stays for the audit trail."""
    binding_ids = list(
        (await session.scalars(select(TelegramChatBinding.id).where(TelegramChatBinding.project_id == project.id))).all()
    )
    if not binding_ids:
        return 0
    for b in (
        await session.scalars(select(TelegramChatBinding).where(TelegramChatBinding.id.in_(binding_ids)))
    ).all():
        if b.active:
            await batching.cancel_open_batch(session, b, reason="DATA_PURGED")
    now = utcnow()
    res = await session.execute(
        update(TelegramMessage)
        .where(TelegramMessage.binding_id.in_(binding_ids), TelegramMessage.text_ciphertext.is_not(None))
        .values(text_ciphertext=None, purged_at=now)
    )
    msg_ids = select(TelegramMessage.id).where(TelegramMessage.binding_id.in_(binding_ids))
    await session.execute(
        update(SignalMessageEvidence)
        .where(SignalMessageEvidence.message_row_id.in_(msg_ids), SignalMessageEvidence.state != "REVOKED")
        .values(state="REVOKED")
    )
    await session.execute(
        update(CommercialSignal).where(CommercialSignal.project_id == project.id).values(evidence_state="REVOKED")
    )
    purged = int(getattr(res, "rowcount", 0) or 0)
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="telegram.data_purged",
        object_type="project",
        object_id=project.id,
        metadata={"messages": purged},
    )
    await session.commit()
    return purged
