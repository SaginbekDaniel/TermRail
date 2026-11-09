"""Pipeline B: client request -> atomic requirements -> evidence -> AI classification ->
server validation + policy gates -> persisted findings -> human review."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, Unprocessable
from app.db.models import (
    AnalysisRun,
    ClientRequest,
    Finding,
    FindingEvidence,
    FindingReview,
    Project,
    RequestItem,
    ScopeBaseline,
    User,
)
from app.domains import audit, scope
from app.domains.evidence import (
    CATEGORIES,
    Candidate,
    assemble_candidates,
    baseline_candidates,
    check_refs,
    gate,
    locate_requirements,
    retrieve_text_matches,
)
from app.domains.intake import request_items
from app.jobs import queue
from app.llm.base import LLMInvalidOutput, LLMProvider, LLMResult
from app.llm.factory import get_llm
from app.llm.prompts import (
    CLASSIFY_PROMPT_VERSION,
    CLASSIFY_SCHEMA,
    CLASSIFY_SYSTEM,
    SCHEMA_VERSION,
    SPLIT_PROMPT_VERSION,
    SPLIT_SCHEMA,
    SPLIT_SYSTEM,
    render_classify_user,
    render_split_user,
)

PROMPT_VERSION = f"{SPLIT_PROMPT_VERSION}+{CLASSIFY_PROMPT_VERSION}"


async def start_analysis(
    session: AsyncSession,
    *,
    project: Project,
    request: ClientRequest,
    user: User,
    baseline_id: uuid.UUID | None,
    idempotency_key: str | None,
    on_behalf: bool = False,
) -> tuple[AnalysisRun, bool]:
    """Create (or return) an analysis run bound to the CURRENT approved baseline and queue it.

    on_behalf=True: started by a connector for `user` (audit records the worker, not the person)."""
    if idempotency_key:
        existing = await session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.request_id == request.id, AnalysisRun.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing, False
    active = await session.scalar(
        select(AnalysisRun).where(AnalysisRun.request_id == request.id, AnalysisRun.status.in_(("QUEUED", "RUNNING")))
    )
    if active is not None:
        return active, False

    baseline = await scope.current_approved(session, project.id)
    if baseline is None:
        raise Conflict("Approve the project's scope baseline before analysing requests", code="BASELINE_REQUIRED")
    if baseline_id is not None and baseline_id != baseline.id:
        raise Conflict(
            "The selected baseline is not the current approved baseline",
            code="STALE_BASELINE",
            details={"current_baseline_id": str(baseline.id)},
        )

    run = AnalysisRun(
        workspace_id=project.workspace_id,
        project_id=project.id,
        request_id=request.id,
        baseline_id=baseline.id,
        idempotency_key=idempotency_key,
        status="QUEUED",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        created_by=user.id,
        token_usage={},
    )
    session.add(run)
    await session.flush()
    job = await queue.enqueue(
        session,
        kind="analyze_request",
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"analysis_run_id": str(run.id)},
        idempotency_key=f"analyze:{run.id}",
        created_by=user.id,
        max_attempts=3,
    )
    run.job_id = job.id
    request.status = "ANALYZING"
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=None if on_behalf else user.id,
        actor_type="WORKER" if on_behalf else "USER",
        event_type="analysis.started",
        object_type="analysis_run",
        object_id=run.id,
        metadata={
            "request_id": str(request.id),
            "baseline_id": str(baseline.id),
            "baseline_version": baseline.version,
            **({"on_behalf_of": str(user.id)} if on_behalf else {}),
        },
    )
    await session.commit()
    return run, True


async def _split(llm: LLMProvider, message: str) -> tuple[list[Any], list[str], LLMResult]:
    result = await llm.generate_json(
        task="split_requirements",
        system=SPLIT_SYSTEM,
        user=render_split_user(message),
        schema=SPLIT_SCHEMA,
        context={"message": message},
    )
    raw = result.data.get("requirements")
    if not isinstance(raw, list):
        raise LLMInvalidOutput("split output has no requirements list")
    items, notes = locate_requirements(message, raw)
    return items, notes, result


async def _classify(
    llm: LLMProvider,
    *,
    item: RequestItem,
    message: str,
    candidates: list[Candidate],
    project: Project,
) -> tuple[dict[str, Any], list[str], dict[str, int], str]:
    """Ask the model; if it cites refs that do not exist, ask once more, then give up (fail closed)."""
    cand_map = {c.ref: c for c in candidates}
    evidence = [c.prompt_dict() for c in candidates]
    user_prompt = render_classify_user(
        requirement=item.exact_text,
        full_message=message,
        evidence=evidence,
        project={"title": project.title, "client": project.client_name, "currency": project.currency},
    )
    usage: dict[str, int] = {}
    model = ""
    bad: list[str] = []
    data: dict[str, Any] = {}
    for attempt in range(2):
        prompt = user_prompt
        if attempt and bad:
            prompt += (
                f"\nYour previous answer cited refs that do not exist ({', '.join(bad)}). "
                "Cite only refs from the evidence list."
            )
        result = await llm.generate_json(
            task="classify_requirement",
            system=CLASSIFY_SYSTEM,
            user=prompt,
            schema=CLASSIFY_SCHEMA,
            context={"requirement": item.exact_text, "evidence": evidence},
        )
        model = result.model
        for k, v in result.usage.items():
            usage[k] = usage.get(k, 0) + v
        data = result.data
        bad = check_refs(data, cand_map)
        if not bad:
            break
    return data, bad, usage, model


async def handle_analyze_request(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    run = await session.get(AnalysisRun, uuid.UUID(payload["analysis_run_id"]))
    if run is None:
        return {"skipped": "run not found"}
    if run.status in ("SUCCEEDED", "NEEDS_REVIEW"):
        return {"skipped": "already completed"}
    request = await session.get(ClientRequest, run.request_id)
    project = await session.get(Project, run.project_id)
    baseline = await session.get(ScopeBaseline, run.baseline_id)
    assert request is not None and project is not None and baseline is not None
    # Re-check tenancy/binding before doing anything with the data (worker defence in depth).
    if not (request.project_id == project.id == baseline.project_id and project.workspace_id == run.workspace_id):
        raise Unprocessable("Analysis run is inconsistent with its project", code="TENANCY_MISMATCH")
    if baseline.status != "APPROVED":
        raise Conflict("Analysis requires an approved baseline", code="BASELINE_REQUIRED")

    llm = get_llm()
    run.status = "RUNNING"
    run.started_at = run.started_at or datetime.now(UTC)
    run.provider = llm.name
    run.model = llm.model
    run.error_code = None
    run.error_message = None
    await session.commit()

    usage: dict[str, int] = dict(run.token_usage or {})
    notes_run: list[str] = []

    items = await request_items(session, request.id)
    if not items:
        split_items, split_notes, result = await _split(llm, request.message_text)
        notes_run += split_notes
        for k, v in result.usage.items():
            usage[k] = usage.get(k, 0) + v
        for i, s in enumerate(split_items):
            session.add(
                RequestItem(
                    workspace_id=request.workspace_id,
                    request_id=request.id,
                    ordinal=i,
                    exact_text=s.exact_text,
                    start_offset=s.start,
                    end_offset=s.end,
                    summary=s.summary,
                )
            )
        run.token_usage = dict(usage)  # new object: JSONB columns do not track in-place mutation
        await session.commit()
        items = await request_items(session, request.id)

    done = set((await session.scalars(select(Finding.request_item_id).where(Finding.analysis_run_id == run.id))).all())
    pending = [i for i in items if i.id not in done]

    settings = get_settings()
    scope_cands = await baseline_candidates(session, baseline.id)
    doc_ids = await scope.baseline_document_ids(session, baseline.id)
    scope_span_ids = {c.span.id for c in scope_cands}
    per_item: list[tuple[RequestItem, list[Candidate]]] = []
    for item in pending:
        retrieved = await retrieve_text_matches(
            session, document_version_ids=doc_ids, requirement=item.exact_text, exclude_span_ids=scope_span_ids
        )
        # Fresh Candidate objects per item, because refs are assigned per prompt.
        cands = [Candidate(ref="", span=c.span, doc=c.doc, scope_items=list(c.scope_items)) for c in scope_cands]
        per_item.append((item, assemble_candidates(cands, retrieved, item.exact_text, settings.ai_max_input_chars)))

    sem = asyncio.Semaphore(max(1, settings.ai_concurrency))

    async def run_one(
        item: RequestItem, cands: list[Candidate]
    ) -> tuple[dict[str, Any], list[str], dict[str, int], str]:
        async with sem:
            return await _classify(llm, item=item, message=request.message_text, candidates=cands, project=project)

    results = await asyncio.gather(*(run_one(i, c) for i, c in per_item))

    any_review = False
    for (item, cands), (data, bad, item_usage, _model) in zip(per_item, results, strict=True):
        for k, v in item_usage.items():
            usage[k] = usage.get(k, 0) + v
        gated = gate(data, {c.ref: c for c in cands}, fabricated=bad or None)
        finding = Finding(
            workspace_id=run.workspace_id,
            analysis_run_id=run.id,
            request_item_id=item.id,
            category=gated.category,
            ai_category=gated.ai_category,
            summary=gated.summary or item.summary or item.exact_text,
            reason=gated.reason,
            uncertainties=gated.uncertainties,
            clarifying_questions=gated.clarifying_questions,
            policy_notes=gated.policy_notes,
            validation_errors=gated.validation_errors,
            model_confidence=gated.model_confidence,
            needs_review=gated.needs_review,
            review_status="PENDING" if gated.needs_review else "AUTO_ACCEPTED",
            final_category=None if gated.needs_review else gated.category,
        )
        session.add(finding)
        await session.flush()
        for polarity, cites in (("SUPPORTING", gated.supporting), ("COUNTER", gated.counter)):
            for cite in cites:
                exists = await session.get(FindingEvidence, (finding.id, cite.candidate.span.id, polarity))
                if exists:
                    continue
                session.add(
                    FindingEvidence(
                        finding_id=finding.id,
                        source_span_id=cite.candidate.span.id,
                        polarity=polarity,
                        quote=cite.quote,
                        scope_item_id=cite.candidate.scope_items[0][0] if cite.candidate.scope_items else None,
                    )
                )
        any_review = any_review or gated.needs_review

    # Previously persisted findings of this run (from an interrupted attempt) also count.
    if done:
        prior_review = await session.scalar(
            select(func.count())
            .select_from(Finding)
            .where(Finding.analysis_run_id == run.id, Finding.needs_review.is_(True))
        )
        any_review = any_review or bool(prior_review)

    run.status = "NEEDS_REVIEW" if any_review else "SUCCEEDED"
    await _queue_integration_followup(session, run, request)
    run.token_usage = dict(usage)
    run.finished_at = datetime.now(UTC)
    request.status = "NEEDS_REVIEW" if any_review else "REVIEWED"
    audit.record(
        session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        actor_type="WORKER",
        event_type="analysis.completed",
        object_type="analysis_run",
        object_id=run.id,
        metadata={
            "status": run.status,
            "items": len(items),
            "notes": notes_run,
            "model": run.model,
            "prompt_version": run.prompt_version,
            **usage,
        },
    )
    await session.commit()
    return {"status": run.status, "items": len(items)}


async def on_analysis_failed(
    session: AsyncSession, payload: dict[str, Any], code: str, message: str, final: bool
) -> None:
    run = await session.get(AnalysisRun, uuid.UUID(payload["analysis_run_id"]))
    if run is None:
        return
    run.error_code = code
    run.error_message = message[:1000]
    if final:
        run.status = "FAILED"
        run.finished_at = datetime.now(UTC)
        request = await session.get(ClientRequest, run.request_id)
        if request is not None:
            request.status = "FAILED"
            await _queue_integration_followup(session, run, request)
        audit.record(
            session,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            actor_type="WORKER",
            event_type="analysis.failed",
            object_type="analysis_run",
            object_id=run.id,
            metadata={"code": code},
        )
    else:
        run.status = "QUEUED"
    await session.commit()


async def _queue_integration_followup(session: AsyncSession, run: AnalysisRun, request: ClientRequest) -> None:
    """Connector-originated requests turn their findings (or a failure) into reviewable signals."""
    if request.source_batch_id is None:
        return
    await queue.enqueue(
        session,
        kind="telegram_build_signals",
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        payload={"analysis_run_id": str(run.id)},
        idempotency_key=f"tgsignals:{run.id}:{run.status}",
        max_attempts=5,
    )


async def retry_analysis(session: AsyncSession, *, run: AnalysisRun, user: User) -> AnalysisRun:
    if run.status != "FAILED":
        raise Conflict("Only failed analyses can be retried", code="NOT_RETRYABLE")
    baseline = await scope.current_approved(session, run.project_id)
    if baseline is None or baseline.id != run.baseline_id:
        raise Conflict("The approved baseline changed; start a new analysis instead", code="STALE_BASELINE")
    from app.db.models import Job

    job = await session.get(Job, run.job_id) if run.job_id else None
    if job is None:
        raise Conflict("Job record missing", code="NOT_RETRYABLE")
    await queue.requeue(session, job)
    run.status = "QUEUED"
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    request = await session.get(ClientRequest, run.request_id)
    if request is not None:
        request.status = "ANALYZING"
    audit.record(
        session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        actor_id=user.id,
        event_type="analysis.retried",
        object_type="analysis_run",
        object_id=run.id,
    )
    await session.commit()
    return run


async def review_finding(
    session: AsyncSession,
    *,
    finding: Finding,
    request: ClientRequest,
    user: User,
    decision: str,
    category: str | None,
    reason: str,
) -> Finding:
    if decision not in ("ACCEPT", "OVERRIDE", "REQUEST_CLARIFICATION"):
        raise Unprocessable("Unknown decision", code="INVALID_DECISION")
    reason = reason.strip()
    if decision == "OVERRIDE":
        if category not in CATEGORIES:
            raise Unprocessable("Choose the corrected category", code="CATEGORY_REQUIRED")
        if len(reason) < 5:
            raise Unprocessable("Explain why you override the AI category", code="REASON_REQUIRED")
        final = category
        status = "OVERRIDDEN"
    elif decision == "ACCEPT":
        if finding.category == "INSUFFICIENT_EVIDENCE" and finding.validation_errors:
            # Accepting a rejected AI output would launder fabricated evidence; force an explicit override.
            raise Unprocessable(
                "This finding failed evidence validation; override it with a reason instead",
                code="CANNOT_ACCEPT_INVALID",
            )
        final = finding.category
        status = "ACCEPTED"
    else:
        final = "AMBIGUOUS"
        status = "CLARIFICATION_REQUESTED"

    session.add(
        FindingReview(
            workspace_id=finding.workspace_id,
            finding_id=finding.id,
            actor_id=user.id,
            decision=decision,
            category=final,
            reason=reason,
        )
    )
    finding.review_status = status
    finding.final_category = final
    run = await session.get(AnalysisRun, finding.analysis_run_id)
    assert run is not None
    remaining = await session.scalar(
        select(func.count())
        .select_from(Finding)
        .where(Finding.analysis_run_id == run.id, Finding.review_status == "PENDING", Finding.id != finding.id)
    )
    if not remaining:
        request.status = "REVIEWED"
    audit.record(
        session,
        workspace_id=finding.workspace_id,
        project_id=request.project_id,
        actor_id=user.id,
        event_type="finding.reviewed",
        object_type="finding",
        object_id=finding.id,
        metadata={
            "decision": decision,
            "ai_category": finding.ai_category,
            "category": finding.category,
            "final_category": final,
        },
    )
    await session.commit()
    return finding


async def latest_run(session: AsyncSession, request_id: uuid.UUID) -> AnalysisRun | None:
    return await session.scalar(
        select(AnalysisRun).where(AnalysisRun.request_id == request_id).order_by(AnalysisRun.created_at.desc()).limit(1)
    )


async def get_finding_for_request(session: AsyncSession, request: ClientRequest, finding_id: uuid.UUID) -> Finding:
    finding = await session.get(Finding, finding_id)
    if finding is None:
        raise NotFound("Finding not found")
    run = await session.get(AnalysisRun, finding.analysis_run_id)
    if run is None or run.request_id != request.id:
        raise NotFound("Finding not found")
    return finding
