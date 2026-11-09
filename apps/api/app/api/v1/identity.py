from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.api import schemas as S
from app.api.deps import DB, MANAGE_ROLES, OWNER_ROLES, CurrentUser, require_workspace
from app.api.serializers import audit_out
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.models import (
    AnalysisRun,
    ChangeOrder,
    ChangeOrderRevision,
    ClientRequest,
    Estimate,
    Finding,
    Project,
    RequestItem,
    Role,
)
from app.domains import audit, identity

router = APIRouter()


@router.post("/auth/register", response_model=S.TokenOut, status_code=201)
async def register(body: S.RegisterIn, db: DB) -> S.TokenOut:
    user = await identity.register(db, email=body.email, password=body.password, display_name=body.display_name)
    token, exp = create_access_token(user.id)
    return S.TokenOut(access_token=token, expires_at=exp)


@router.post("/auth/login", response_model=S.TokenOut)
async def login(body: S.LoginIn, db: DB, request: Request) -> S.TokenOut:
    client = request.client.host if request.client else "unknown"
    user = await identity.authenticate(db, email=body.email, password=body.password, client_key=client)
    token, exp = create_access_token(user.id)
    return S.TokenOut(access_token=token, expires_at=exp)


@router.get("/me", response_model=S.MeOut)
async def me(user: CurrentUser, db: DB) -> S.MeOut:
    rows = await identity.list_workspaces(db, user)
    return S.MeOut(
        user=S.UserOut.model_validate(user),
        workspaces=[S.WorkspaceOut(id=w.id, name=w.name, role=r, created_at=w.created_at) for w, r in rows],  # type: ignore[arg-type]
        auth_provider=get_settings().auth_provider,
    )


@router.post("/workspaces", response_model=S.WorkspaceOut, status_code=201)
async def create_workspace(body: S.WorkspaceIn, user: CurrentUser, db: DB) -> S.WorkspaceOut:
    ws = await identity.create_workspace(db, user=user, name=body.name)
    return S.WorkspaceOut(id=ws.id, name=ws.name, role="OWNER", created_at=ws.created_at)


@router.get("/workspaces/{workspace_id}", response_model=S.WorkspaceOut)
async def get_workspace(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> S.WorkspaceOut:
    access = await require_workspace(db, user, workspace_id)
    from app.db.models import Workspace

    ws = await db.get(Workspace, workspace_id)
    assert ws is not None
    return S.WorkspaceOut(id=ws.id, name=ws.name, role=access.role.value, created_at=ws.created_at)  # type: ignore[arg-type]


@router.get("/workspaces/{workspace_id}/members", response_model=list[S.MemberOut])
async def list_members(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.MemberOut]:
    await require_workspace(db, user, workspace_id)
    return [
        S.MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=m.role, status=m.status)  # type: ignore[arg-type]
        for m, u in await identity.list_members(db, workspace_id)
    ]


@router.post("/workspaces/{workspace_id}/members", response_model=S.MemberOut, status_code=201)
async def add_member(workspace_id: uuid.UUID, body: S.MemberIn, user: CurrentUser, db: DB) -> S.MemberOut:
    await require_workspace(db, user, workspace_id, OWNER_ROLES)
    m = await identity.add_member(db, workspace_id=workspace_id, actor=user, email=body.email, role=Role(body.role))
    from app.db.models import User

    u = await db.get(User, m.user_id)
    assert u is not None
    return S.MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=m.role, status=m.status)  # type: ignore[arg-type]


@router.get("/workspaces/{workspace_id}/overview", response_model=S.OverviewOut)
async def overview(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> S.OverviewOut:
    """All numbers come from stored records; nothing is estimated or simulated."""
    await require_workspace(db, user, workspace_id)
    active = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.workspace_id == workspace_id, Project.status == "ACTIVE")
    )
    needs_review = await db.scalar(
        select(func.count())
        .select_from(Finding)
        .where(Finding.workspace_id == workspace_id, Finding.review_status == "PENDING")
    )
    requests_total = await db.scalar(
        select(func.count()).select_from(ClientRequest).where(ClientRequest.workspace_id == workspace_id)
    )
    # Potential = latest APPROVED estimate per requirement (not revenue).
    latest = (
        select(Estimate.request_item_id, func.max(Estimate.version).label("v"))
        .where(Estimate.workspace_id == workspace_id, Estimate.status == "APPROVED")
        .group_by(Estimate.request_item_id)
        .subquery()
    )
    pot_rows = await db.execute(
        select(Estimate.currency, func.sum(Estimate.subtotal))
        .join(latest, (latest.c.request_item_id == Estimate.request_item_id) & (latest.c.v == Estimate.version))
        .group_by(Estimate.currency)
    )
    potential = [S.MoneyByCurrency(currency=c, amount=a or Decimal("0")) for c, a in pot_rows.all()]

    cos = list((await db.scalars(select(ChangeOrder).where(ChangeOrder.workspace_id == workspace_id))).all())
    by_status: dict[str, int] = {}
    approved: dict[str, Decimal] = {}
    for co in cos:
        by_status[co.status] = by_status.get(co.status, 0) + 1
        if co.status in ("APPROVED_INTERNAL", "EXPORTED") and co.approved_revision_id:
            rev = await db.get(ChangeOrderRevision, co.approved_revision_id)
            if rev is not None:
                cur = rev.content_json["currency"]
                approved[cur] = approved.get(cur, Decimal("0")) + Decimal(rev.content_json["total"])
    events = await audit.list_events(db, workspace_id=workspace_id, limit=12)
    return S.OverviewOut(
        active_projects=int(active or 0),
        needs_review=int(needs_review or 0),
        requests_total=int(requests_total or 0),
        potential_change_value=potential,
        approved_change_value=[S.MoneyByCurrency(currency=c, amount=a) for c, a in approved.items()],
        change_orders_by_status=by_status,
        recent_activity=await audit_out(db, events),
    )


@router.get("/workspaces/{workspace_id}/inbox", response_model=list[S.InboxItemOut])
async def inbox(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.InboxItemOut]:
    await require_workspace(db, user, workspace_id)
    rows = await db.execute(
        select(Finding, RequestItem, ClientRequest, Project)
        .join(RequestItem, RequestItem.id == Finding.request_item_id)
        .join(AnalysisRun, AnalysisRun.id == Finding.analysis_run_id)
        .join(ClientRequest, ClientRequest.id == AnalysisRun.request_id)
        .join(Project, Project.id == ClientRequest.project_id)
        .where(Finding.workspace_id == workspace_id, Finding.review_status == "PENDING")
        .order_by(ClientRequest.received_at.desc(), RequestItem.ordinal)
        .limit(200)
    )
    return [
        S.InboxItemOut(
            finding_id=f.id,
            request_item_id=i.id,
            request_id=r.id,
            project_id=p.id,
            project_title=p.title,
            requirement=i.exact_text,
            category=cast(S.Category, f.category),
            summary=f.summary,
            received_at=r.received_at,
            created_at=f.created_at,  # type: ignore[arg-type]
        )
        for f, i, r, p in rows.all()
    ]


@router.get("/workspaces/{workspace_id}/audit", response_model=list[S.AuditOut])
async def workspace_audit(workspace_id: uuid.UUID, user: CurrentUser, db: DB, limit: int = 100) -> list[S.AuditOut]:
    await require_workspace(db, user, workspace_id, MANAGE_ROLES)
    events = await audit.list_events(db, workspace_id=workspace_id, limit=min(max(limit, 1), 500))
    return await audit_out(db, events)
