"""Commercial signals: deduplicated, evidence-backed cases for human review.

A signal is a *potential* change, never a decision. It is created from
- evidence-gated analysis findings of a Telegram batch (CHANGE_CANDIDATE / AMBIGUOUS / INSUFFICIENT_EVIDENCE,
  or anything the policy gates flagged for review),
- deterministic non-monetary mentions (TIMELINE_CHANGE_CANDIDATE, PAYMENT_COMMITMENT_MENTION),
- an analysis that could not run (UNANALYZED): an outage never silently means "no change".

Dedup: within a project, an open signal of the same category family whose term fingerprint is similar
(Jaccard >= 0.5 on stemmed content words) absorbs the new occurrence: one case, growing evidence history,
one notification. Different families (e.g. a scope change vs. a deadline change) are never merged.

Every Telegram citation pins (message row, content version, sha256 of that version, [start, end)). The quote
shown to a reader is re-derived from the stored ciphertext and only if the hash still matches.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import Conflict, NotFound, Unprocessable
from app.db.models import (
    AnalysisRun,
    ClientRequest,
    CommercialSignal,
    Finding,
    Project,
    RequestItem,
    SignalMessageEvidence,
    TelegramBatch,
    TelegramBatchMessage,
    TelegramChatBinding,
    TelegramMessage,
    User,
)
from app.domains import audit, change_orders, intake
from app.integrations.telegram import crypto

BUILD_JOB = "telegram_build_signals"
SIMILARITY_THRESHOLD = 0.5

FAMILY = {
    "CHANGE_CANDIDATE": "SCOPE",
    "AMBIGUOUS": "SCOPE",
    "INSUFFICIENT_EVIDENCE": "SCOPE",
    "UNANALYZED": "SCOPE",
    "BUG_FIX": "BUG_FIX",
    "IN_SCOPE": "IN_SCOPE",
    "TIMELINE_CHANGE_CANDIDATE": "TIMELINE",
    "PAYMENT_COMMITMENT_MENTION": "PAYMENT",
}
# When occurrences of one case are classified differently, the case shows the most cautious category.
PRECEDENCE = ["CHANGE_CANDIDATE", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "UNANALYZED"]
SEVERITY = {
    "CHANGE_CANDIDATE": "HIGH",
    "TIMELINE_CHANGE_CANDIDATE": "MEDIUM",
    "AMBIGUOUS": "MEDIUM",
    "INSUFFICIENT_EVIDENCE": "MEDIUM",
    "UNANALYZED": "MEDIUM",
    "BUG_FIX": "LOW",
    "IN_SCOPE": "LOW",
    "PAYMENT_COMMITMENT_MENTION": "LOW",
}
ACTIVE_STATUSES = ("OPEN", "CLARIFICATION_REQUESTED")

_WORD = re.compile(r"\w+", re.UNICODE)
# Request verbs and chat filler carry no meaning about *what* is requested.
_FILLER_STEMS = {
    "добав", "сдела", "нужно", "нужна", "нужен", "хочу", "хотим", "хотел", "можно", "можете", "давай", "пожал",
    "сделай", "измен", "помен", "реали", "подкл", "приве", "здрав", "спаси", "также", "тогда", "вообщ", "кстат",
    "need", "want", "make", "also", "still",
    "please", "could", "would", "should", "about", "there", "thank", "hello", "maybe", "again",
    "какой", "какая", "какие", "этот", "этого", "этой", "будет", "будут", "когда", "сейча", "очень",
}  # fmt: skip
_STOP = {"the", "and", "for", "with", "that", "this", "you", "your", "our", "что", "это", "для", "как", "так", "или"}


def fingerprint(text_: str) -> list[str]:
    terms: set[str] = set()
    for w in _WORD.findall(text_.lower()):
        if len(w) < 4 or w.isdigit() or w in _STOP:
            continue
        stem = w[:5]
        if stem in _FILLER_STEMS:
            continue
        terms.add(stem)
    return sorted(terms)


def fingerprint_hash(terms: list[str], category: str) -> str:
    return hashlib.sha256(f"{FAMILY[category]}|{' '.join(terms)}".encode()).hexdigest()


def similarity(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class Cite:
    message: TelegramMessage
    version: int
    text_hash: str
    start: int
    end: int


async def _lock_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Serialize signal creation per project so two workers cannot open duplicate cases."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"signals:{project_id}"})


async def _upsert(
    session: AsyncSession,
    *,
    binding: TelegramChatBinding,
    category: str,
    summary: str,
    terms: list[str],
    cites: list[Cite],
    baseline_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    request_id: uuid.UUID | None = None,
    finding_id: uuid.UUID | None = None,
) -> tuple[CommercialSignal, bool]:
    await _lock_project(session, binding.project_id)
    now = utcnow()
    family = FAMILY[category]
    fhash = fingerprint_hash(terms, category)
    candidates = (
        await session.scalars(
            select(CommercialSignal).where(
                CommercialSignal.project_id == binding.project_id,
                CommercialSignal.status.in_(ACTIVE_STATUSES),
                CommercialSignal.category.in_([c for c, f in FAMILY.items() if f == family]),
            )
        )
    ).all()
    best: CommercialSignal | None = None
    best_score = 0.0
    for c in candidates:
        score = 1.0 if c.fingerprint_hash == fhash else similarity(c.fingerprint_terms, terms)
        if score > best_score:
            best, best_score = c, score
    created = False
    if best is not None and best_score >= SIMILARITY_THRESHOLD:
        signal = best
        signal.occurrences += 1
        signal.last_seen_at = now
        signal.fingerprint_terms = sorted(set(signal.fingerprint_terms) | set(terms))
        if category in PRECEDENCE and signal.category in PRECEDENCE:
            signal.category = min(category, signal.category, key=PRECEDENCE.index)
            signal.severity = SEVERITY[signal.category]
        if request_id is not None:
            signal.request_id = request_id
            signal.latest_finding_id = finding_id
            signal.baseline_id = baseline_id
        signal.version += 1
    else:
        signal = CommercialSignal(
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            binding_id=binding.id,
            request_id=request_id,
            latest_finding_id=finding_id,
            baseline_id=baseline_id,
            category=category,
            summary=summary[:500],
            fingerprint_terms=terms,
            fingerprint_hash=fhash,
            status="OPEN",
            evidence_state="VALID",
            severity=SEVERITY[category],
            notify=SEVERITY[category] in ("HIGH", "MEDIUM"),
            occurrences=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(signal)
        created = True
    await session.flush()
    for cite in cites:
        current_ok = cite.message.deleted_at is None and cite.message.content_version == cite.version
        await session.execute(
            insert(SignalMessageEvidence)
            .values(
                id=uuid.uuid4(),
                workspace_id=binding.workspace_id,
                signal_id=signal.id,
                message_row_id=cite.message.id,
                message_content_version=cite.version,
                message_text_hash=cite.text_hash,
                quote_start=cite.start,
                quote_end=cite.end,
                batch_id=batch_id,
                finding_id=finding_id,
                state="VALID" if current_ok else ("REVOKED" if cite.message.deleted_at else "CHANGED"),
            )
            .on_conflict_do_nothing(constraint="uq_signal_evidence_exact")
        )
        if not current_ok:
            signal.evidence_state = "REVOKED" if cite.message.deleted_at else "CHANGED"
    audit.record(
        session,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        actor_type="WORKER",
        event_type="signal.created" if created else "signal.merged",
        object_type="commercial_signal",
        object_id=signal.id,
        metadata={"category": category, "evidence": len(cites), "occurrences": signal.occurrences},
    )
    return signal, created


async def record_message_signal(
    session: AsyncSession,
    *,
    binding: TelegramChatBinding,
    batch: TelegramBatch,
    baseline_id: uuid.UUID,
    category: str,
    message: TelegramMessage,
    text: str,
) -> CommercialSignal:
    assert message.text_hash is not None
    cite = Cite(message, message.content_version, message.text_hash, 0, len(text))
    terms = fingerprint(text)
    signal, _ = await _upsert(
        session,
        binding=binding,
        category=category,
        summary=text[:300],
        terms=terms,
        cites=[cite],
        baseline_id=baseline_id,
        batch_id=batch.id,
    )
    return signal


async def record_unanalyzed(
    session: AsyncSession,
    *,
    binding: TelegramChatBinding,
    batch: TelegramBatch,
    baseline_id: uuid.UUID | None,
    messages: list[tuple[TelegramMessage, str]],
    reason: str,
    request_id: uuid.UUID | None = None,
) -> CommercialSignal:
    cites = [Cite(m, m.content_version, m.text_hash or "", 0, len(t)) for m, t in messages if t]
    terms = fingerprint(" ".join(t for _, t in messages))
    signal, _ = await _upsert(
        session,
        binding=binding,
        category="UNANALYZED",
        summary=reason,
        terms=terms or [f"batch-{batch.id.hex[:8]}"],
        cites=cites,
        baseline_id=baseline_id,
        batch_id=batch.id,
        request_id=request_id,
    )
    return signal


def _wants_signal(f: Finding) -> bool:
    category = f.final_category or f.category
    return category in ("CHANGE_CANDIDATE", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE") or f.needs_review


async def handle_build_signals(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    run = await session.get(AnalysisRun, uuid.UUID(payload["analysis_run_id"]))
    if run is None:
        return {"skipped": "run not found"}
    request = await session.get(ClientRequest, run.request_id)
    assert request is not None
    if request.source_batch_id is None:
        return {"skipped": "not an integration request"}
    batch = await session.get(TelegramBatch, request.source_batch_id)
    assert batch is not None
    binding = await session.get(TelegramChatBinding, batch.binding_id)
    assert binding is not None and binding.workspace_id == run.workspace_id == request.workspace_id

    members = (
        await session.execute(
            select(TelegramBatchMessage, TelegramMessage)
            .join(TelegramMessage, TelegramMessage.id == TelegramBatchMessage.message_row_id)
            .where(TelegramBatchMessage.batch_id == batch.id, TelegramBatchMessage.segment_start.is_not(None))
            .order_by(TelegramBatchMessage.segment_start)
        )
    ).all()

    if run.status == "FAILED":
        msgs: list[tuple[TelegramMessage, str]] = []
        for member, msg in members:
            assert member.segment_start is not None and member.segment_end is not None
            msgs.append((msg, request.message_text[member.segment_start : member.segment_end]))
        await record_unanalyzed(
            session,
            binding=binding,
            batch=batch,
            baseline_id=run.baseline_id,
            messages=msgs,
            reason=run.error_code or "ANALYSIS_FAILED",
            request_id=request.id,
        )
        await session.commit()
        return {"unanalyzed": True}

    created = merged = 0
    rows = (
        await session.execute(
            select(Finding, RequestItem)
            .join(RequestItem, RequestItem.id == Finding.request_item_id)
            .where(Finding.analysis_run_id == run.id)
            .order_by(RequestItem.ordinal)
        )
    ).all()
    for finding, item in rows:
        if not _wants_signal(finding):
            continue
        cites: list[Cite] = []
        for member, msg in members:
            assert member.segment_start is not None and member.segment_end is not None
            lo, hi = max(item.start_offset, member.segment_start), min(item.end_offset, member.segment_end)
            if hi > lo and member.version_at_snapshot is not None and member.text_hash_at_snapshot:
                cites.append(
                    Cite(
                        msg,
                        member.version_at_snapshot,
                        member.text_hash_at_snapshot,
                        lo - member.segment_start,
                        hi - member.segment_start,
                    )
                )
        _, was_created = await _upsert(
            session,
            binding=binding,
            category=finding.final_category or finding.category,
            summary=finding.summary or item.exact_text,
            terms=fingerprint(item.exact_text) or fingerprint(finding.summary),
            cites=cites,
            baseline_id=run.baseline_id,
            batch_id=batch.id,
            request_id=request.id,
            finding_id=finding.id,
        )
        created += was_created
        merged += not was_created
    # A successful re-analysis supersedes an earlier "could not analyse" case for the same request.
    for s in (
        await session.scalars(
            select(CommercialSignal).where(
                CommercialSignal.request_id == request.id,
                CommercialSignal.category == "UNANALYZED",
                CommercialSignal.status.in_(ACTIVE_STATUSES),
            )
        )
    ).all():
        s.status = "RESOLVED"
        s.resolution_reason = "ANALYZED_LATER"
        s.resolved_at = utcnow()
        s.version += 1
    await session.commit()
    return {"created": created, "merged": merged}


async def invalidate_message_evidence(session: AsyncSession, message: TelegramMessage, state: str) -> int:
    """An edited (CHANGED) or deleted (REVOKED) message invalidates evidence that cited an older version.
    Decided cases go back to review; nothing is rewritten in place."""
    assert state in ("CHANGED", "REVOKED")
    ev = (
        await session.scalars(
            select(SignalMessageEvidence).where(
                SignalMessageEvidence.message_row_id == message.id,
                # A deletion also revokes evidence an earlier edit already marked CHANGED.
                SignalMessageEvidence.state.in_(("VALID", "CHANGED") if state == "REVOKED" else ("VALID",)),
                SignalMessageEvidence.message_content_version <= message.content_version,
            )
        )
    ).all()
    touched: set[uuid.UUID] = set()
    for e in ev:
        if state == "CHANGED" and e.message_content_version == message.content_version:
            continue
        e.state = state
        touched.add(e.signal_id)
    for sid in touched:
        signal = await session.get(CommercialSignal, sid, with_for_update=True)
        assert signal is not None
        if state == "REVOKED" or signal.evidence_state != "REVOKED":
            signal.evidence_state = state
        if signal.status in ("DISMISSED", "RESOLVED"):
            signal.status = "OPEN"
            signal.notify = True
        signal.version += 1
        audit.record(
            session,
            workspace_id=signal.workspace_id,
            project_id=signal.project_id,
            actor_type="SYSTEM",
            event_type="signal.evidence_" + state.lower(),
            object_type="commercial_signal",
            object_id=signal.id,
        )
    return len(touched)


# ------------------------------------------------------------------------------------------------
# Reading
# ------------------------------------------------------------------------------------------------


@dataclass
class EvidenceView:
    id: uuid.UUID
    message_id: int
    direction: str
    sent_at: Any
    content_version: int
    state: str
    quote: str | None  # None when the content is no longer available or has changed


async def evidence_views(session: AsyncSession, signal_id: uuid.UUID) -> list[EvidenceView]:
    rows = (
        await session.execute(
            select(SignalMessageEvidence, TelegramMessage)
            .join(TelegramMessage, TelegramMessage.id == SignalMessageEvidence.message_row_id)
            .where(SignalMessageEvidence.signal_id == signal_id)
            .order_by(TelegramMessage.sent_at, SignalMessageEvidence.quote_start)
        )
    ).all()
    out: list[EvidenceView] = []
    for ev, msg in rows:
        quote = None
        state = ev.state
        if (
            state == "VALID"
            and msg.text_ciphertext is not None
            and msg.deleted_at is None
            and msg.content_version == ev.message_content_version
        ):
            plain = crypto.decrypt(msg.text_ciphertext)
            if plain is not None and crypto.text_hash(plain) == ev.message_text_hash:
                quote = plain[ev.quote_start : ev.quote_end]
            else:
                state = "CHANGED"
        elif state == "VALID":
            state = "REVOKED" if msg.deleted_at or msg.text_ciphertext is None else "CHANGED"
        out.append(
            EvidenceView(ev.id, msg.message_id, msg.direction, msg.sent_at, ev.message_content_version, state, quote)
        )
    return out


async def get_signal(session: AsyncSession, signal_id: uuid.UUID) -> CommercialSignal:
    signal = await session.get(CommercialSignal, signal_id)
    if signal is None:
        raise NotFound("Signal not found")
    return signal


async def open_counts(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    rows = await session.execute(
        select(CommercialSignal.project_id, func.count())
        .where(
            CommercialSignal.project_id.in_(project_ids),
            CommercialSignal.status.in_(ACTIVE_STATUSES),
            CommercialSignal.notify.is_(True),
        )
        .group_by(CommercialSignal.project_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


# ------------------------------------------------------------------------------------------------
# Human actions (manager). Nothing here sends anything or changes the approved baseline.
# ------------------------------------------------------------------------------------------------


async def _locked(session: AsyncSession, signal_id: uuid.UUID, expected_version: int) -> CommercialSignal:
    signal = await session.scalar(select(CommercialSignal).where(CommercialSignal.id == signal_id).with_for_update())
    if signal is None:
        raise NotFound("Signal not found")
    if signal.version != expected_version:
        raise Conflict(
            "This case changed since you opened it. Reload and review again.",
            code="STALE_SIGNAL",
            details={"current_version": signal.version},
        )
    return signal


def _record(session: AsyncSession, signal: CommercialSignal, user: User, event: str, meta: dict[str, Any]) -> None:
    audit.record(
        session,
        workspace_id=signal.workspace_id,
        project_id=signal.project_id,
        actor_id=user.id,
        event_type=event,
        object_type="commercial_signal",
        object_id=signal.id,
        object_version=signal.version,
        metadata=meta,
    )


async def dismiss(
    session: AsyncSession, *, signal_id: uuid.UUID, user: User, expected_version: int, reason: str
) -> CommercialSignal:
    reason = reason.strip()
    if len(reason) < 3:
        raise Unprocessable("Say briefly why this is not a commercial change", code="REASON_REQUIRED")
    signal = await _locked(session, signal_id, expected_version)
    if signal.status not in ACTIVE_STATUSES:
        raise Conflict("Only open cases can be dismissed", code="INVALID_TRANSITION")
    signal.status = "DISMISSED"
    signal.resolution_reason = reason[:2000]
    signal.resolved_by = user.id
    signal.resolved_at = utcnow()
    signal.version += 1
    _record(session, signal, user, "signal.dismissed", {})
    await session.commit()
    return signal


async def resolve(
    session: AsyncSession, *, signal_id: uuid.UUID, user: User, expected_version: int, category: str, reason: str
) -> CommercialSignal:
    if category not in ("IN_SCOPE", "BUG_FIX"):
        raise Unprocessable("Choose in scope or bug fix", code="CATEGORY_REQUIRED")
    reason = reason.strip()
    if len(reason) < 3:
        raise Unprocessable("Explain the decision", code="REASON_REQUIRED")
    signal = await _locked(session, signal_id, expected_version)
    if signal.status not in ACTIVE_STATUSES:
        raise Conflict("Only open cases can be resolved", code="INVALID_TRANSITION")
    signal.status = "RESOLVED"
    signal.resolved_category = category
    signal.resolution_reason = reason[:2000]
    signal.resolved_by = user.id
    signal.resolved_at = utcnow()
    signal.version += 1
    _record(session, signal, user, "signal.resolved", {"category": category})
    await session.commit()
    return signal


async def request_clarification(
    session: AsyncSession, *, signal_id: uuid.UUID, user: User, expected_version: int
) -> tuple[CommercialSignal, list[str]]:
    """Marks the case as waiting for the client and returns suggested questions for the manager to send
    themselves. TermRail does not send them."""
    signal = await _locked(session, signal_id, expected_version)
    if signal.status not in ACTIVE_STATUSES:
        raise Conflict("Only open cases can wait for clarification", code="INVALID_TRANSITION")
    questions: list[str] = []
    if signal.latest_finding_id:
        finding = await session.get(Finding, signal.latest_finding_id)
        if finding is not None:
            questions = list(finding.clarifying_questions or [])
    signal.status = "CLARIFICATION_REQUESTED"
    signal.version += 1
    _record(session, signal, user, "signal.clarification_requested", {"questions": len(questions)})
    await session.commit()
    return signal, questions


async def convert_to_request(session: AsyncSession, *, signal_id: uuid.UUID, user: User) -> ClientRequest:
    """Ensure the case has a request in the regular review workflow (estimates, change orders).
    Analysis-derived cases already have one; mention-only cases get one from their still-valid evidence."""
    signal = await session.scalar(select(CommercialSignal).where(CommercialSignal.id == signal_id).with_for_update())
    if signal is None:
        raise NotFound("Signal not found")
    if signal.request_id is not None:
        req = await session.get(ClientRequest, signal.request_id)
        assert req is not None
        return req
    quotes = [e.quote for e in await evidence_views(session, signal.id) if e.quote]
    if not quotes:
        raise Conflict("The cited messages are no longer available", code="EVIDENCE_UNAVAILABLE")
    project = await session.get(Project, signal.project_id)
    binding = await session.get(TelegramChatBinding, signal.binding_id) if signal.binding_id else None
    assert project is not None
    req = ClientRequest(
        workspace_id=project.workspace_id,
        project_id=project.id,
        channel="TELEGRAM",
        external_id=f"telegram-signal:{signal.id}",
        content_hash=intake.content_hash("\n\n".join(quotes)),
        sender=binding.display_name if binding else "",
        subject="",
        message_text="\n\n".join(quotes)[: intake.MAX_MESSAGE_CHARS],
        status="NEW",
        created_by=user.id,
        origin="USER",  # a person chose to turn this case into a request
    )
    session.add(req)
    await session.flush()
    signal.request_id = req.id
    signal.version += 1
    _record(session, signal, user, "signal.converted_to_request", {"request_id": str(req.id)})
    await session.commit()
    return req


async def create_change_order_draft(
    session: AsyncSession,
    *,
    signal_id: uuid.UUID,
    user: User,
    expected_version: int,
    estimate_ids: list[uuid.UUID],
    title: str,
    language: str,
    idempotency_key: str | None,
) -> CommercialSignal:
    """Delegates to the existing change-order workflow: requires human-approved estimates built from the
    rate card. The result is a DRAFT; nothing is sent, signed or billed."""
    signal = await _locked(session, signal_id, expected_version)
    if signal.request_id is None:
        raise Conflict("Turn this case into a request and estimate it first", code="ESTIMATE_REQUIRED")
    if signal.evidence_state != "VALID":
        raise Conflict("The client's messages changed; review the case again first", code="EVIDENCE_CHANGED")
    request = await session.get(ClientRequest, signal.request_id)
    project = await session.get(Project, signal.project_id)
    assert request is not None and project is not None
    co, _ = await change_orders.create_change_order(
        session,
        project=project,
        request=request,
        user=user,
        estimate_ids=estimate_ids,
        title=title,
        language=language,
        idempotency_key=idempotency_key,
    )
    signal = await _locked(session, signal_id, expected_version)
    signal.status = "CONVERTED"
    signal.change_order_id = co.id
    signal.resolved_by = user.id
    signal.resolved_at = utcnow()
    signal.version += 1
    _record(session, signal, user, "signal.change_order_drafted", {"change_order_id": str(co.id)})
    await session.commit()
    return signal
