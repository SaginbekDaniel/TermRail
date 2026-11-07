"""Scope baselines: AI candidate extraction, human editing, and immutable approval."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound, Unprocessable
from app.db.models import (
    Approval,
    BaselineDocument,
    DocumentVersion,
    Project,
    ScopeBaseline,
    ScopeEvidence,
    ScopeItem,
    SourceSpan,
    StoredFile,
    User,
)
from app.domains import audit
from app.jobs import queue
from app.llm.base import LLMInvalidOutput
from app.llm.factory import get_llm
from app.llm.prompts import EXTRACT_PROMPT_VERSION, EXTRACT_SCHEMA, EXTRACT_SYSTEM, render_extract_user

MAX_ITEMS = 200


# ------------------------------------------------------------------------------------------------
# Queries
# ------------------------------------------------------------------------------------------------


async def current_approved(session: AsyncSession, project_id: uuid.UUID) -> ScopeBaseline | None:
    return await session.scalar(
        select(ScopeBaseline)
        .where(ScopeBaseline.project_id == project_id, ScopeBaseline.status == "APPROVED")
        .order_by(ScopeBaseline.version.desc())
        .limit(1)
    )


async def get_draft(session: AsyncSession, project_id: uuid.UUID) -> ScopeBaseline | None:
    return await session.scalar(
        select(ScopeBaseline).where(ScopeBaseline.project_id == project_id, ScopeBaseline.status == "DRAFT")
    )


async def list_baselines(session: AsyncSession, project_id: uuid.UUID) -> list[ScopeBaseline]:
    return list(
        (
            await session.scalars(
                select(ScopeBaseline)
                .where(ScopeBaseline.project_id == project_id)
                .order_by(ScopeBaseline.version.desc())
            )
        ).all()
    )


@dataclass
class ItemView:
    item: ScopeItem
    spans: list[tuple[SourceSpan, DocumentVersion]]


async def baseline_items(session: AsyncSession, baseline_id: uuid.UUID) -> list[ItemView]:
    items = list(
        (
            await session.scalars(
                select(ScopeItem).where(ScopeItem.baseline_id == baseline_id).order_by(ScopeItem.ordinal)
            )
        ).all()
    )
    if not items:
        return []
    rows = await session.execute(
        select(ScopeEvidence.scope_item_id, SourceSpan, DocumentVersion)
        .join(SourceSpan, SourceSpan.id == ScopeEvidence.source_span_id)
        .join(DocumentVersion, DocumentVersion.id == SourceSpan.document_version_id)
        .where(ScopeEvidence.scope_item_id.in_([i.id for i in items]))
        .order_by(SourceSpan.ordinal)
    )
    by_item: dict[uuid.UUID, list[tuple[SourceSpan, DocumentVersion]]] = {}
    for item_id, span, doc in rows.all():
        by_item.setdefault(item_id, []).append((span, doc))
    return [ItemView(item=i, spans=by_item.get(i.id, [])) for i in items]


async def baseline_document_ids(session: AsyncSession, baseline_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await session.scalars(
                select(BaselineDocument.document_version_id).where(BaselineDocument.baseline_id == baseline_id)
            )
        ).all()
    )


# ------------------------------------------------------------------------------------------------
# Draft lifecycle
# ------------------------------------------------------------------------------------------------


async def get_or_create_draft(session: AsyncSession, *, project: Project, user: User) -> ScopeBaseline:
    draft = await get_draft(session, project.id)
    if draft is not None:
        return draft
    latest = await current_approved(session, project.id)
    max_version = await session.scalar(
        select(func.coalesce(func.max(ScopeBaseline.version), 0)).where(ScopeBaseline.project_id == project.id)
    )
    draft = ScopeBaseline(
        workspace_id=project.workspace_id,
        project_id=project.id,
        version=int(max_version or 0) + 1,
        status="DRAFT",
        draft_revision=1,
        based_on_baseline_id=latest.id if latest else None,
        created_by=user.id,
    )
    session.add(draft)
    await session.flush()
    if latest is not None:
        # A new version starts as an editable copy of the approved one; the approved one stays untouched.
        for doc_id in await baseline_document_ids(session, latest.id):
            session.add(BaselineDocument(baseline_id=draft.id, document_version_id=doc_id))
        for view in await baseline_items(session, latest.id):
            new_item = ScopeItem(
                workspace_id=project.workspace_id,
                baseline_id=draft.id,
                ordinal=view.item.ordinal,
                title=view.item.title,
                description=view.item.description,
                inclusion_type=view.item.inclusion_type,
                acceptance_criteria=view.item.acceptance_criteria,
                origin=view.item.origin,
                accepted=True,
            )
            session.add(new_item)
            await session.flush()
            for span, _doc in view.spans:
                session.add(ScopeEvidence(scope_item_id=new_item.id, source_span_id=span.id))
    await session.flush()
    return draft


async def _project_spans(
    session: AsyncSession, project_id: uuid.UUID, span_ids: set[uuid.UUID]
) -> dict[uuid.UUID, SourceSpan]:
    if not span_ids:
        return {}
    rows = await session.execute(
        select(SourceSpan, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == SourceSpan.document_version_id)
        .where(SourceSpan.id.in_(span_ids))
    )
    found: dict[uuid.UUID, SourceSpan] = {}
    for span, doc in rows.all():
        if doc.project_id == project_id:
            found[span.id] = span
    return found


async def start_extraction(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    document_version_ids: list[uuid.UUID] | None,
    request_key: str,
) -> tuple[ScopeBaseline, Any]:
    draft = await get_or_create_draft(session, project=project, user=user)
    docs_q = select(DocumentVersion).where(DocumentVersion.project_id == project.id)
    if document_version_ids:
        docs_q = docs_q.where(DocumentVersion.id.in_(document_version_ids))
    docs = list((await session.scalars(docs_q)).all())
    if document_version_ids and len(docs) != len(set(document_version_ids)):
        raise NotFound("Document not found")
    parsed = [d for d in docs if d.parse_status == "PARSED"]
    if not parsed:
        raise Unprocessable(
            "Upload a contract and wait until it is parsed. Documents that need OCR/review cannot be used.",
            code="NO_PARSED_DOCUMENTS",
        )
    job = await queue.enqueue(
        session,
        kind="extract_scope",
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"baseline_id": str(draft.id), "document_version_ids": [str(d.id) for d in parsed]},
        idempotency_key=f"extract:{draft.id}:{request_key}",
        created_by=user.id,
        max_attempts=3,
    )
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="scope.extraction_started",
        object_type="scope_baseline",
        object_id=draft.id,
        object_version=draft.version,
        metadata={"job_id": str(job.id), "documents": len(parsed)},
    )
    await session.commit()
    return draft, job


def _batches(spans: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = [[]]
    size = 0
    for s in spans:
        if size + len(s["text"]) > max_chars and batches[-1]:
            batches.append([])
            size = 0
        batches[-1].append(s)
        size += len(s["text"])
    return batches


async def handle_extract_scope(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """Worker handler: ask the LLM for scope candidates, keep only those citing real spans."""
    baseline = await session.get(ScopeBaseline, uuid.UUID(payload["baseline_id"]))
    if baseline is None or baseline.status != "DRAFT":
        return {"skipped": "baseline is no longer a draft"}
    doc_ids = [uuid.UUID(d) for d in payload["document_version_ids"]]
    docs = {
        d.id: d
        for d in (await session.scalars(select(DocumentVersion).where(DocumentVersion.id.in_(doc_ids)))).all()
        if d.project_id == baseline.project_id and d.parse_status == "PARSED"
    }
    spans = list(
        (
            await session.scalars(
                select(SourceSpan)
                .where(SourceSpan.document_version_id.in_(list(docs)))
                .order_by(SourceSpan.document_version_id, SourceSpan.ordinal)
            )
        ).all()
    )
    ref_map: dict[str, SourceSpan] = {}
    prompt_spans = []
    for i, s in enumerate(spans, start=1):
        ref = f"S{i}"
        ref_map[ref] = s
        prompt_spans.append({"ref": ref, "text": s.normalized_text, "heading": s.heading})

    llm = get_llm()
    settings = get_settings()
    candidates: list[dict[str, Any]] = []
    rejected = 0
    usage_total = 0
    for batch in _batches(prompt_spans, settings.ai_max_input_chars):
        user_prompt = render_extract_user(batch, [d.title for d in docs.values()])
        result = await get_llm_result(llm, user_prompt, batch)
        usage_total += int(result.usage.get("total_tokens", 0))
        raw_items = result.data.get("items")
        if not isinstance(raw_items, list):
            raise LLMInvalidOutput("extraction output has no items list")
        for raw in raw_items[:MAX_ITEMS]:
            refs = [r for r in (raw.get("source_refs") or []) if isinstance(r, str)]
            valid = [ref_map[r] for r in refs if r in ref_map]
            kind = raw.get("inclusion_type")
            title = str(raw.get("title") or "").strip()[:300]
            if not valid or len(valid) != len(refs) or kind not in ("INCLUDED", "EXCLUDED", "CONDITION") or not title:
                rejected += 1  # fabricated/missing citations or malformed item: never stored
                continue
            candidates.append(
                {
                    "title": title,
                    "description": str(raw.get("description") or "").strip(),
                    "inclusion_type": kind,
                    "acceptance_criteria": str(raw.get("acceptance_criteria") or "").strip(),
                    "spans": valid,
                }
            )

    existing = await baseline_items(session, baseline.id)
    existing_keys = {
        (v.item.title.lower(), v.item.inclusion_type, frozenset(s.id for s, _ in v.spans)) for v in existing
    }
    ordinal = max((v.item.ordinal for v in existing), default=-1) + 1
    added = 0
    for c in candidates:
        key = (c["title"].lower(), c["inclusion_type"], frozenset(s.id for s in c["spans"]))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        item = ScopeItem(
            workspace_id=baseline.workspace_id,
            baseline_id=baseline.id,
            ordinal=ordinal,
            title=c["title"],
            description=c["description"],
            inclusion_type=c["inclusion_type"],
            acceptance_criteria=c["acceptance_criteria"],
            origin="AI_CANDIDATE",
            accepted=False,
        )
        ordinal += 1
        session.add(item)
        await session.flush()
        for span in {s.id: s for s in c["spans"]}.values():
            session.add(ScopeEvidence(scope_item_id=item.id, source_span_id=span.id))
        added += 1
    for doc_id in docs:
        exists = await session.get(BaselineDocument, (baseline.id, doc_id))
        if exists is None:
            session.add(BaselineDocument(baseline_id=baseline.id, document_version_id=doc_id))
    baseline.draft_revision += 1
    audit.record(
        session,
        workspace_id=baseline.workspace_id,
        project_id=baseline.project_id,
        actor_type="WORKER",
        event_type="scope.candidates_extracted",
        object_type="scope_baseline",
        object_id=baseline.id,
        object_version=baseline.version,
        metadata={
            "added": added,
            "rejected": rejected,
            "provider": llm.name,
            "model": llm.model,
            "prompt_version": EXTRACT_PROMPT_VERSION,
            "total_tokens": usage_total,
        },
    )
    await session.commit()
    return {"added": added, "rejected": rejected}


async def get_llm_result(llm: Any, user_prompt: str, batch: list[dict[str, Any]]) -> Any:
    return await llm.generate_json(
        task="extract_scope", system=EXTRACT_SYSTEM, user=user_prompt, schema=EXTRACT_SCHEMA, context={"spans": batch}
    )


async def replace_draft(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    expected_revision: int,
    items: list[dict[str, Any]],
) -> ScopeBaseline:
    """Full replacement of the draft's items (PUT semantics) guarded by draft_revision."""
    draft = await get_or_create_draft(session, project=project, user=user)
    if draft.draft_revision != expected_revision:
        raise Conflict(
            "The scope draft changed since you loaded it. Reload and re-apply your edits.",
            code="STALE_DRAFT",
            details={"current_revision": draft.draft_revision},
        )
    if len(items) > MAX_ITEMS:
        raise Unprocessable(f"At most {MAX_ITEMS} scope items", code="TOO_MANY_ITEMS")

    all_span_ids = {sid for it in items for sid in it["source_span_ids"]}
    spans = await _project_spans(session, project.id, all_span_ids)
    missing = all_span_ids - set(spans)
    if missing:
        raise Unprocessable(
            "Some cited source fragments do not exist in this project",
            code="INVALID_SOURCE_SPAN",
            details={"span_ids": sorted(str(m) for m in missing)},
        )

    existing = {
        i.id: i for i in (await session.scalars(select(ScopeItem).where(ScopeItem.baseline_id == draft.id))).all()
    }
    keep_ids = {it["id"] for it in items if it.get("id")}
    unknown = keep_ids - set(existing)
    if unknown:
        raise Unprocessable("Unknown scope item id", code="INVALID_SCOPE_ITEM")

    for item_id, item in existing.items():
        if item_id not in keep_ids:
            await session.delete(item)
    await session.flush()

    for ordinal, it in enumerate(items):
        if it.get("id"):
            item = existing[it["id"]]
            changed = (
                item.title != it["title"]
                or item.description != it["description"]
                or item.inclusion_type != it["inclusion_type"]
                or item.acceptance_criteria != it["acceptance_criteria"]
            )
            item.ordinal = ordinal
            item.title = it["title"]
            item.description = it["description"]
            item.inclusion_type = it["inclusion_type"]
            item.acceptance_criteria = it["acceptance_criteria"]
            # Editing an item counts as reviewing it.
            item.accepted = bool(it.get("accepted", item.accepted)) or changed
            await session.execute(delete(ScopeEvidence).where(ScopeEvidence.scope_item_id == item.id))
        else:
            item = ScopeItem(
                workspace_id=project.workspace_id,
                baseline_id=draft.id,
                ordinal=ordinal,
                title=it["title"],
                description=it["description"],
                inclusion_type=it["inclusion_type"],
                acceptance_criteria=it["acceptance_criteria"],
                origin="MANUAL",
                accepted=True,
            )
            session.add(item)
        await session.flush()
        for sid in dict.fromkeys(it["source_span_ids"]):
            session.add(ScopeEvidence(scope_item_id=item.id, source_span_id=sid))

    doc_ids = {spans[sid].document_version_id for sid in all_span_ids}
    current_docs = set(await baseline_document_ids(session, draft.id))
    for doc_id in doc_ids - current_docs:
        session.add(BaselineDocument(baseline_id=draft.id, document_version_id=doc_id))
    draft.draft_revision += 1
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="scope.draft_updated",
        object_type="scope_baseline",
        object_id=draft.id,
        object_version=draft.draft_revision,
        metadata={"items": len(items)},
    )
    await session.commit()
    return draft


def compute_baseline_hash(
    *, project_id: uuid.UUID, version: int, documents: list[tuple[uuid.UUID, str]], views: list[ItemView]
) -> str:
    canonical = {
        "project_id": str(project_id),
        "version": version,
        "documents": sorted([{"id": str(d), "sha256": h} for d, h in documents], key=lambda x: x["id"]),
        "items": [
            {
                "ordinal": v.item.ordinal,
                "title": v.item.title,
                "description": v.item.description,
                "inclusion_type": v.item.inclusion_type,
                "acceptance_criteria": v.item.acceptance_criteria,
                "evidence": sorted(str(s.id) for s, _ in v.spans),
            }
            for v in views
        ],
    }
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def approve_draft(
    session: AsyncSession, *, project: Project, user: User, expected_revision: int, note: str
) -> ScopeBaseline:
    # Lock the draft row so two concurrent approvals cannot both succeed.
    draft = await session.scalar(
        select(ScopeBaseline)
        .where(ScopeBaseline.project_id == project.id, ScopeBaseline.status == "DRAFT")
        .with_for_update()
    )
    if draft is None:
        raise Conflict("There is no scope draft to approve", code="NO_DRAFT")
    if draft.draft_revision != expected_revision:
        raise Conflict(
            "The scope draft changed since you reviewed it. Reload before approving.",
            code="STALE_DRAFT",
            details={"current_revision": draft.draft_revision},
        )
    views = await baseline_items(session, draft.id)
    if not views:
        raise Unprocessable("A baseline needs at least one scope item", code="EMPTY_BASELINE")
    unsupported = [v.item.title for v in views if not v.spans]
    if unsupported:
        raise Unprocessable(
            "Every scope item must cite at least one source fragment",
            code="UNSUPPORTED_SCOPE_ITEM",
            details={"items": unsupported},
        )
    unreviewed = [v.item.title for v in views if not v.item.accepted]
    if unreviewed:
        raise Unprocessable(
            "Review (accept or edit) every AI candidate before approving",
            code="UNREVIEWED_CANDIDATES",
            details={"items": unreviewed},
        )
    doc_ids = {doc.id for v in views for _, doc in v.spans}
    bad_docs = [doc.title for v in views for _, doc in v.spans if doc.parse_status != "PARSED"]
    if bad_docs:
        raise Unprocessable(
            "Cited documents must be fully parsed", code="UNPARSED_SOURCE", details={"documents": sorted(set(bad_docs))}
        )
    rows = await session.execute(
        select(DocumentVersion.id, StoredFile.sha256)
        .join(StoredFile, StoredFile.id == DocumentVersion.file_id)
        .where(DocumentVersion.id.in_(doc_ids))
    )
    documents = [(r[0], r[1]) for r in rows.all()]
    baseline_hash = compute_baseline_hash(
        project_id=project.id, version=draft.version, documents=documents, views=views
    )

    draft.status = "APPROVED"
    draft.baseline_hash = baseline_hash
    draft.approved_by = user.id
    draft.approved_at = datetime.now(UTC)
    draft.approval_note = note.strip() or None
    session.add(
        Approval(
            workspace_id=project.workspace_id,
            target_type="SCOPE_BASELINE",
            target_id=draft.id,
            content_hash=baseline_hash,
            actor_id=user.id,
            decision="APPROVED",
            comment=note.strip(),
        )
    )
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="scope.baseline_approved",
        object_type="scope_baseline",
        object_id=draft.id,
        object_version=draft.version,
        metadata={"baseline_hash": baseline_hash, "items": len(views)},
    )
    try:
        await session.commit()
    except Exception as exc:  # pragma: no cover - surfaced as a conflict
        await session.rollback()
        raise AppError("Approval failed, please retry", code="APPROVAL_FAILED", status_code=409) from exc
    return draft
