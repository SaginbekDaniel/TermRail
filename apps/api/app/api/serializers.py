"""Builders for nested API responses (kept out of the route handlers)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas as S
from app.db.models import (
    AnalysisRun,
    Approval,
    AuditEvent,
    ChangeOrder,
    ChangeOrderExport,
    ChangeOrderRevision,
    ClientRequest,
    DocumentVersion,
    Estimate,
    Finding,
    FindingEvidence,
    FindingReview,
    Job,
    Project,
    RequestItem,
    ScopeBaseline,
    ScopeItem,
    SourceSpan,
    User,
)
from app.domains import estimates as est_domain
from app.domains import scope as scope_domain
from app.domains.intake import request_items


async def user_names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    clean = {i for i in ids if i}
    if not clean:
        return {}
    rows = await session.execute(select(User.id, User.display_name, User.email).where(User.id.in_(clean)))
    return {r[0]: (r[1] or r[2]) for r in rows.all()}


def job_out(job: Job | None) -> S.JobOut | None:
    return S.JobOut.model_validate(job) if job else None


async def baseline_out(session: AsyncSession, baseline: ScopeBaseline) -> S.BaselineOut:
    views = await scope_domain.baseline_items(session, baseline.id)
    names = await user_names(session, {baseline.approved_by})
    return S.BaselineOut(
        id=baseline.id,
        project_id=baseline.project_id,
        version=baseline.version,
        status=baseline.status,
        draft_revision=baseline.draft_revision,
        baseline_hash=baseline.baseline_hash,
        approved_by=baseline.approved_by,
        approved_by_name=names.get(baseline.approved_by) if baseline.approved_by else None,
        approved_at=baseline.approved_at,
        approval_note=baseline.approval_note,
        based_on_baseline_id=baseline.based_on_baseline_id,
        created_at=baseline.created_at,
        items=[
            S.ScopeItemOut(
                id=v.item.id,
                ordinal=v.item.ordinal,
                title=v.item.title,
                description=v.item.description,
                inclusion_type=v.item.inclusion_type,  # type: ignore[arg-type]
                acceptance_criteria=v.item.acceptance_criteria,
                origin=v.item.origin,
                accepted=v.item.accepted,
                evidence=[
                    S.EvidenceRefOut(
                        span_id=s.id,
                        document_version_id=d.id,
                        document_title=d.title,
                        document_version=d.version,
                        anchor_type=s.anchor_type,
                        page=s.page,
                        paragraph_index=s.paragraph_index,
                        table_ref=s.table_ref,
                        text=s.normalized_text,
                    )
                    for s, d in v.spans
                ],
            )
            for v in views
        ],
    )


async def findings_out(session: AsyncSession, run_id: uuid.UUID) -> list[S.FindingOut]:
    findings = list(
        (
            await session.scalars(select(Finding).where(Finding.analysis_run_id == run_id).order_by(Finding.created_at))
        ).all()
    )
    if not findings:
        return []
    ids = [f.id for f in findings]
    ev_rows = await session.execute(
        select(FindingEvidence, SourceSpan, DocumentVersion, ScopeItem)
        .join(SourceSpan, SourceSpan.id == FindingEvidence.source_span_id)
        .join(DocumentVersion, DocumentVersion.id == SourceSpan.document_version_id)
        .outerjoin(ScopeItem, ScopeItem.id == FindingEvidence.scope_item_id)
        .where(FindingEvidence.finding_id.in_(ids))
        .order_by(FindingEvidence.polarity.desc(), SourceSpan.ordinal)
    )
    evidence: dict[uuid.UUID, list[S.FindingEvidenceOut]] = {}
    for fe, span, doc, item in ev_rows.all():
        evidence.setdefault(fe.finding_id, []).append(
            S.FindingEvidenceOut(
                span_id=span.id,
                polarity=fe.polarity,  # type: ignore[arg-type]
                quote=fe.quote,
                scope_item_id=fe.scope_item_id,
                scope_item_title=item.title if item else None,
                inclusion_type=item.inclusion_type if item else None,
                document_version_id=doc.id,
                document_title=doc.title,
                document_version=doc.version,
                anchor_type=span.anchor_type,
                page=span.page,
                paragraph_index=span.paragraph_index,
                table_ref=span.table_ref,
                span_text=span.normalized_text,
            )
        )
    rev_rows = list(
        (
            await session.scalars(
                select(FindingReview).where(FindingReview.finding_id.in_(ids)).order_by(FindingReview.created_at)
            )
        ).all()
    )
    names = await user_names(session, {r.actor_id for r in rev_rows})
    reviews: dict[uuid.UUID, list[S.FindingReviewOut]] = {}
    for r in rev_rows:
        reviews.setdefault(r.finding_id, []).append(
            S.FindingReviewOut(
                decision=r.decision,
                category=r.category,
                reason=r.reason,
                actor_name=names.get(r.actor_id, "?"),
                created_at=r.created_at,
            )
        )
    # Keep the requirement order.
    item_order = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Finding.request_item_id, func.min(Finding.created_at))
                .where(Finding.id.in_(ids))
                .group_by(Finding.request_item_id)
            )
        ).all()
    }
    ordinals = {
        i.id: i.ordinal
        for i in (await session.scalars(select(RequestItem).where(RequestItem.id.in_(list(item_order))))).all()
    }
    findings.sort(key=lambda f: ordinals.get(f.request_item_id, 0))
    return [
        S.FindingOut(
            id=f.id,
            request_item_id=f.request_item_id,
            category=f.category,  # type: ignore[arg-type]
            ai_category=f.ai_category,  # type: ignore[arg-type]
            final_category=f.final_category,  # type: ignore[arg-type]
            summary=f.summary,
            reason=f.reason,
            uncertainties=f.uncertainties,
            clarifying_questions=f.clarifying_questions,
            policy_notes=f.policy_notes,
            validation_errors=f.validation_errors,
            model_confidence=f.model_confidence,
            needs_review=f.needs_review,
            review_status=f.review_status,
            evidence=evidence.get(f.id, []),
            reviews=reviews.get(f.id, []),
        )
        for f in findings
    ]


async def run_out(session: AsyncSession, run: AnalysisRun) -> S.AnalysisRunOut:
    baseline = await session.get(ScopeBaseline, run.baseline_id)
    job = await session.get(Job, run.job_id) if run.job_id else None
    return S.AnalysisRunOut(
        id=run.id,
        request_id=run.request_id,
        baseline_id=run.baseline_id,
        baseline_version=baseline.version if baseline else 0,
        status=run.status,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        schema_version=run.schema_version,
        token_usage=run.token_usage or {},
        error_code=run.error_code,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        job=job_out(job),
        findings=await findings_out(session, run.id),
    )


async def request_out(
    session: AsyncSession, request: ClientRequest, project: Project, possible_duplicate_of: uuid.UUID | None = None
) -> S.RequestOut:
    from app.domains.analysis import latest_run

    run = await latest_run(session, request.id)
    items = await request_items(session, request.id)
    return S.RequestOut(
        id=request.id,
        project_id=request.project_id,
        project_title=project.title,
        channel=request.channel,
        sender=request.sender,
        subject=request.subject,
        message_text=request.message_text,
        status=request.status,
        received_at=request.received_at,
        created_at=request.created_at,
        possible_duplicate_of=possible_duplicate_of,
        items=[S.RequestItemOut.model_validate(i) for i in items],
        latest_run=await run_out(session, run) if run else None,
    )


async def request_list(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID | None, limit: int = 100
) -> list[S.RequestListItemOut]:
    q = (
        select(ClientRequest, Project.title)
        .join(Project, Project.id == ClientRequest.project_id)
        .where(ClientRequest.workspace_id == workspace_id)
    )
    if project_id:
        q = q.where(ClientRequest.project_id == project_id)
    rows = (await session.execute(q.order_by(ClientRequest.received_at.desc()).limit(limit))).all()
    out: list[S.RequestListItemOut] = []
    for req, title in rows:
        latest = await session.scalar(
            select(AnalysisRun.id)
            .where(AnalysisRun.request_id == req.id)
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
        cats: dict[str, int] = {}
        pending = 0
        if latest:
            for f in (await session.scalars(select(Finding).where(Finding.analysis_run_id == latest))).all():
                key = f.final_category or f.category
                cats[key] = cats.get(key, 0) + 1
                pending += 1 if f.review_status == "PENDING" else 0
        n_items = await session.scalar(
            select(func.count()).select_from(RequestItem).where(RequestItem.request_id == req.id)
        )
        out.append(
            S.RequestListItemOut(
                id=req.id,
                project_id=req.project_id,
                project_title=title,
                sender=req.sender,
                subject=req.subject,
                excerpt=req.message_text[:180],
                status=req.status,
                received_at=req.received_at,
                items=int(n_items or 0),
                pending_reviews=pending,
                categories=cats,
            )
        )
    return out


async def estimate_out(session: AsyncSession, e: Estimate) -> S.EstimateOut:
    lines = await est_domain.estimate_lines(session, e.id)
    return S.EstimateOut(
        id=e.id,
        request_id=e.request_id,
        request_item_id=e.request_item_id,
        finding_id=e.finding_id,
        version=e.version,
        status=e.status,
        currency=e.currency,
        rate_card_revision=e.rate_card_revision,
        subtotal=e.subtotal,
        timeline_days=e.timeline_days,
        notes=e.notes,
        approved_at=e.approved_at,
        created_at=e.created_at,
        lines=[S.EstimateLineOut.model_validate(ln) for ln in lines],
    )


def allowed_actions(co: ChangeOrder) -> list[str]:
    return {
        "DRAFT": ["edit", "submit", "cancel", "preview"],
        "INTERNAL_REVIEW": ["approve", "request_changes", "cancel", "preview"],
        "APPROVED_INTERNAL": ["export", "edit", "cancel", "preview"],
        "EXPORTED": ["export", "edit", "preview"],
        "CANCELLED": [],
    }.get(co.status, [])


async def change_order_out(session: AsyncSession, co: ChangeOrder) -> S.ChangeOrderOut:
    project = await session.get(Project, co.project_id)
    assert project is not None
    revisions = list(
        (
            await session.scalars(
                select(ChangeOrderRevision)
                .where(ChangeOrderRevision.change_order_id == co.id)
                .order_by(ChangeOrderRevision.revision_no.desc())
            )
        ).all()
    )
    rev_ids = [r.id for r in revisions]
    approvals = list(
        (
            await session.scalars(
                select(Approval)
                .where(Approval.target_type == "CHANGE_ORDER_REVISION", Approval.target_id.in_(rev_ids))
                .order_by(Approval.decided_at.desc())
            )
        ).all()
    )
    exports = list(
        (
            await session.scalars(
                select(ChangeOrderExport)
                .where(ChangeOrderExport.change_order_id == co.id)
                .order_by(ChangeOrderExport.created_at.desc())
            )
        ).all()
    )
    names = await user_names(session, {r.created_by for r in revisions} | {a.actor_id for a in approvals})

    def rev_out(r: ChangeOrderRevision) -> S.RevisionOut:
        return S.RevisionOut(
            id=r.id,
            revision_no=r.revision_no,
            content_hash=r.content_hash,
            content=r.content_json,
            created_by_name=names.get(r.created_by, "?"),
            created_at=r.created_at,
        )

    current = next(r for r in revisions if r.id == co.current_revision_id)
    return S.ChangeOrderOut(
        id=co.id,
        project_id=co.project_id,
        project_title=project.title,
        request_id=co.request_id,
        number=co.number,
        status=co.status,
        current_revision_id=co.current_revision_id,
        approved_revision_id=co.approved_revision_id,
        current=rev_out(current),
        revisions=[rev_out(r) for r in revisions],
        approvals=[
            S.ApprovalOut(
                id=a.id,
                target_id=a.target_id,
                decision=a.decision,
                comment=a.comment,
                content_hash=a.content_hash,
                actor_name=names.get(a.actor_id, "?"),
                decided_at=a.decided_at,
            )
            for a in approvals
        ],
        exports=[
            S.ExportOut(
                id=x.id,
                revision_id=x.revision_id,
                content_hash=x.content_hash,
                pdf_sha256=x.pdf_sha256,
                is_draft=x.is_draft,
                created_at=x.created_at,
                download_path=f"/change-orders/{co.id}/exports/{x.id}/download",
            )
            for x in exports
        ],
        allowed_actions=allowed_actions(co),
        created_at=co.created_at,
        updated_at=co.updated_at,
    )


async def audit_out(session: AsyncSession, events: list[AuditEvent]) -> list[S.AuditOut]:
    names = await user_names(session, {e.actor_id for e in events})
    return [
        S.AuditOut(
            id=e.id,
            project_id=e.project_id,
            actor_type=e.actor_type,
            actor_name=names.get(e.actor_id) if e.actor_id else None,
            event_type=e.event_type,
            object_type=e.object_type,
            object_id=e.object_id,
            object_version=e.object_version,
            metadata=e.event_metadata,
            occurred_at=e.occurred_at,
        )
        for e in events
    ]


def document_out(v: DocumentVersion, f: Any, span_count: int) -> S.DocumentOut:
    return S.DocumentOut(
        id=v.id,
        project_id=v.project_id,
        version=v.version,
        title=v.title,
        original_name=f.original_name,
        mime=f.mime,
        bytes=f.bytes,
        sha256=f.sha256,
        parse_status=v.parse_status,
        parse_error=v.parse_error,
        parser_version=v.parser_version,
        page_count=v.page_count,
        text_chars=v.text_chars,
        quality=v.quality or {},
        span_count=span_count,
        created_at=v.created_at,
    )
