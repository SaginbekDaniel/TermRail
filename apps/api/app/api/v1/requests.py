from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api import schemas as S
from app.api.deps import (
    CONTRIBUTE_ROLES,
    DB,
    MANAGE_ROLES,
    CurrentUser,
    IdempotencyKey,
    require_project,
    require_workspace,
)
from app.api.serializers import estimate_out, request_list, request_out, run_out
from app.core.errors import NotFound
from app.db.models import AnalysisRun, ClientRequest, Estimate, Project, Role
from app.domains import analysis, intake
from app.domains import estimates as est_domain

router = APIRouter()


async def _request_for_user(
    db: DB,
    user: CurrentUser,
    request_id: uuid.UUID,
    roles: frozenset[Role] | None = None,  # type: ignore[valid-type]
) -> tuple[ClientRequest, Project]:
    req = await db.get(ClientRequest, request_id)
    if req is None:
        raise NotFound("Request not found")
    try:
        project, _ = (
            await require_project(db, user, req.project_id, roles)
            if roles
            else await require_project(db, user, req.project_id)
        )
    except NotFound as exc:
        raise NotFound("Request not found") from exc
    return req, project


@router.post("/projects/{project_id}/requests", response_model=S.RequestOut, status_code=201)
async def create_request(
    project_id: uuid.UUID, body: S.RequestIn, user: CurrentUser, db: DB, key: IdempotencyKey, response: Response
) -> S.RequestOut:
    project, _ = await require_project(db, user, project_id, CONTRIBUTE_ROLES)
    req, created, dup = await intake.create_request(
        db,
        project=project,
        user=user,
        message_text=body.message_text,
        sender=body.sender,
        subject=body.subject,
        idempotency_key=key,
    )
    if not created:
        response.status_code = 200
    return await request_out(db, req, project, possible_duplicate_of=dup)


@router.get("/projects/{project_id}/requests", response_model=list[S.RequestListItemOut])
async def list_project_requests(project_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.RequestListItemOut]:
    project, _ = await require_project(db, user, project_id)
    return await request_list(db, workspace_id=project.workspace_id, project_id=project.id)


@router.get("/workspaces/{workspace_id}/requests", response_model=list[S.RequestListItemOut])
async def list_workspace_requests(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.RequestListItemOut]:
    await require_workspace(db, user, workspace_id)
    return await request_list(db, workspace_id=workspace_id, project_id=None)


@router.get("/requests/{request_id}", response_model=S.RequestOut)
async def get_request(request_id: uuid.UUID, user: CurrentUser, db: DB) -> S.RequestOut:
    req, project = await _request_for_user(db, user, request_id)
    return await request_out(db, req, project)


@router.post("/requests/{request_id}/analyze", response_model=S.AnalyzeOut, status_code=202)
async def analyze(
    request_id: uuid.UUID, body: S.AnalyzeIn, user: CurrentUser, db: DB, key: IdempotencyKey, response: Response
) -> S.AnalyzeOut:
    req, project = await _request_for_user(db, user, request_id, CONTRIBUTE_ROLES)
    run, created = await analysis.start_analysis(
        db, project=project, request=req, user=user, baseline_id=body.baseline_id, idempotency_key=key
    )
    if not created:
        response.status_code = 200
    return S.AnalyzeOut(analysis_run_id=run.id, job_id=run.job_id, status=run.status, created=created)


async def _run_for_user(
    db: DB,
    user: CurrentUser,
    run_id: uuid.UUID,
    roles: frozenset[Role] | None = None,  # type: ignore[valid-type]
) -> AnalysisRun:
    run = await db.get(AnalysisRun, run_id)
    if run is None:
        raise NotFound("Analysis not found")
    try:
        await (require_project(db, user, run.project_id, roles) if roles else require_project(db, user, run.project_id))
    except NotFound as exc:
        raise NotFound("Analysis not found") from exc
    return run


@router.get("/analysis-runs/{run_id}", response_model=S.AnalysisRunOut)
async def get_run(run_id: uuid.UUID, user: CurrentUser, db: DB) -> S.AnalysisRunOut:
    run = await _run_for_user(db, user, run_id)
    return await run_out(db, run)


@router.post("/analysis-runs/{run_id}/retry", response_model=S.AnalysisRunOut)
async def retry_run(run_id: uuid.UUID, user: CurrentUser, db: DB) -> S.AnalysisRunOut:
    run = await _run_for_user(db, user, run_id, CONTRIBUTE_ROLES)
    run = await analysis.retry_analysis(db, run=run, user=user)
    return await run_out(db, run)


@router.post("/requests/{request_id}/findings/{finding_id}/review", response_model=S.FindingOut)
async def review(
    request_id: uuid.UUID, finding_id: uuid.UUID, body: S.ReviewIn, user: CurrentUser, db: DB
) -> S.FindingOut:
    req, _ = await _request_for_user(db, user, request_id, MANAGE_ROLES)
    finding = await analysis.get_finding_for_request(db, req, finding_id)
    finding = await analysis.review_finding(
        db, finding=finding, request=req, user=user, decision=body.decision, category=body.category, reason=body.reason
    )
    run = await db.get(AnalysisRun, finding.analysis_run_id)
    assert run is not None
    out = await run_out(db, run)
    return next(f for f in out.findings if f.id == finding.id)


@router.get("/requests/{request_id}/estimates", response_model=list[S.EstimateOut])
async def list_estimates(request_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.EstimateOut]:
    req, _ = await _request_for_user(db, user, request_id)
    return [await estimate_out(db, e) for e in await est_domain.list_estimates(db, req.id)]


@router.post("/requests/{request_id}/estimates", response_model=S.EstimateOut, status_code=201)
async def create_estimate(request_id: uuid.UUID, body: S.EstimateIn, user: CurrentUser, db: DB) -> S.EstimateOut:
    req, project = await _request_for_user(db, user, request_id, MANAGE_ROLES)
    e = await est_domain.create_estimate(
        db,
        project=project,
        request=req,
        user=user,
        request_item_id=body.request_item_id,
        lines=[ln.model_dump() for ln in body.lines],
        timeline_days=body.timeline_days,
        notes=body.notes,
    )
    return await estimate_out(db, e)


@router.post("/estimates/{estimate_id}/approve", response_model=S.EstimateOut)
async def approve_estimate(estimate_id: uuid.UUID, user: CurrentUser, db: DB) -> S.EstimateOut:
    e = await db.get(Estimate, estimate_id)
    if e is None:
        raise NotFound("Estimate not found")
    try:
        await require_project(db, user, e.project_id, MANAGE_ROLES)
    except NotFound as exc:
        raise NotFound("Estimate not found") from exc
    e = await est_domain.approve_estimate(db, estimate=e, user=user)
    return await estimate_out(db, e)
