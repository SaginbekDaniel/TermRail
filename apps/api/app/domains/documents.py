from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import PurePath

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, PayloadTooLarge
from app.db.models import DocumentVersion, Project, SourceSpan, StoredFile, User
from app.domains import audit
from app.jobs import queue
from app.parsing.parser import DOCX_MIME, PARSER_VERSION, ParseError, parse_document, sniff_mime
from app.storage import document_key, get_storage

PARSE_TIMEOUT_SECONDS = 90


async def upload_document(
    session: AsyncSession, *, project: Project, user: User, filename: str, data: bytes, title: str | None
) -> tuple[DocumentVersion, bool]:
    """Store the original privately, create an immutable document version and queue parsing.

    Returns (version, created). Uploading identical bytes again returns the existing version.
    """
    settings = get_settings()
    if len(data) == 0:
        raise AppError("The file is empty", code="EMPTY_FILE", status_code=422)
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLarge(f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit")
    try:
        mime = sniff_mime(data, filename)
    except ParseError as exc:
        raise AppError(exc.message, code=exc.code, status_code=415) from exc

    sha = hashlib.sha256(data).hexdigest()
    existing_file = await session.scalar(
        select(StoredFile).where(StoredFile.project_id == project.id, StoredFile.sha256 == sha)
    )
    if existing_file is not None:
        version = await session.scalar(select(DocumentVersion).where(DocumentVersion.file_id == existing_file.id))
        assert version is not None
        return version, False

    ext = ".docx" if mime == DOCX_MIME else ".pdf"
    key = document_key(project.workspace_id, project.id, sha, ext)
    await asyncio.to_thread(get_storage().put, key, data)

    safe_name = PurePath(filename or f"document{ext}").name[:300]
    stored = StoredFile(
        workspace_id=project.workspace_id,
        project_id=project.id,
        storage_path=key,
        sha256=sha,
        mime=mime,
        bytes=len(data),
        original_name=safe_name,
        uploaded_by=user.id,
    )
    session.add(stored)
    await session.flush()
    next_version = (
        await session.scalar(
            select(func.coalesce(func.max(DocumentVersion.version), 0)).where(DocumentVersion.project_id == project.id)
        )
    ) + 1
    version = DocumentVersion(
        workspace_id=project.workspace_id,
        project_id=project.id,
        file_id=stored.id,
        version=next_version,
        title=(title or safe_name).strip()[:300],
        parse_status="PENDING",
        created_by=user.id,
        quality={},
    )
    session.add(version)
    await session.flush()
    await queue.enqueue(
        session,
        kind="parse_document",
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"document_version_id": str(version.id)},
        idempotency_key=f"parse:{version.id}",
        created_by=user.id,
    )
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="document.uploaded",
        object_type="document_version",
        object_id=version.id,
        object_version=version.version,
        metadata={"sha256": sha, "mime": mime, "bytes": len(data)},
    )
    await session.commit()
    return version, True


async def handle_parse_document(session: AsyncSession, payload: dict[str, str]) -> None:
    """Worker handler. Idempotent: an already-parsed version is left untouched."""
    version = await session.get(DocumentVersion, uuid.UUID(payload["document_version_id"]))
    if version is None:
        return
    if version.parse_status in ("PARSED", "NEEDS_OCR_OR_REVIEW"):
        return
    stored = await session.get(StoredFile, version.file_id)
    assert stored is not None
    version.parse_status = "PARSING"
    await session.commit()

    data = await asyncio.to_thread(get_storage().get, stored.storage_path)
    settings = get_settings()
    try:
        parsed = await asyncio.wait_for(
            asyncio.to_thread(parse_document, data, stored.mime, max_pages=settings.max_document_pages),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except ParseError as exc:
        version.parse_status = "FAILED"
        version.parse_error = exc.code
        version.parser_version = PARSER_VERSION
        audit.record(
            session,
            workspace_id=version.workspace_id,
            project_id=version.project_id,
            actor_type="WORKER",
            event_type="document.parse_failed",
            object_type="document_version",
            object_id=version.id,
            metadata={"code": exc.code},
        )
        await session.commit()
        return
    except TimeoutError:
        version.parse_status = "FAILED"
        version.parse_error = "PARSE_TIMEOUT"
        await session.commit()
        return

    # Re-runs after a crash mid-insert: start from a clean slate for this version.
    existing = await session.scalar(
        select(func.count()).select_from(SourceSpan).where(SourceSpan.document_version_id == version.id)
    )
    if existing:
        from sqlalchemy import delete

        await session.execute(delete(SourceSpan).where(SourceSpan.document_version_id == version.id))

    for i, s in enumerate(parsed.spans):
        session.add(
            SourceSpan(
                workspace_id=version.workspace_id,
                document_version_id=version.id,
                ordinal=i,
                anchor_type=s.anchor_type,
                page=s.page,
                paragraph_index=s.paragraph_index,
                table_ref=s.table_ref,
                char_start=s.char_start,
                char_end=s.char_end,
                exact_quote=s.exact_quote,
                normalized_text=s.normalized_text,
                heading=s.heading,
            )
        )
    version.parse_status = parsed.status
    version.parser_version = PARSER_VERSION
    version.page_count = parsed.page_count
    version.text_chars = parsed.text_chars
    version.quality = parsed.quality
    version.parse_error = None
    audit.record(
        session,
        workspace_id=version.workspace_id,
        project_id=version.project_id,
        actor_type="WORKER",
        event_type="document.parsed",
        object_type="document_version",
        object_id=version.id,
        object_version=version.version,
        metadata={"status": parsed.status, "spans": len(parsed.spans), "issues": parsed.quality.get("issues")},
    )
    await session.commit()


async def list_versions(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[DocumentVersion, StoredFile, int]]:
    span_count = (
        select(func.count(SourceSpan.id))
        .where(SourceSpan.document_version_id == DocumentVersion.id)
        .correlate(DocumentVersion)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(DocumentVersion, StoredFile, span_count)
        .join(StoredFile, StoredFile.id == DocumentVersion.file_id)
        .where(DocumentVersion.project_id == project_id)
        .order_by(DocumentVersion.version.desc())
    )
    return [(v, f, int(c or 0)) for v, f, c in rows.all()]


async def list_spans(session: AsyncSession, version_id: uuid.UUID) -> list[SourceSpan]:
    return list(
        (
            await session.scalars(
                select(SourceSpan).where(SourceSpan.document_version_id == version_id).order_by(SourceSpan.ordinal)
            )
        ).all()
    )
