from __future__ import annotations

import asyncio
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.api import schemas as S
from app.api.deps import DB, MANAGE_ROLES, CurrentUser, require_project
from app.api.serializers import document_out
from app.core.config import get_settings
from app.core.errors import NotFound, PayloadTooLarge
from app.db.models import DocumentVersion, StoredFile
from app.domains import documents
from app.storage import get_storage

router = APIRouter()


async def _version_for_user(db: DB, user: CurrentUser, version_id: uuid.UUID) -> DocumentVersion:  # type: ignore[valid-type]
    version = await db.get(DocumentVersion, version_id)
    if version is None:
        raise NotFound("Document not found")
    try:
        await require_project(db, user, version.project_id)
    except NotFound as exc:
        raise NotFound("Document not found") from exc
    return version


@router.post("/projects/{project_id}/documents", response_model=S.UploadOut, status_code=201)
async def upload(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
) -> S.UploadOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLarge(f"File exceeds the {limit // (1024 * 1024)} MB limit")
    version, created = await documents.upload_document(
        db, project=project, user=user, filename=file.filename or "document", data=data, title=title
    )
    if not created:
        response.status_code = 200
    rows = [r for r in await documents.list_versions(db, project.id) if r[0].id == version.id]
    v, f, n = rows[0]
    return S.UploadOut(document=document_out(v, f, n), duplicate=not created)


@router.get("/projects/{project_id}/documents", response_model=list[S.DocumentOut])
async def list_documents(project_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.DocumentOut]:
    project, _ = await require_project(db, user, project_id)
    return [document_out(v, f, n) for v, f, n in await documents.list_versions(db, project.id)]


@router.get("/documents/{version_id}", response_model=S.DocumentOut)
async def get_document(version_id: uuid.UUID, user: CurrentUser, db: DB) -> S.DocumentOut:
    version = await _version_for_user(db, user, version_id)
    rows = [r for r in await documents.list_versions(db, version.project_id) if r[0].id == version.id]
    v, f, n = rows[0]
    return document_out(v, f, n)


@router.get("/documents/{version_id}/spans", response_model=list[S.SpanOut])
async def spans(version_id: uuid.UUID, user: CurrentUser, db: DB) -> list[S.SpanOut]:
    version = await _version_for_user(db, user, version_id)
    return [S.SpanOut.model_validate(s) for s in await documents.list_spans(db, version.id)]


@router.get("/documents/{version_id}/file")
async def download(version_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    """Streams the private original after the membership check (no public URLs exist)."""
    version = await _version_for_user(db, user, version_id)
    stored = await db.get(StoredFile, version.file_id)
    assert stored is not None
    data = await asyncio.to_thread(get_storage().get, stored.storage_path)
    return Response(
        content=data,
        media_type=stored.mime,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(stored.original_name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
