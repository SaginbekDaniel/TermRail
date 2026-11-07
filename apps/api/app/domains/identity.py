from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound, TooManyRequests, Unauthorized, Unprocessable
from app.core.security import hash_password, verify_password
from app.db.models import Membership, Role, User, Workspace
from app.domains import audit

# Simple in-process login throttle (per email+ip). A shared store (e.g. Redis) is needed when
# running several API replicas; documented in README.
_attempts: dict[str, deque[float]] = defaultdict(deque)
_WINDOW = 60.0
_MAX_ATTEMPTS = 8


def _throttle(key: str) -> None:
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= _MAX_ATTEMPTS:
        raise TooManyRequests("Too many login attempts, try again in a minute")
    q.append(now)


def _require_local() -> None:
    if get_settings().auth_provider != "local":
        raise AppError(
            "Email/password login is disabled; use the configured identity provider",
            code="LOCAL_AUTH_DISABLED",
            status_code=400,
        )


async def register(session: AsyncSession, *, email: str, password: str, display_name: str) -> User:
    _require_local()
    email = email.strip().lower()
    if len(password) < 10:
        raise Unprocessable("Password must be at least 10 characters", code="WEAK_PASSWORD")
    exists = await session.scalar(select(func.count()).select_from(User).where(User.email == email))
    if exists:
        raise Conflict("An account with this email already exists", code="EMAIL_TAKEN")
    user = User(
        email=email,
        display_name=display_name.strip() or email.split("@")[0],
        password_hash=hash_password(password),
        auth_provider="local",
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("An account with this email already exists", code="EMAIL_TAKEN") from exc
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str, client_key: str) -> User:
    _require_local()
    email = email.strip().lower()
    _throttle(f"{email}|{client_key}")
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(user.password_hash, password):
        raise Unauthorized("Invalid email or password", code="INVALID_CREDENTIALS")
    return user


async def create_workspace(session: AsyncSession, *, user: User, name: str) -> Workspace:
    ws = Workspace(name=name.strip(), owner_id=user.id)
    session.add(ws)
    await session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER, status="ACTIVE"))
    audit.record(
        session,
        workspace_id=ws.id,
        actor_id=user.id,
        event_type="workspace.created",
        object_type="workspace",
        object_id=ws.id,
    )
    await session.commit()
    return ws


async def list_workspaces(session: AsyncSession, user: User) -> list[tuple[Workspace, str]]:
    rows = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id, Membership.status == "ACTIVE")
        .order_by(Workspace.created_at)
    )
    return [(w, r) for w, r in rows.all()]


async def list_members(session: AsyncSession, workspace_id: uuid.UUID) -> list[tuple[Membership, User]]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    )
    return [(m, u) for m, u in rows.all()]


async def add_member(
    session: AsyncSession, *, workspace_id: uuid.UUID, actor: User, email: str, role: Role
) -> Membership:
    """Add an EXISTING account to the workspace (email invitations are P1)."""
    if role == Role.OWNER:
        raise Unprocessable("Ownership transfer is not supported", code="ROLE_NOT_ASSIGNABLE")
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise NotFound("No account with this email. Ask them to sign up first.", code="USER_NOT_FOUND")
    existing = await session.scalar(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id)
    )
    if existing is not None:
        raise Conflict("This user is already a member", code="ALREADY_MEMBER")
    membership = Membership(workspace_id=workspace_id, user_id=user.id, role=role, status="ACTIVE")
    session.add(membership)
    audit.record(
        session,
        workspace_id=workspace_id,
        actor_id=actor.id,
        event_type="membership.added",
        object_type="membership",
        object_id=user.id,
        metadata={"role": str(role)},
    )
    await session.commit()
    return membership
