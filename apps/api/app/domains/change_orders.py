"""Change orders: immutable revisions, an explicit state machine, approvals bound to the exact
revision + content hash, and PDF export of approved revisions only (draft previews are watermarked)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, Unprocessable
from app.db.models import (
    Approval,
    ChangeOrder,
    ChangeOrderExport,
    ChangeOrderRevision,
    ClientRequest,
    DocumentVersion,
    Estimate,
    Finding,
    FindingEvidence,
    Project,
    RequestItem,
    ScopeBaseline,
    SourceSpan,
    User,
)
from app.domains import audit
from app.domains.estimates import estimate_lines
from app.domains.money import total
from app.parsing.parser import anchor_label
from app.pdf.change_order import DEFAULT_TITLES, SUPPORTED_LANGUAGES
from app.storage import export_key, get_storage

# state -> allowed transitions
TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"INTERNAL_REVIEW", "CANCELLED"},
    "INTERNAL_REVIEW": {"DRAFT", "APPROVED_INTERNAL", "CANCELLED"},
    "APPROVED_INTERNAL": {"EXPORTED", "DRAFT", "CANCELLED"},
    "EXPORTED": {"EXPORTED", "DRAFT"},
    "CANCELLED": set(),
}
EDITABLE_FIELDS = ("title", "summary", "terms", "acceptance_criteria", "exclusions", "valid_until", "timeline_days")


def _transition(co: ChangeOrder, target: str) -> None:
    if target not in TRANSITIONS.get(co.status, set()):
        raise Conflict(
            f"Cannot move a change order from {co.status} to {target}",
            code="INVALID_TRANSITION",
            details={"from": co.status, "to": target},
        )
    co.status = target


def content_hash(content: dict[str, Any]) -> str:
    blob = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def _locked(session: AsyncSession, co_id: uuid.UUID) -> ChangeOrder:
    co = await session.scalar(
        select(ChangeOrder).where(ChangeOrder.id == co_id).with_for_update().execution_options(populate_existing=True)
    )
    if co is None:
        raise NotFound("Change order not found")
    return co


async def current_revision(session: AsyncSession, co: ChangeOrder) -> ChangeOrderRevision:
    rev = await session.get(ChangeOrderRevision, co.current_revision_id) if co.current_revision_id else None
    if rev is None:
        raise NotFound("Change order revision not found")
    return rev


async def _item_payload(session: AsyncSession, request: ClientRequest, estimate: Estimate) -> dict[str, Any]:
    item = await session.get(RequestItem, estimate.request_item_id)
    finding = await session.get(Finding, estimate.finding_id)
    assert item is not None and finding is not None
    rows = await session.execute(
        select(FindingEvidence, SourceSpan, DocumentVersion)
        .join(SourceSpan, SourceSpan.id == FindingEvidence.source_span_id)
        .join(DocumentVersion, DocumentVersion.id == SourceSpan.document_version_id)
        .where(FindingEvidence.finding_id == finding.id, FindingEvidence.polarity == "SUPPORTING")
        .order_by(SourceSpan.ordinal)
    )
    evidence = [
        {
            "span_id": str(span.id),
            "quote": fe.quote,
            "document_title": doc.title,
            "document_version": doc.version,
            "anchor": anchor_label(span.anchor_type, span.page, span.paragraph_index, span.table_ref),
        }
        for fe, span, doc in rows.all()
    ]
    lines = await estimate_lines(session, estimate.id)
    return {
        "request_item_id": str(item.id),
        "requirement": item.exact_text,
        "summary": finding.summary,
        "category": finding.final_category,
        "reason": finding.reason,
        "evidence": evidence,
        "estimate": {
            "id": str(estimate.id),
            "version": estimate.version,
            "rate_card_revision": estimate.rate_card_revision,
            "timeline_days": estimate.timeline_days,
            "subtotal": str(estimate.subtotal),
            "lines": [
                {
                    "kind": ln.kind,
                    "description": ln.description,
                    "role": ln.role,
                    "hours": str(ln.hours) if ln.hours is not None else None,
                    "rate": str(ln.rate_snapshot) if ln.rate_snapshot is not None else None,
                    "amount": str(ln.amount),
                }
                for ln in lines
            ],
        },
    }


def _recompute_totals(content: dict[str, Any]) -> None:
    content["total"] = str(total([Decimal(i["estimate"]["subtotal"]) for i in content["items"]]))
    if content.get("timeline_days") is None:
        days = [i["estimate"]["timeline_days"] for i in content["items"] if i["estimate"]["timeline_days"] is not None]
        content["timeline_days"] = sum(days) if days else None


async def create_change_order(
    session: AsyncSession,
    *,
    project: Project,
    request: ClientRequest,
    user: User,
    estimate_ids: list[uuid.UUID],
    title: str,
    language: str,
    idempotency_key: str | None,
) -> tuple[ChangeOrder, bool]:
    if idempotency_key:
        existing = await session.scalar(
            select(ChangeOrder).where(
                ChangeOrder.project_id == project.id, ChangeOrder.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing, False
    if not estimate_ids:
        raise Unprocessable("Select at least one approved estimate", code="ESTIMATE_REQUIRED")
    estimates = list((await session.scalars(select(Estimate).where(Estimate.id.in_(estimate_ids)))).all())
    if len(estimates) != len(set(estimate_ids)) or any(e.request_id != request.id for e in estimates):
        raise NotFound("Estimate not found")
    if any(e.status != "APPROVED" for e in estimates):
        raise Conflict("Only approved estimates can be included in a change order", code="ESTIMATE_NOT_APPROVED")
    if len({e.request_item_id for e in estimates}) != len(estimates):
        raise Unprocessable("Choose one estimate per requirement", code="DUPLICATE_REQUIREMENT")
    for e in estimates:
        newer = await session.scalar(
            select(func.count())
            .select_from(Estimate)
            .where(
                Estimate.request_item_id == e.request_item_id,
                Estimate.version > e.version,
                Estimate.status == "APPROVED",
            )
        )
        if newer:
            raise Conflict("A newer approved estimate exists for one of the requirements", code="STALE_ESTIMATE")

    finding = await session.get(Finding, estimates[0].finding_id)
    from app.db.models import AnalysisRun

    run = await session.get(AnalysisRun, finding.analysis_run_id) if finding else None
    baseline = await session.get(ScopeBaseline, run.baseline_id) if run else None
    assert baseline is not None

    number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(ChangeOrder.number), 0)).where(ChangeOrder.project_id == project.id)
            )
            or 0
        )
        + 1
    )
    items = [await _item_payload(session, request, e) for e in sorted(estimates, key=lambda e: str(e.request_item_id))]
    # Keep requirement order as in the client message.
    ordinals = {
        str(i.id): i.ordinal
        for i in (await session.scalars(select(RequestItem).where(RequestItem.request_id == request.id))).all()
    }
    items.sort(key=lambda i: ordinals.get(i["request_item_id"], 0))
    content: dict[str, Any] = {
        "schema": "change-order-v1",
        "language": language if language in SUPPORTED_LANGUAGES else "en",
        "number": number,
        "title": title.strip() or DEFAULT_TITLES.get(language, DEFAULT_TITLES["en"]).format(n=number),
        "summary": "",
        "project": {"id": str(project.id), "title": project.title, "client_name": project.client_name},
        "currency": project.currency,
        "baseline": {"id": str(baseline.id), "version": baseline.version, "hash": baseline.baseline_hash},
        "request": {
            "id": str(request.id),
            "received_at": request.received_at.isoformat(),
            "sender": request.sender,
            "subject": request.subject,
        },
        "items": items,
        "timeline_days": None,
        "terms": "",
        "acceptance_criteria": "",
        "exclusions": "",
        "valid_until": None,
    }
    _recompute_totals(content)

    co = ChangeOrder(
        workspace_id=project.workspace_id,
        project_id=project.id,
        request_id=request.id,
        number=number,
        status="DRAFT",
        idempotency_key=idempotency_key,
        created_by=user.id,
    )
    session.add(co)
    await session.flush()
    rev = ChangeOrderRevision(
        change_order_id=co.id,
        revision_no=1,
        content_json=content,
        content_hash=content_hash(content),
        created_by=user.id,
    )
    session.add(rev)
    await session.flush()
    co.current_revision_id = rev.id
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="change_order.created",
        object_type="change_order",
        object_id=co.id,
        object_version=1,
        metadata={"total": content["total"], "currency": content["currency"], "items": len(items)},
    )
    await session.commit()
    return co, True


def _validate_edit(changes: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key == "valid_until":
            if value in (None, ""):
                clean[key] = None
            else:
                try:
                    clean[key] = date.fromisoformat(str(value)).isoformat()
                except ValueError as exc:
                    raise Unprocessable("valid_until must be a date (YYYY-MM-DD)", code="INVALID_DATE") from exc
        elif key == "timeline_days":
            if value is None:
                clean[key] = None
            else:
                if not isinstance(value, int) or value < 0 or value > 3650:
                    raise Unprocessable("timeline_days must be 0..3650", code="INVALID_TIMELINE")
                clean[key] = value
        else:
            text = str(value or "").strip()
            limit = 300 if key == "title" else 5000
            if key == "title" and not text:
                raise Unprocessable("Title cannot be empty", code="TITLE_REQUIRED")
            clean[key] = text[:limit]
    return clean


async def edit_draft(
    session: AsyncSession, *, co_id: uuid.UUID, user: User, expected_revision_no: int, changes: dict[str, Any]
) -> ChangeOrder:
    co = await _locked(session, co_id)
    rev = await current_revision(session, co)
    if rev.revision_no != expected_revision_no:
        raise Conflict(
            "The change order was edited by someone else. Reload and re-apply your edits.",
            code="STALE_REVISION",
            details={"current_revision_no": rev.revision_no},
        )
    if co.status == "INTERNAL_REVIEW":
        raise Conflict("Request changes before editing a change order that is in review", code="IN_REVIEW")
    if co.status == "CANCELLED":
        raise Conflict("Cancelled change orders cannot be edited", code="INVALID_TRANSITION")
    clean = _validate_edit(changes)
    content = json.loads(json.dumps(rev.content_json))
    content.update(clean)
    _recompute_totals(content)
    new_hash = content_hash(content)
    if new_hash == rev.content_hash:
        return co
    was_approved = co.status in ("APPROVED_INTERNAL", "EXPORTED")
    new_rev = ChangeOrderRevision(
        change_order_id=co.id,
        revision_no=rev.revision_no + 1,
        content_json=content,
        content_hash=new_hash,
        created_by=user.id,
    )
    session.add(new_rev)
    await session.flush()
    co.current_revision_id = new_rev.id
    if was_approved:
        # Any edit after approval invalidates it: the approval stays bound to the old revision.
        _transition(co, "DRAFT")
        co.approved_revision_id = None
    co.lock_version += 1
    audit.record(
        session,
        workspace_id=co.workspace_id,
        project_id=co.project_id,
        actor_id=user.id,
        event_type="change_order.revised",
        object_type="change_order",
        object_id=co.id,
        object_version=new_rev.revision_no,
        metadata={"fields": sorted(clean), "approval_invalidated": was_approved},
    )
    await session.commit()
    return co


async def submit(session: AsyncSession, *, co_id: uuid.UUID, user: User) -> ChangeOrder:
    co = await _locked(session, co_id)
    _transition(co, "INTERNAL_REVIEW")
    co.lock_version += 1
    audit.record(
        session,
        workspace_id=co.workspace_id,
        project_id=co.project_id,
        actor_id=user.id,
        event_type="change_order.submitted",
        object_type="change_order",
        object_id=co.id,
    )
    await session.commit()
    return co


async def request_changes(session: AsyncSession, *, co_id: uuid.UUID, user: User, comment: str) -> ChangeOrder:
    co = await _locked(session, co_id)
    rev = await current_revision(session, co)
    if co.status != "INTERNAL_REVIEW":
        raise Conflict("Only change orders in internal review can be sent back", code="INVALID_TRANSITION")
    _transition(co, "DRAFT")
    co.lock_version += 1
    session.add(
        Approval(
            workspace_id=co.workspace_id,
            target_type="CHANGE_ORDER_REVISION",
            target_id=rev.id,
            content_hash=rev.content_hash,
            actor_id=user.id,
            decision="CHANGES_REQUESTED",
            comment=comment.strip()[:2000],
        )
    )
    audit.record(
        session,
        workspace_id=co.workspace_id,
        project_id=co.project_id,
        actor_id=user.id,
        event_type="change_order.changes_requested",
        object_type="change_order",
        object_id=co.id,
        object_version=rev.revision_no,
    )
    await session.commit()
    return co


async def approve(
    session: AsyncSession, *, co_id: uuid.UUID, user: User, revision_id: uuid.UUID, content_hash_: str, comment: str
) -> ChangeOrder:
    co = await _locked(session, co_id)  # row lock: concurrent approvals serialize; the 2nd sees the new state
    if co.status != "INTERNAL_REVIEW":
        raise Conflict(
            "Only change orders in internal review can be approved",
            code="INVALID_TRANSITION",
            details={"status": co.status},
        )
    rev = await current_revision(session, co)
    if rev.id != revision_id or rev.content_hash != content_hash_:
        raise Conflict(
            "You are approving an outdated revision. Reload and review the current one.",
            code="STALE_REVISION",
            details={"current_revision_id": str(rev.id)},
        )
    _transition(co, "APPROVED_INTERNAL")
    co.approved_revision_id = rev.id
    co.lock_version += 1
    session.add(
        Approval(
            workspace_id=co.workspace_id,
            target_type="CHANGE_ORDER_REVISION",
            target_id=rev.id,
            content_hash=rev.content_hash,
            actor_id=user.id,
            decision="APPROVED",
            comment=comment.strip()[:2000],
        )
    )
    audit.record(
        session,
        workspace_id=co.workspace_id,
        project_id=co.project_id,
        actor_id=user.id,
        event_type="change_order.approved",
        object_type="change_order",
        object_id=co.id,
        object_version=rev.revision_no,
        metadata={"content_hash": rev.content_hash, "total": rev.content_json.get("total")},
    )
    await session.commit()
    return co


async def cancel(session: AsyncSession, *, co_id: uuid.UUID, user: User) -> ChangeOrder:
    co = await _locked(session, co_id)
    _transition(co, "CANCELLED")
    co.lock_version += 1
    audit.record(
        session,
        workspace_id=co.workspace_id,
        project_id=co.project_id,
        actor_id=user.id,
        event_type="change_order.cancelled",
        object_type="change_order",
        object_id=co.id,
    )
    await session.commit()
    return co


async def export_pdf(session: AsyncSession, *, co_id: uuid.UUID, user: User, draft: bool) -> ChangeOrderExport:
    from app.pdf.change_order import render_change_order_pdf

    co = await _locked(session, co_id)
    approver: User | None = None
    approval: Approval | None = None
    if draft:
        if co.status == "CANCELLED":
            raise Conflict("Cancelled change orders cannot be exported", code="INVALID_TRANSITION")
        rev = await current_revision(session, co)
        approved = False
    else:
        if co.status not in ("APPROVED_INTERNAL", "EXPORTED") or co.approved_revision_id is None:
            raise Conflict("Only an approved revision can be exported", code="APPROVAL_REQUIRED")
        if co.approved_revision_id != co.current_revision_id:
            raise Conflict("The current revision is not the approved one", code="APPROVAL_REQUIRED")
        approved_rev = await session.get(ChangeOrderRevision, co.approved_revision_id)
        assert approved_rev is not None
        rev = approved_rev
        approval = await session.scalar(
            select(Approval)
            .where(
                Approval.target_type == "CHANGE_ORDER_REVISION",
                Approval.target_id == rev.id,
                Approval.decision == "APPROVED",
                Approval.content_hash == rev.content_hash,
            )
            .order_by(Approval.decided_at.desc())
            .limit(1)
        )
        if approval is None:
            raise Conflict("No approval matches this revision's content hash", code="APPROVAL_REQUIRED")
        approved = True
        approver = await session.get(User, approval.actor_id)
    meta = {
        "revision_no": rev.revision_no,
        "content_hash": rev.content_hash,
        "status": "APPROVED_INTERNAL" if approved else co.status,
        "approved_by": (approver.display_name or approver.email) if approved and approver else None,
        "approved_at": approval.decided_at.isoformat() if approval else None,
        "draft": not approved,
    }
    pdf_bytes = await asyncio.to_thread(render_change_order_pdf, rev.content_json, meta)
    export = ChangeOrderExport(
        workspace_id=co.workspace_id,
        change_order_id=co.id,
        revision_id=rev.id,
        content_hash=rev.content_hash,
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        storage_path="",
        is_draft=not approved,
        created_by=user.id,
    )
    export.id = uuid.uuid4()
    export.storage_path = export_key(co.workspace_id, co.project_id, export.id)
    await asyncio.to_thread(get_storage().put, export.storage_path, pdf_bytes)
    session.add(export)
    if approved:
        _transition(co, "EXPORTED")
        co.lock_version += 1
    audit.record(
        session,
        workspace_id=co.workspace_id,
        project_id=co.project_id,
        actor_id=user.id,
        event_type="change_order.exported",
        object_type="change_order",
        object_id=co.id,
        object_version=rev.revision_no,
        metadata={"draft": not approved, "pdf_sha256": export.pdf_sha256, "content_hash": rev.content_hash},
    )
    await session.commit()
    return export
