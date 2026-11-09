"""Rate cards and estimates: amounts are computed here from approved rates and human-entered hours."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, Unprocessable
from app.db.models import (
    AnalysisRun,
    Approval,
    ClientRequest,
    Estimate,
    EstimateLine,
    Finding,
    Project,
    RateCard,
    RequestItem,
    User,
)
from app.domains import audit
from app.domains.money import line_amount, to_decimal, total, validate_rate


async def current_rates(session: AsyncSession, project_id: uuid.UUID) -> tuple[int, list[RateCard]]:
    revision = await session.scalar(select(func.max(RateCard.revision)).where(RateCard.project_id == project_id))
    if revision is None:
        return 0, []
    rows = await session.scalars(
        select(RateCard).where(RateCard.project_id == project_id, RateCard.revision == revision).order_by(RateCard.role)
    )
    return int(revision), list(rows.all())


async def replace_rates(
    session: AsyncSession, *, project: Project, user: User, expected_revision: int, rates: list[dict[str, Any]]
) -> tuple[int, list[RateCard]]:
    revision, _ = await current_rates(session, project.id)
    if revision != expected_revision:
        raise Conflict(
            "Rates changed since you loaded them. Reload and try again.",
            code="STALE_RATES",
            details={"current_revision": revision},
        )
    roles = [r["role"].strip() for r in rates]
    if any(not r for r in roles):
        raise Unprocessable("Every rate needs a role name", code="ROLE_REQUIRED")
    if len({r.casefold() for r in roles}) != len(roles):
        raise Unprocessable("Role names must be unique", code="DUPLICATE_ROLE")
    new_revision = revision + 1
    rows = []
    for r in rates:
        currency = r.get("currency") or project.currency
        if currency != project.currency:
            raise Unprocessable(f"Rates must be in the project currency ({project.currency})", code="CURRENCY_MISMATCH")
        rate = validate_rate(to_decimal(r["hourly_rate"], "hourly_rate"))
        row = RateCard(
            workspace_id=project.workspace_id,
            project_id=project.id,
            revision=new_revision,
            role=r["role"].strip()[:100],
            currency=currency,
            hourly_rate=rate,
            created_by=user.id,
        )
        session.add(row)
        rows.append(row)
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="rates.updated",
        object_type="rate_card",
        object_id=project.id,
        object_version=new_revision,
        metadata={"roles": len(rows)},
    )
    await session.commit()
    return new_revision, rows


async def effective_finding(session: AsyncSession, request: ClientRequest, item: RequestItem) -> Finding | None:
    """The reviewed finding of the latest analysis run for this requirement."""
    return await session.scalar(
        select(Finding)
        .join(AnalysisRun, AnalysisRun.id == Finding.analysis_run_id)
        .where(AnalysisRun.request_id == request.id, Finding.request_item_id == item.id)
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )


async def create_estimate(
    session: AsyncSession,
    *,
    project: Project,
    request: ClientRequest,
    user: User,
    request_item_id: uuid.UUID,
    lines: list[dict[str, Any]],
    timeline_days: int | None,
    notes: str,
) -> Estimate:
    item = await session.get(RequestItem, request_item_id)
    if item is None or item.request_id != request.id:
        raise NotFound("Requirement not found")
    finding = await effective_finding(session, request, item)
    if finding is None:
        raise Conflict("Analyse the request before estimating", code="ANALYSIS_REQUIRED")
    if finding.review_status in ("PENDING",):
        raise Conflict("Review the AI finding before estimating", code="REVIEW_REQUIRED")
    if finding.final_category != "CHANGE_CANDIDATE":
        raise Conflict(
            "Only requirements confirmed as potential changes can be priced. "
            "Ambiguous requests need clarification, not a price.",
            code="ESTIMATE_NOT_ALLOWED",
            details={"final_category": finding.final_category},
        )
    if not lines:
        raise Unprocessable("Add at least one estimate line", code="ESTIMATE_INCOMPLETE")
    if timeline_days is not None and (timeline_days < 0 or timeline_days > 3650):
        raise Unprocessable("Timeline must be between 0 and 3650 days", code="INVALID_TIMELINE")

    rate_revision, rates = await current_rates(session, project.id)
    rate_by_role = {r.role.casefold(): r for r in rates}
    computed: list[EstimateLine] = []
    for i, raw in enumerate(lines):
        kind = raw.get("kind")
        if kind == "HOURLY":
            role = str(raw.get("role") or "").strip()
            rate = rate_by_role.get(role.casefold())
            if rate is None:
                raise Unprocessable(
                    f"No approved rate for role '{role}'. Set project rates first.",
                    code="RATE_REQUIRED",
                    details={"role": role},
                )
            hours = to_decimal(raw.get("hours"), "hours") if raw.get("hours") is not None else None
            amount = line_amount("HOURLY", hours=hours, rate=rate.hourly_rate, fixed=None)
            computed.append(
                EstimateLine(
                    ordinal=i,
                    kind="HOURLY",
                    description=str(raw.get("description") or "")[:500],
                    role=rate.role,
                    hours=hours,
                    rate_snapshot=rate.hourly_rate,
                    amount=amount,
                )
            )
        elif kind == "FIXED":
            fixed = to_decimal(raw.get("amount"), "amount") if raw.get("amount") is not None else None
            amount = line_amount("FIXED", hours=None, rate=None, fixed=fixed)
            computed.append(
                EstimateLine(
                    ordinal=i, kind="FIXED", description=str(raw.get("description") or "")[:500], amount=amount
                )
            )
        else:
            raise Unprocessable("Unknown line kind", code="INVALID_LINE_KIND")

    version = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(Estimate.version), 0)).where(Estimate.request_item_id == item.id)
            )
            or 0
        )
        + 1
    )
    estimate = Estimate(
        workspace_id=project.workspace_id,
        project_id=project.id,
        request_id=request.id,
        request_item_id=item.id,
        finding_id=finding.id,
        version=version,
        status="DRAFT",
        currency=project.currency,
        rate_card_revision=rate_revision,
        subtotal=total([line.amount for line in computed]),
        timeline_days=timeline_days,
        notes=notes.strip()[:2000],
        created_by=user.id,
    )
    session.add(estimate)
    await session.flush()
    for line in computed:
        line.estimate_id = estimate.id
        session.add(line)
    audit.record(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        event_type="estimate.created",
        object_type="estimate",
        object_id=estimate.id,
        object_version=version,
        metadata={"subtotal": str(estimate.subtotal), "currency": estimate.currency},
    )
    await session.commit()
    return estimate


async def estimate_lines(session: AsyncSession, estimate_id: uuid.UUID) -> list[EstimateLine]:
    return list(
        (
            await session.scalars(
                select(EstimateLine).where(EstimateLine.estimate_id == estimate_id).order_by(EstimateLine.ordinal)
            )
        ).all()
    )


def estimate_hash(estimate: Estimate, lines: list[EstimateLine]) -> str:
    canonical = {
        "id": str(estimate.id),
        "version": estimate.version,
        "currency": estimate.currency,
        "subtotal": str(estimate.subtotal),
        "timeline_days": estimate.timeline_days,
        "lines": [
            {
                "kind": ln.kind,
                "role": ln.role,
                "hours": str(ln.hours) if ln.hours is not None else None,
                "rate": str(ln.rate_snapshot) if ln.rate_snapshot is not None else None,
                "amount": str(ln.amount),
            }
            for ln in lines
        ],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


async def approve_estimate(session: AsyncSession, *, estimate: Estimate, user: User) -> Estimate:
    locked = await session.scalar(select(Estimate).where(Estimate.id == estimate.id).with_for_update())
    assert locked is not None
    if locked.status == "APPROVED":
        raise Conflict("Estimate already approved", code="ALREADY_APPROVED")
    lines = await estimate_lines(session, locked.id)
    locked.status = "APPROVED"
    locked.approved_by = user.id
    locked.approved_at = datetime.now(UTC)
    session.add(
        Approval(
            workspace_id=locked.workspace_id,
            target_type="ESTIMATE",
            target_id=locked.id,
            content_hash=estimate_hash(locked, lines),
            actor_id=user.id,
            decision="APPROVED",
        )
    )
    audit.record(
        session,
        workspace_id=locked.workspace_id,
        project_id=locked.project_id,
        actor_id=user.id,
        event_type="estimate.approved",
        object_type="estimate",
        object_id=locked.id,
        object_version=locked.version,
        metadata={"subtotal": str(locked.subtotal)},
    )
    await session.commit()
    return locked


async def list_estimates(session: AsyncSession, request_id: uuid.UUID) -> list[Estimate]:
    return list(
        (
            await session.scalars(
                select(Estimate)
                .where(Estimate.request_id == request_id)
                .order_by(Estimate.request_item_id, Estimate.version)
            )
        ).all()
    )
