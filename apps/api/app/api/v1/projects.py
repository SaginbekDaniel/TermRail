from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.api import schemas as S
from app.api.deps import DB, MANAGE_ROLES, CurrentUser, IdempotencyKey, require_project, require_workspace
from app.api.serializers import audit_out
from app.db.models import AnalysisRun, ClientRequest, DocumentVersion, Finding, Project, ScopeBaseline
from app.domains import audit, projects
from app.domains import estimates as est_domain
from app.integrations.telegram import signals as tg_signals

router = APIRouter()


async def _summary(db: DB, p: Project) -> S.ProjectSummaryOut:  # type: ignore[valid-type]
    docs = await db.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.project_id == p.id))
    baseline_version = await db.scalar(
        select(func.max(ScopeBaseline.version)).where(
            ScopeBaseline.project_id == p.id, ScopeBaseline.status == "APPROVED"
        )
    )
    has_draft = await db.scalar(
        select(func.count())
        .select_from(ScopeBaseline)
        .where(ScopeBaseline.project_id == p.id, ScopeBaseline.status == "DRAFT")
    )
    open_reviews = await db.scalar(
        select(func.count())
        .select_from(Finding)
        .join(AnalysisRun, AnalysisRun.id == Finding.analysis_run_id)
        .where(AnalysisRun.project_id == p.id, Finding.review_status == "PENDING")
    )
    reqs = await db.scalar(select(func.count()).select_from(ClientRequest).where(ClientRequest.project_id == p.id))
    open_signals = (await tg_signals.open_counts(db, [p.id])).get(p.id, 0)
    return S.ProjectSummaryOut(
        **S.ProjectOut.model_validate(p).model_dump(),
        documents=int(docs or 0),
        baseline_version=baseline_version,
        has_draft=bool(has_draft),
        open_reviews=int(open_reviews or 0),
        requests=int(reqs or 0),
        open_signals=open_signals,
    )


@router.post("/projects", response_model=S.ProjectOut, status_code=201)
async def create_project(
    body: S.ProjectIn, user: CurrentUser, db: DB, key: IdempotencyKey, response: Response
) -> Project:
    await require_workspace(db, user, body.workspace_id, MANAGE_ROLES)
    project, created = await projects.create_project(
        db,
        workspace_id=body.workspace_id,
        user=user,
        title=body.title,
        client_name=body.client_name,
        currency=body.currency,
        budget=body.budget,
        description=body.description,
        idempotency_key=key,
    )
    if not created:
        response.status_code = 200
    return project


@router.get("/projects", response_model=list[S.ProjectSummaryOut])
async def list_projects(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.ProjectSummaryOut]:
    await require_workspace(db, user, workspace_id)
    return [await _summary(db, p) for p in await projects.list_projects(db, workspace_id)]


@router.get("/projects/{project_id}", response_model=S.ProjectSummaryOut)
async def get_project(project_id: uuid.UUID, user: CurrentUser, db: DB) -> S.ProjectSummaryOut:
    project, _ = await require_project(db, user, project_id)
    return await _summary(db, project)


@router.patch("/projects/{project_id}", response_model=S.ProjectOut)
async def patch_project(project_id: uuid.UUID, body: S.ProjectPatch, user: CurrentUser, db: DB) -> Project:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    return await projects.update_project(
        db, project=project, user=user, expected_version=body.expected_version, changes=changes
    )


@router.get("/projects/{project_id}/rates", response_model=S.RatesOut)
async def get_rates(project_id: uuid.UUID, user: CurrentUser, db: DB) -> S.RatesOut:
    project, _ = await require_project(db, user, project_id)
    revision, rates = await est_domain.current_rates(db, project.id)
    return S.RatesOut(revision=revision, currency=project.currency, rates=[S.RateOut.model_validate(r) for r in rates])


@router.put("/projects/{project_id}/rates", response_model=S.RatesOut)
async def put_rates(project_id: uuid.UUID, body: S.RatesIn, user: CurrentUser, db: DB) -> S.RatesOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    revision, rates = await est_domain.replace_rates(
        db,
        project=project,
        user=user,
        expected_revision=body.expected_revision,
        rates=[r.model_dump() for r in body.rates],
    )
    return S.RatesOut(revision=revision, currency=project.currency, rates=[S.RateOut.model_validate(r) for r in rates])


@router.get("/projects/{project_id}/audit", response_model=list[S.AuditOut])
async def project_audit(project_id: uuid.UUID, user: CurrentUser, db: DB, limit: int = 100) -> list[S.AuditOut]:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    events = await audit.list_events(
        db, workspace_id=project.workspace_id, project_id=project.id, limit=min(max(limit, 1), 500)
    )
    return await audit_out(db, events)
