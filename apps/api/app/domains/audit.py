"""Append-only audit trail. Metadata must never contain document text, prompts or secrets."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_request_id
from app.db.models import AuditEvent


def record(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    event_type: str,
    object_type: str,
    object_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "USER",
    object_version: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_type=actor_type if actor_id or actor_type != "USER" else "SYSTEM",
        actor_id=actor_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        object_version=object_version,
        event_metadata=metadata or {},
        request_id=get_request_id(),
    )
    session.add(event)
    return event


async def list_events(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
    if project_id is not None:
        stmt = stmt.where(AuditEvent.project_id == project_id)
    stmt = stmt.order_by(AuditEvent.occurred_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())
