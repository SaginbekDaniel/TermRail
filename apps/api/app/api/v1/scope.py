from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api import schemas as S
from app.api.deps import DB, MANAGE_ROLES, CurrentUser, IdempotencyKey, require_project
from app.api.serializers import baseline_out, job_out
from app.db.models import Job
from app.domains import scope

router = APIRouter()


async def _state(db: DB, project_id: uuid.UUID) -> S.ScopeStateOut:  # type: ignore[valid-type]
    current = await scope.current_approved(db, project_id)
    draft = await scope.get_draft(db, project_id)
    history = [
        {
            "id": str(b.id),
            "version": b.version,
            "status": b.status,
            "baseline_hash": b.baseline_hash,
            "approved_at": b.approved_at.isoformat() if b.approved_at else None,
        }
        for b in await scope.list_baselines(db, project_id)
    ]
    job = None
    if draft is not None:
        job = await db.scalar(
            select(Job)
            .where(
                Job.kind == "extract_scope",
                Job.project_id == project_id,
                Job.payload["baseline_id"].astext == str(draft.id),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
    return S.ScopeStateOut(
        current=await baseline_out(db, current) if current else None,
        draft=await baseline_out(db, draft) if draft else None,
        history=history,
        extraction_job=job_out(job),
    )


@router.get("/projects/{project_id}/scope", response_model=S.ScopeStateOut)
async def scope_state(project_id: uuid.UUID, user: CurrentUser, db: DB) -> S.ScopeStateOut:
    project, _ = await require_project(db, user, project_id)
    return await _state(db, project.id)


@router.post("/projects/{project_id}/scope/draft", response_model=S.BaselineOut, status_code=201)
async def create_draft(project_id: uuid.UUID, user: CurrentUser, db: DB) -> S.BaselineOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    draft = await scope.get_or_create_draft(db, project=project, user=user)
    await db.commit()
    return await baseline_out(db, draft)


@router.post("/projects/{project_id}/scope/extract", response_model=S.ExtractOut, status_code=202)
async def extract(
    project_id: uuid.UUID, body: S.ExtractIn, user: CurrentUser, db: DB, key: IdempotencyKey
) -> S.ExtractOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    draft, job = await scope.start_extraction(
        db,
        project=project,
        user=user,
        document_version_ids=body.document_version_ids,
        request_key=key or uuid.uuid4().hex,
    )
    out = job_out(job)
    assert out is not None
    return S.ExtractOut(baseline_id=draft.id, job=out)


@router.get("/projects/{project_id}/scope/candidates", response_model=S.BaselineOut | None)
async def candidates(project_id: uuid.UUID, user: CurrentUser, db: DB) -> S.BaselineOut | None:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    draft = await scope.get_draft(db, project.id)
    return await baseline_out(db, draft) if draft else None


@router.put("/projects/{project_id}/scope/draft", response_model=S.BaselineOut)
async def put_draft(project_id: uuid.UUID, body: S.DraftIn, user: CurrentUser, db: DB) -> S.BaselineOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    draft = await scope.replace_draft(
        db,
        project=project,
        user=user,
        expected_revision=body.expected_revision,
        items=[i.model_dump() for i in body.items],
    )
    return await baseline_out(db, draft)


@router.post("/projects/{project_id}/scope/approve", response_model=S.BaselineOut)
async def approve(project_id: uuid.UUID, body: S.ApproveBaselineIn, user: CurrentUser, db: DB) -> S.BaselineOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    baseline = await scope.approve_draft(
        db, project=project, user=user, expected_revision=body.expected_revision, note=body.note
    )
    return await baseline_out(db, baseline)


@router.get("/projects/{project_id}/scope/baselines", response_model=list[S.BaselineOut])
async def baselines(project_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.BaselineOut]:
    project, _ = await require_project(db, user, project_id)
    return [await baseline_out(db, b) for b in await scope.list_baselines(db, project.id)]
