from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.db.models import Project, User
from app.domains import audit


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user: User,
    title: str,
    client_name: str,
    currency: str,
    budget: Decimal | None,
    description: str,
    idempotency_key: str | None,
    is_demo: bool = False,
) -> tuple[Project, bool]:
    """Returns (project, created). A repeated submission with the same key returns the original."""
    if idempotency_key:
        existing = await session.scalar(
            select(Project).where(Project.workspace_id == workspace_id, Project.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing, False
    project = Project(
        workspace_id=workspace_id,
        title=title.strip(),
        client_name=client_name.strip(),
        currency=currency,
        budget=budget,
        description=description.strip(),
        idempotency_key=idempotency_key,
        is_demo=is_demo,
        created_by=user.id,
    )
    session.add(project)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Project).where(Project.workspace_id == workspace_id, Project.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing, False
    audit.record(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="project.created",
        object_type="project",
        object_id=project.id,
        object_version=1,
        metadata={"is_demo": is_demo},
    )
    await session.commit()
    return project, True


async def update_project(
    session: AsyncSession, *, project: Project, user: User, expected_version: int, changes: dict[str, object]
) -> Project:
    if project.version != expected_version:
        raise Conflict("The project was changed by someone else. Reload and try again.", code="STALE_VERSION")
    for key, value in changes.items():
        setattr(project, key, value.strip() if isinstance(value, str) else value)
    project.version += 1
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="project.updated",
        object_type="project",
        object_id=project.id,
        object_version=project.version,
        metadata={"fields": sorted(changes)},
    )
    await session.commit()
    return project


async def list_projects(session: AsyncSession, workspace_id: uuid.UUID) -> list[Project]:
    return list(
        (
            await session.scalars(
                select(Project).where(Project.workspace_id == workspace_id).order_by(Project.created_at.desc())
            )
        ).all()
    )
