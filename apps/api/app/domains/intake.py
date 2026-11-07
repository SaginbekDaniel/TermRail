from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unprocessable
from app.db.models import ClientRequest, Project, RequestItem, User
from app.domains import audit

MAX_MESSAGE_CHARS = 20_000


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


async def create_request(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    message_text: str,
    sender: str,
    subject: str,
    idempotency_key: str | None,
) -> tuple[ClientRequest, bool, uuid.UUID | None]:
    """Returns (request, created, possible_duplicate_of).

    Dedup strategy (manual intake): the client sends an Idempotency-Key per form submission, so a
    double click or a network retry returns the original request. Re-submitting the same text later
    without a key is allowed (clients do repeat themselves) but is flagged as a possible duplicate.
    """
    if not message_text.strip():
        raise Unprocessable("The message is empty", code="EMPTY_MESSAGE")
    if len(message_text) > MAX_MESSAGE_CHARS:
        raise Unprocessable(f"Messages are limited to {MAX_MESSAGE_CHARS} characters", code="MESSAGE_TOO_LONG")
    if idempotency_key:
        existing = await session.scalar(
            select(ClientRequest).where(
                ClientRequest.project_id == project.id, ClientRequest.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing, False, None
    chash = content_hash(message_text)
    dup = await session.scalar(
        select(ClientRequest.id)
        .where(ClientRequest.project_id == project.id, ClientRequest.content_hash == chash)
        .order_by(ClientRequest.created_at)
        .limit(1)
    )
    request = ClientRequest(
        workspace_id=project.workspace_id,
        project_id=project.id,
        channel="MANUAL",
        idempotency_key=idempotency_key,
        content_hash=chash,
        sender=sender.strip()[:300],
        subject=subject.strip()[:300],
        message_text=message_text,
        status="NEW",
        created_by=user.id,
    )
    session.add(request)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(ClientRequest).where(
                ClientRequest.project_id == project.id, ClientRequest.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            raise
        return existing, False, None
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="request.received",
        object_type="request",
        object_id=request.id,
        metadata={"chars": len(message_text), "possible_duplicate_of": str(dup) if dup else None},
    )
    await session.commit()
    return request, True, dup


async def request_items(session: AsyncSession, request_id: uuid.UUID) -> list[RequestItem]:
    return list(
        (
            await session.scalars(
                select(RequestItem).where(RequestItem.request_id == request_id).order_by(RequestItem.ordinal)
            )
        ).all()
    )
