from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api import schemas as S
from app.api.deps import DB, MANAGE_ROLES, CurrentUser, IdempotencyKey, require_project, require_workspace
from app.api.serializers import change_order_out
from app.core.errors import NotFound
from app.db.models import ChangeOrder, ChangeOrderExport, ChangeOrderRevision, ClientRequest, Project, Role
from app.domains import change_orders as co_domain
from app.storage import get_storage

router = APIRouter()


async def _co_for_user(
    db: DB,
    user: CurrentUser,
    co_id: uuid.UUID,
    roles: frozenset[Role] | None = None,  # type: ignore[valid-type]
) -> ChangeOrder:
    co = await db.get(ChangeOrder, co_id)
    if co is None:
        raise NotFound("Change order not found")
    try:
        await (require_project(db, user, co.project_id, roles) if roles else require_project(db, user, co.project_id))
    except NotFound as exc:
        raise NotFound("Change order not found") from exc
    return co


@router.post("/change-orders", response_model=S.ChangeOrderOut, status_code=201)
async def create(
    body: S.ChangeOrderIn, user: CurrentUser, db: DB, key: IdempotencyKey, response: Response
) -> S.ChangeOrderOut:
    req = await db.get(ClientRequest, body.request_id)
    if req is None:
        raise NotFound("Request not found")
    try:
        project, _ = await require_project(db, user, req.project_id, MANAGE_ROLES)
    except NotFound as exc:
        raise NotFound("Request not found") from exc
    co, created = await co_domain.create_change_order(
        db,
        project=project,
        request=req,
        user=user,
        estimate_ids=body.estimate_ids,
        title=body.title,
        language=body.language,
        idempotency_key=key,
    )
    if not created:
        response.status_code = 200
    return await change_order_out(db, co)


@router.get("/change-orders", response_model=list[S.ChangeOrderListItemOut])
async def list_change_orders(
    workspace_id: uuid.UUID, user: CurrentUser, db: DB, project_id: uuid.UUID | None = None
) -> list[S.ChangeOrderListItemOut]:
    await require_workspace(db, user, workspace_id)
    q = (
        select(ChangeOrder, ChangeOrderRevision, Project.title)
        .join(ChangeOrderRevision, ChangeOrderRevision.id == ChangeOrder.current_revision_id)
        .join(Project, Project.id == ChangeOrder.project_id)
        .where(ChangeOrder.workspace_id == workspace_id)
    )
    if project_id:
        q = q.where(ChangeOrder.project_id == project_id)
    rows = await db.execute(q.order_by(ChangeOrder.updated_at.desc()).limit(200))
    return [
        S.ChangeOrderListItemOut(
            id=co.id,
            project_id=co.project_id,
            project_title=title,
            number=co.number,
            title=rev.content_json.get("title", ""),
            status=co.status,
            currency=rev.content_json["currency"],
            total=Decimal(rev.content_json["total"]),
            revision_no=rev.revision_no,
            updated_at=co.updated_at,
        )
        for co, rev, title in rows.all()
    ]


@router.get("/change-orders/{co_id}", response_model=S.ChangeOrderOut)
async def get(co_id: uuid.UUID, user: CurrentUser, db: DB) -> S.ChangeOrderOut:
    co = await _co_for_user(db, user, co_id)
    return await change_order_out(db, co)


@router.patch("/change-orders/{co_id}/draft", response_model=S.ChangeOrderOut)
async def patch_draft(co_id: uuid.UUID, body: S.ChangeOrderPatch, user: CurrentUser, db: DB) -> S.ChangeOrderOut:
    co = await _co_for_user(db, user, co_id, MANAGE_ROLES)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_revision_no"})
    co = await co_domain.edit_draft(
        db, co_id=co.id, user=user, expected_revision_no=body.expected_revision_no, changes=changes
    )
    return await change_order_out(db, co)


@router.post("/change-orders/{co_id}/submit", response_model=S.ChangeOrderOut)
async def submit(co_id: uuid.UUID, user: CurrentUser, db: DB) -> S.ChangeOrderOut:
    co = await _co_for_user(db, user, co_id, MANAGE_ROLES)
    return await change_order_out(db, await co_domain.submit(db, co_id=co.id, user=user))


@router.post("/change-orders/{co_id}/request-changes", response_model=S.ChangeOrderOut)
async def request_changes(co_id: uuid.UUID, body: S.CommentIn, user: CurrentUser, db: DB) -> S.ChangeOrderOut:
    co = await _co_for_user(db, user, co_id, MANAGE_ROLES)
    return await change_order_out(db, await co_domain.request_changes(db, co_id=co.id, user=user, comment=body.comment))


@router.post("/change-orders/{co_id}/approve", response_model=S.ChangeOrderOut)
async def approve(co_id: uuid.UUID, body: S.ApproveCOIn, user: CurrentUser, db: DB) -> S.ChangeOrderOut:
    co = await _co_for_user(db, user, co_id, MANAGE_ROLES)
    co = await co_domain.approve(
        db, co_id=co.id, user=user, revision_id=body.revision_id, content_hash_=body.content_hash, comment=body.comment
    )
    return await change_order_out(db, co)


@router.post("/change-orders/{co_id}/cancel", response_model=S.ChangeOrderOut)
async def cancel(co_id: uuid.UUID, user: CurrentUser, db: DB) -> S.ChangeOrderOut:
    co = await _co_for_user(db, user, co_id, MANAGE_ROLES)
    return await change_order_out(db, await co_domain.cancel(db, co_id=co.id, user=user))


@router.post("/change-orders/{co_id}/export", response_model=S.ExportOut, status_code=201)
async def export(co_id: uuid.UUID, body: S.ExportIn, user: CurrentUser, db: DB) -> S.ExportOut:
    co = await _co_for_user(db, user, co_id, MANAGE_ROLES)
    x = await co_domain.export_pdf(db, co_id=co.id, user=user, draft=body.draft)
    return S.ExportOut(
        id=x.id,
        revision_id=x.revision_id,
        content_hash=x.content_hash,
        pdf_sha256=x.pdf_sha256,
        is_draft=x.is_draft,
        created_at=x.created_at,
        download_path=f"/change-orders/{co.id}/exports/{x.id}/download",
    )


@router.get("/change-orders/{co_id}/exports/{export_id}/download")
async def download(co_id: uuid.UUID, export_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    co = await _co_for_user(db, user, co_id)
    x = await db.get(ChangeOrderExport, export_id)
    if x is None or x.change_order_id != co.id:
        raise NotFound("Export not found")
    data = await asyncio.to_thread(get_storage().get, x.storage_path)
    suffix = "-draft" if x.is_draft else ""
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="change-order-{co.number}{suffix}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Content-Hash": x.content_hash,
        },
    )
