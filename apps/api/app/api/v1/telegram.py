"""Authenticated Telegram + commercial-signal endpoints. Workspace/project are always derived from our own
records and the caller's membership; foreign-tenant objects are reported as 404."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api import schemas as S
from app.api.deps import DB, MANAGE_ROLES, CurrentUser, IdempotencyKey, require_project, require_workspace
from app.api.serializers import findings_out
from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.models import CommercialSignal, Finding, Role, TelegramLinkIntent
from app.domains import scope
from app.integrations.telegram import bindings, linking, signals

router = APIRouter()


# ---------------------------------------------------------------- schemas
class LinkIntentOut(BaseModel):
    intent_id: uuid.UUID
    deep_link: str
    expires_at: datetime


class ConnectionOut(BaseModel):
    id: uuid.UUID
    status: str
    is_enabled: bool
    telegram_username: str | None
    rights: list[str]
    linked_at: datetime | None
    revoked_at: datetime | None
    last_event_at: datetime | None


class PendingLinkOut(BaseModel):
    id: uuid.UUID
    status: str
    expires_at: datetime
    verified: bool
    telegram_username: str | None


class TelegramStatusOut(BaseModel):
    configured: bool
    bot_username: str | None
    state: Literal["UNLINKED", "LINK_PENDING", "CONNECTED", "ACCESS_REVOKED", "LINK_CONFLICT"]
    connection: ConnectionOut | None
    pending_link: PendingLinkOut | None


class EligibleChatOut(BaseModel):
    chat_id: int
    display_name: str
    last_seen_at: datetime
    bound_project_id: uuid.UUID | None


class BindIn(BaseModel):
    chat_id: int


class MonitoringIn(BaseModel):
    enabled: bool
    privacy_acknowledged: bool = False
    expected_version: int | None = None


class BatchOut(BaseModel):
    id: uuid.UUID
    state: str
    outcome: str | None
    message_count: int
    last_message_at: datetime
    quiet_until: datetime
    processed_at: datetime | None


class BindingOut(BaseModel):
    status: Literal["UNBOUND", "AWAITING_CHAT", "NEEDS_BASELINE", "READY", "MONITORING", "PAUSED"]
    has_approved_baseline: bool
    binding_id: uuid.UUID | None = None
    chat_id: int | None = None
    display_name: str | None = None
    monitoring_enabled: bool = False
    version: int | None = None
    consent_at: datetime | None = None
    settings: dict[str, Any]
    last_batch: BatchOut | None = None


class SignalEvidenceOut(BaseModel):
    id: uuid.UUID
    message_id: int
    direction: str
    sent_at: datetime
    content_version: int
    state: str
    quote: str | None


class SignalOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    category: str
    summary: str
    status: str
    evidence_state: str
    severity: str
    notify: bool
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    request_id: uuid.UUID | None
    change_order_id: uuid.UUID | None
    baseline_id: uuid.UUID | None
    stale_baseline: bool
    resolution_reason: str | None
    resolved_category: str | None
    resolved_at: datetime | None
    version: int


class SignalDetailOut(SignalOut):
    evidence: list[SignalEvidenceOut]
    finding: S.FindingOut | None
    baseline_version: int | None


class ReasonIn(BaseModel):
    expected_version: int
    reason: str = Field(default="", max_length=2000)


class ResolveIn(ReasonIn):
    category: Literal["IN_SCOPE", "BUG_FIX"]


class VersionIn(BaseModel):
    expected_version: int


class ClarificationOut(BaseModel):
    signal: SignalOut
    suggested_questions: list[str]


class ConvertOut(BaseModel):
    request_id: uuid.UUID


class SignalChangeOrderIn(BaseModel):
    expected_version: int
    estimate_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    title: str = Field(default="", max_length=200)
    language: Literal["en", "ru"] = "en"


# ---------------------------------------------------------------- helpers
def _connection_out(c: Any) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        status=c.status,
        is_enabled=c.is_enabled,
        telegram_username=c.telegram_username,
        rights=sorted(k for k, v in (c.rights or {}).items() if v is True),
        linked_at=c.linked_at,
        revoked_at=c.revoked_at,
        last_event_at=c.last_event_at,
    )


async def _signal_out(db: DB, s: CommercialSignal, current_baseline: uuid.UUID | None) -> SignalOut:
    return SignalOut(
        id=s.id,
        project_id=s.project_id,
        category=s.category,
        summary=s.summary,
        status=s.status,
        evidence_state=s.evidence_state,
        severity=s.severity,
        notify=s.notify,
        occurrences=s.occurrences,
        first_seen_at=s.first_seen_at,
        last_seen_at=s.last_seen_at,
        request_id=s.request_id,
        change_order_id=s.change_order_id,
        baseline_id=s.baseline_id,
        stale_baseline=s.baseline_id is not None and s.baseline_id != current_baseline,
        resolution_reason=s.resolution_reason,
        resolved_category=s.resolved_category,
        resolved_at=s.resolved_at,
        version=s.version,
    )


async def _current_baseline_id(db: DB, project_id: uuid.UUID) -> uuid.UUID | None:
    b = await scope.current_approved(db, project_id)
    return b.id if b else None


async def _signal_for_user(
    db: DB, user: CurrentUser, signal_id: uuid.UUID, roles: frozenset[Role] | None = None
) -> CommercialSignal:
    s = await db.get(CommercialSignal, signal_id)
    if s is None:
        raise NotFound("Signal not found")
    try:
        await (require_project(db, user, s.project_id, roles) if roles else require_project(db, user, s.project_id))
    except NotFound as exc:
        raise NotFound("Signal not found") from exc
    return s


async def _detail(db: DB, s: CommercialSignal) -> SignalDetailOut:
    current = await _current_baseline_id(db, s.project_id)
    base = await _signal_out(db, s, current)
    finding = None
    if s.latest_finding_id:
        f = await db.get(Finding, s.latest_finding_id)
        if f is not None:
            finding = next((x for x in await findings_out(db, f.analysis_run_id) if x.id == f.id), None)
    baseline_version = None
    if s.baseline_id:
        from app.db.models import ScopeBaseline

        b = await db.get(ScopeBaseline, s.baseline_id)
        baseline_version = b.version if b else None
    ev = [SignalEvidenceOut(**e.__dict__) for e in await signals.evidence_views(db, s.id)]
    return SignalDetailOut(**base.model_dump(), evidence=ev, finding=finding, baseline_version=baseline_version)


# ---------------------------------------------------------------- workspace: connection
@router.get("/workspaces/{workspace_id}/integrations/telegram/status", response_model=TelegramStatusOut)
async def telegram_status(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> TelegramStatusOut:
    await require_workspace(db, user, workspace_id)
    s = get_settings()
    conn = await linking.workspace_connection(db, workspace_id)
    intent = await db.scalar(
        select(TelegramLinkIntent)
        .where(TelegramLinkIntent.workspace_id == workspace_id, TelegramLinkIntent.initiated_by == user.id)
        .order_by(TelegramLinkIntent.created_at.desc())
        .limit(1)
    )
    pending = None
    state: Any = "UNLINKED"
    if conn is not None:
        state = conn.status
    elif intent is not None and intent.status in ("PENDING", "VERIFIED", "CONFLICT"):
        from app.core.clock import utcnow

        live = intent.status != "PENDING" or intent.expires_at > utcnow()
        if live:
            state = "LINK_CONFLICT" if intent.status == "CONFLICT" else "LINK_PENDING"
            pending = PendingLinkOut(
                id=intent.id,
                status=intent.status,
                expires_at=intent.expires_at,
                verified=intent.status == "VERIFIED",
                telegram_username=intent.telegram_username,
            )
    return TelegramStatusOut(
        configured=s.telegram_enabled,
        bot_username=s.telegram_bot_username or None if s.telegram_enabled else None,
        state=state,
        connection=_connection_out(conn) if conn else None,
        pending_link=pending,
    )


@router.post(
    "/workspaces/{workspace_id}/integrations/telegram/link-intents", response_model=LinkIntentOut, status_code=201
)
async def create_link_intent(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> LinkIntentOut:
    await require_workspace(db, user, workspace_id, MANAGE_ROLES)
    intent, nonce = await linking.create_intent(db, workspace_id=workspace_id, user=user)
    return LinkIntentOut(intent_id=intent.id, deep_link=linking.deep_link(nonce), expires_at=intent.expires_at)


@router.post("/workspaces/{workspace_id}/integrations/telegram/disconnect", status_code=204)
async def disconnect(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    await require_workspace(db, user, workspace_id, MANAGE_ROLES)
    await linking.disconnect(db, workspace_id=workspace_id, user=user)
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/integrations/telegram/eligible-chats", response_model=list[EligibleChatOut])
async def eligible_chats(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> list[EligibleChatOut]:
    await require_workspace(db, user, workspace_id, MANAGE_ROLES)
    return [
        EligibleChatOut(
            chat_id=c.chat_id, display_name=c.display_name, last_seen_at=c.last_seen_at, bound_project_id=pid
        )
        for c, pid in await bindings.eligible_chats(db, workspace_id)
    ]


# ---------------------------------------------------------------- project: binding + monitoring
async def _binding_out(db: DB, project: Any) -> BindingOut:
    st = await bindings.state(db, project)
    b = st.binding
    lb = st.last_batch
    return BindingOut(
        status=st.status,  # type: ignore[arg-type]
        has_approved_baseline=st.has_baseline,
        binding_id=b.id if b else None,
        chat_id=b.chat_id if b else None,
        display_name=b.display_name if b else None,
        monitoring_enabled=bool(b and b.monitoring_enabled),
        version=b.version if b else None,
        consent_at=b.consent_at if b else None,
        settings=bindings.monitoring_settings(),
        last_batch=BatchOut(
            id=lb.id,
            state=lb.state,
            outcome=lb.outcome,
            message_count=lb.message_count,
            last_message_at=lb.last_message_at,
            quiet_until=lb.quiet_until,
            processed_at=lb.processed_at,
        )
        if lb
        else None,
    )


@router.get("/projects/{project_id}/telegram/chat-binding", response_model=BindingOut)
async def get_binding(project_id: uuid.UUID, user: CurrentUser, db: DB) -> BindingOut:
    project, _ = await require_project(db, user, project_id)
    return await _binding_out(db, project)


@router.post("/projects/{project_id}/telegram/chat-binding", response_model=BindingOut, status_code=201)
async def bind_chat(project_id: uuid.UUID, body: BindIn, user: CurrentUser, db: DB) -> BindingOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    await bindings.bind_chat(db, project=project, user=user, chat_id=body.chat_id)
    return await _binding_out(db, project)


@router.delete("/projects/{project_id}/telegram/chat-binding", status_code=204)
async def unbind_chat(project_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    await bindings.unbind(db, project=project, user=user)
    return Response(status_code=204)


@router.patch("/projects/{project_id}/telegram/monitoring", response_model=BindingOut)
async def set_monitoring(project_id: uuid.UUID, body: MonitoringIn, user: CurrentUser, db: DB) -> BindingOut:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    await bindings.set_monitoring(
        db,
        project=project,
        user=user,
        enabled=body.enabled,
        privacy_acknowledged=body.privacy_acknowledged,
        expected_version=body.expected_version,
    )
    return await _binding_out(db, project)


@router.delete("/projects/{project_id}/telegram/data", status_code=200)
async def purge_data(project_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, int]:
    project, _ = await require_project(db, user, project_id, MANAGE_ROLES)
    return {"messages_purged": await bindings.purge_project_data(db, project=project, user=user)}


# ---------------------------------------------------------------- signals
@router.get("/projects/{project_id}/commercial-signals", response_model=list[SignalOut])
async def list_signals(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    status: Literal["active", "all"] = Query(default="active"),
) -> list[SignalOut]:
    project, _ = await require_project(db, user, project_id)
    q = select(CommercialSignal).where(CommercialSignal.project_id == project.id)
    if status == "active":
        q = q.where(CommercialSignal.status.in_(signals.ACTIVE_STATUSES))
    rows = (await db.scalars(q.order_by(CommercialSignal.last_seen_at.desc()).limit(200))).all()
    current = await _current_baseline_id(db, project.id)
    return [await _signal_out(db, s, current) for s in rows]


@router.get("/commercial-signals/{signal_id}", response_model=SignalDetailOut)
async def get_signal(signal_id: uuid.UUID, user: CurrentUser, db: DB) -> SignalDetailOut:
    return await _detail(db, await _signal_for_user(db, user, signal_id))


@router.post("/commercial-signals/{signal_id}/dismiss", response_model=SignalDetailOut)
async def dismiss(signal_id: uuid.UUID, body: ReasonIn, user: CurrentUser, db: DB) -> SignalDetailOut:
    await _signal_for_user(db, user, signal_id, MANAGE_ROLES)
    s = await signals.dismiss(
        db, signal_id=signal_id, user=user, expected_version=body.expected_version, reason=body.reason
    )
    return await _detail(db, s)


@router.post("/commercial-signals/{signal_id}/resolve", response_model=SignalDetailOut)
async def resolve(signal_id: uuid.UUID, body: ResolveIn, user: CurrentUser, db: DB) -> SignalDetailOut:
    await _signal_for_user(db, user, signal_id, MANAGE_ROLES)
    s = await signals.resolve(
        db,
        signal_id=signal_id,
        user=user,
        expected_version=body.expected_version,
        category=body.category,
        reason=body.reason,
    )
    return await _detail(db, s)


@router.post("/commercial-signals/{signal_id}/request-clarification", response_model=ClarificationOut)
async def request_clarification(signal_id: uuid.UUID, body: VersionIn, user: CurrentUser, db: DB) -> ClarificationOut:
    await _signal_for_user(db, user, signal_id, MANAGE_ROLES)
    s, questions = await signals.request_clarification(
        db, signal_id=signal_id, user=user, expected_version=body.expected_version
    )
    return ClarificationOut(
        signal=await _signal_out(db, s, await _current_baseline_id(db, s.project_id)), suggested_questions=questions
    )


@router.post("/commercial-signals/{signal_id}/convert-to-request", response_model=ConvertOut)
async def convert_to_request(signal_id: uuid.UUID, user: CurrentUser, db: DB) -> ConvertOut:
    await _signal_for_user(db, user, signal_id, MANAGE_ROLES)
    req = await signals.convert_to_request(db, signal_id=signal_id, user=user)
    return ConvertOut(request_id=req.id)


@router.post("/commercial-signals/{signal_id}/create-change-order-draft", response_model=SignalDetailOut)
async def create_change_order_draft(
    signal_id: uuid.UUID, body: SignalChangeOrderIn, user: CurrentUser, db: DB, key: IdempotencyKey
) -> SignalDetailOut:
    await _signal_for_user(db, user, signal_id, MANAGE_ROLES)
    s = await signals.create_change_order_draft(
        db,
        signal_id=signal_id,
        user=user,
        expected_version=body.expected_version,
        estimate_ids=body.estimate_ids,
        title=body.title,
        language=body.language,
        idempotency_key=key,
    )
    return await _detail(db, s)

