"""Request dependencies: DB session, authenticated user, and tenant/role access checks.

Every object is loaded through a helper here that verifies workspace membership. Resources
in workspaces the caller does not belong to are reported as 404 so their existence is not leaked.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import verify_access_token
from app.db.models import Membership, Project, Role, User
from app.db.session import get_sessionmaker

READ_ROLES = frozenset({Role.OWNER, Role.MANAGER, Role.MEMBER, Role.VIEWER})
CONTRIBUTE_ROLES = frozenset({Role.OWNER, Role.MANAGER, Role.MEMBER})
MANAGE_ROLES = frozenset({Role.OWNER, Role.MANAGER})
OWNER_ROLES = frozenset({Role.OWNER})


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token", code="UNAUTHORIZED")
    identity = verify_access_token(authorization.split(" ", 1)[1].strip())
    if identity.provider == "local":
        try:
            user_id = uuid.UUID(identity.subject)
        except ValueError as exc:
            raise Unauthorized("Invalid access token", code="INVALID_TOKEN") from exc
        user = await db.get(User, user_id)
    else:
        user = await db.scalar(select(User).where(User.external_subject == identity.subject))
        if user is None and identity.email:
            # First request with a valid Supabase session: provision the local user record.
            user = User(
                email=identity.email.lower(),
                display_name=identity.email.split("@")[0],
                auth_provider="supabase",
                external_subject=identity.subject,
            )
            db.add(user)
            await db.commit()
    if user is None:
        raise Unauthorized("Unknown user", code="INVALID_TOKEN")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class Access:
    user: User
    membership: Membership

    @property
    def role(self) -> Role:
        return Role(self.membership.role)

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.membership.workspace_id


async def require_workspace(
    db: AsyncSession, user: User, workspace_id: uuid.UUID, roles: frozenset[Role] = READ_ROLES
) -> Access:
    membership = await db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user.id,
            Membership.status == "ACTIVE",
        )
    )
    if membership is None:
        raise NotFound("Workspace not found")
    if Role(membership.role) not in roles:
        raise Forbidden("Your role does not allow this action", code="ROLE_FORBIDDEN")
    return Access(user=user, membership=membership)


async def require_project(
    db: AsyncSession, user: User, project_id: uuid.UUID, roles: frozenset[Role] = READ_ROLES
) -> tuple[Project, Access]:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFound("Project not found")
    try:
        access = await require_workspace(db, user, project.workspace_id, roles)
    except NotFound as exc:
        raise NotFound("Project not found") from exc
    return project, access


def idempotency_key_header(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    if idempotency_key is None:
        return None
    key = idempotency_key.strip()
    if not key or len(key) > 100:
        return None
    return key


IdempotencyKey = Annotated[str | None, Depends(idempotency_key_header)]
