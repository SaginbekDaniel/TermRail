"""Persistent sliding-window batching of a monitored chat and its finalization.

- Every new text message in a monitored chat joins the chat's single OPEN batch (unique partial index) and
  moves `quiet_until = last_message_at + debounce` (default 120 s), capped by `max_deadline`
  (first message + 15 min) and by `max_batch_messages` (100) so an endless chat still gets analysed.
- One durable job per batch (`telegram_finalize_batch`, idempotency key = batch id). If it fires while the
  window is still moving, it defers itself to the new `quiet_until` (JobDeferred: no attempt consumed).
- Finalization re-checks every activation condition and fails closed; it snapshots the exact content version
  of every message, triages it deterministically, and only then hands candidate client text to the existing
  intake + evidence-gated analysis pipeline, pinned to the current approved baseline.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_settings
from app.db.models import (
    Project,
    TelegramBatch,
    TelegramBatchMessage,
    TelegramBusinessConnection,
    TelegramChatBinding,
    TelegramMessage,
    User,
)
from app.domains import audit, intake, scope
from app.integrations.telegram import crypto, prefilter
from app.jobs import queue

FINALIZE_JOB = "telegram_finalize_batch"
SEPARATOR = "\n\n"


async def open_batch(session: AsyncSession, binding_id: uuid.UUID) -> TelegramBatch | None:
    return await session.scalar(
        select(TelegramBatch)
        .where(TelegramBatch.binding_id == binding_id, TelegramBatch.state == "OPEN")
        .with_for_update()
    )


async def append_message(session: AsyncSession, binding: TelegramChatBinding, message: TelegramMessage) -> TelegramBatch:
    s = get_settings()
    now = utcnow()
    batch = await open_batch(session, binding.id)
    if batch is None:
        try:
            async with session.begin_nested():
                batch = TelegramBatch(
                    workspace_id=binding.workspace_id,
                    binding_id=binding.id,
                    state="OPEN",
                    first_message_at=now,
                    last_message_at=now,
                    quiet_until=now + timedelta(seconds=s.telegram_message_debounce_seconds),
                    max_deadline=now + timedelta(seconds=s.telegram_max_batch_window_seconds),
                    message_count=0,
                )
                session.add(batch)
        except IntegrityError:
            # A concurrent delivery for the same chat opened the batch first; join it.
            batch = await open_batch(session, binding.id)
            assert batch is not None
    await session.execute(
        insert(TelegramBatchMessage)
        .values(batch_id=batch.id, message_row_id=message.id)
        .on_conflict_do_nothing(index_elements=["batch_id", "message_row_id"])
    )
    batch.message_count += 1
    batch.last_message_at = now
    quiet = min(now + timedelta(seconds=s.telegram_message_debounce_seconds), batch.max_deadline)
    if batch.message_count >= s.telegram_max_batch_messages:
        quiet = now  # cap reached: close now
    batch.quiet_until = quiet
    job = await queue.enqueue(
        session,
        kind=FINALIZE_JOB,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        payload={"batch_id": str(batch.id)},
        idempotency_key=f"tgbatch:{batch.id}",
        max_attempts=5,
        run_at=quiet,
    )
    batch.job_id = job.id
    if job.status == "QUEUED":
        job.next_run_at = quiet  # follow the sliding window (earlier when the cap is hit)
    await session.flush()
    return batch


async def cancel_open_batch(session: AsyncSession, binding: TelegramChatBinding, *, reason: str) -> None:
    """Close the chat's un-analysed batch and physically drop the message bodies it buffered."""
    batch = await open_batch(session, binding.id)
    if batch is None:
        return
    batch.state = "CANCELLED"
    batch.outcome = reason[:60]
    batch.processed_at = utcnow()
    rows = (
        await session.scalars(
            select(TelegramMessage)
            .join(TelegramBatchMessage, TelegramBatchMessage.message_row_id == TelegramMessage.id)
            .where(TelegramBatchMessage.batch_id == batch.id)
        )
    ).all()
    for m in rows:
        m.text_ciphertext = None
        m.purged_at = utcnow()
    audit.record(
        session,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        actor_type="SYSTEM",
        event_type="telegram.batch_cancelled",
        object_type="telegram_batch",
        object_id=batch.id,
        metadata={"reason": reason, "messages": len(rows)},
    )


async def handle_finalize_batch(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    from app.domains import analysis
    from app.integrations.telegram import signals

    batch = await session.scalar(
        select(TelegramBatch).where(TelegramBatch.id == uuid.UUID(payload["batch_id"])).with_for_update()
    )
    if batch is None or batch.state != "OPEN":
        return {"skipped": "not open"}
    now = utcnow()
    if now < batch.quiet_until:
        await session.rollback()
        raise queue.JobDeferred(batch.quiet_until)

    binding = await session.get(TelegramChatBinding, batch.binding_id)
    assert binding is not None
    conn = await session.get(TelegramBusinessConnection, binding.connection_id)
    project = await session.get(Project, binding.project_id)
    baseline = await scope.current_approved(session, binding.project_id)
    # Fail closed: every activation condition must still hold at the moment of analysis.
    reason = None
    if not (binding.active and binding.monitoring_enabled):
        reason = "MONITORING_OFF"
    elif conn is None or conn.status != "CONNECTED" or not conn.is_enabled:
        reason = "CONNECTION_INACTIVE"
    elif project is None or project.status != "ACTIVE" or project.workspace_id != binding.workspace_id:
        reason = "PROJECT_INACTIVE"
    elif baseline is None:
        reason = "BASELINE_REQUIRED"
    if reason is not None:
        await cancel_open_batch(session, binding, reason=reason)
        await session.commit()
        return {"cancelled": reason}
    assert conn is not None and project is not None and baseline is not None

    rows = (
        await session.execute(
            select(TelegramMessage, TelegramBatchMessage)
            .join(TelegramBatchMessage, TelegramBatchMessage.message_row_id == TelegramMessage.id)
            .where(TelegramBatchMessage.batch_id == batch.id)
            .order_by(TelegramMessage.sent_at, TelegramMessage.message_id)
            .with_for_update(of=TelegramMessage)
        )
    ).all()

    max_chars = intake.MAX_MESSAGE_CHARS
    parts: list[str] = []
    cursor = 0
    candidates: list[TelegramMessage] = []
    overflow: list[tuple[TelegramMessage, str]] = []
    side_signals: list[tuple[str, TelegramMessage, str]] = []
    digest = hashlib.sha256()
    for msg, member in rows:
        text = crypto.decrypt(msg.text_ciphertext) if msg.text_ciphertext is not None else None
        if msg.deleted_at is not None or not text:
            member.prefilter_label = "DELETED" if msg.deleted_at is not None else "NO_TEXT"
            continue
        member.version_at_snapshot = msg.content_version
        member.text_hash_at_snapshot = msg.text_hash
        digest.update(f"{msg.id}:{msg.content_version}:{msg.text_hash};".encode())
        if msg.direction == "OUTBOUND":
            member.prefilter_label = "OUTBOUND"  # context only; never a client requirement
            continue
        tri = prefilter.triage(text)
        member.prefilter_label = ",".join(sorted(tri.labels))
        for label, category in (("TIMELINE", "TIMELINE_CHANGE_CANDIDATE"), ("PAYMENT", "PAYMENT_COMMITMENT_MENTION")):
            if label in tri.labels:
                side_signals.append((category, msg, text))
        if not tri.send_to_analysis:
            continue
        sep = SEPARATOR if parts else ""
        if cursor + len(sep) + len(text) > max_chars:
            member.prefilter_label = "CANDIDATE_OVERFLOW"
            overflow.append((msg, text))
            continue
        cursor += len(sep)
        member.segment_start = cursor
        member.segment_end = cursor + len(text)
        parts.append(sep + text)
        cursor += len(text)
        candidates.append(msg)

    batch.baseline_id = baseline.id
    batch.snapshot_hash = digest.hexdigest()
    batch.processed_at = now
    owner_id = conn.linked_by
    assert owner_id is not None

    for category, msg, text in side_signals:
        await signals.record_message_signal(
            session, binding=binding, batch=batch, baseline_id=baseline.id, category=category, message=msg, text=text
        )
    if overflow:
        await signals.record_unanalyzed(
            session, binding=binding, batch=batch, baseline_id=baseline.id, messages=overflow, reason="TOO_LONG"
        )

    if not candidates:
        batch.state = "NO_ACTION"
        batch.outcome = "SIGNALS_ONLY" if side_signals else "NO_CANDIDATES"
        audit.record(
            session,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            actor_type="WORKER",
            event_type="telegram.batch_finalized",
            object_type="telegram_batch",
            object_id=batch.id,
            metadata={"messages": len(rows), "candidates": 0, "side_signals": len(side_signals)},
        )
        await session.commit()
        return {"state": batch.state}

    request = await intake.create_integration_request(
        session,
        project=project,
        on_behalf_of=owner_id,
        channel="TELEGRAM",
        external_id=f"telegram:{binding.id}:{batch.id}",
        sender=binding.display_name,
        message_text="".join(parts),
        source_batch_id=batch.id,
    )
    batch.state = "PROCESSED"
    batch.outcome = "ANALYSIS_QUEUED"
    audit.record(
        session,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        actor_type="WORKER",
        event_type="telegram.batch_finalized",
        object_type="telegram_batch",
        object_id=batch.id,
        metadata={
            "messages": len(rows),
            "candidates": len(candidates),
            "side_signals": len(side_signals),
            "request_id": str(request.id),
            "baseline_id": str(baseline.id),
        },
    )
    owner = await session.get(User, owner_id)
    assert owner is not None
    # Commits the whole finalization atomically with the queued analysis job.
    await analysis.start_analysis(
        session,
        project=project,
        request=request,
        user=owner,
        baseline_id=baseline.id,
        idempotency_key=f"telegram:{batch.id}",
        on_behalf=True,
    )
    return {"state": batch.state, "request_id": str(request.id)}

