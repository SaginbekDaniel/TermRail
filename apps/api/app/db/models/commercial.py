from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, updated_at_col, uuid_pk

CO_STATUSES = (
    "DRAFT",
    "INTERNAL_REVIEW",
    "APPROVED_INTERNAL",
    "EXPORTED",
    "CANCELLED",
)


class RateCard(Base):
    """Immutable rate rows; a PUT creates a new revision for the whole project rate card."""

    __tablename__ = "rate_cards"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", "role", name="uq_rate_cards_project_rev_role"),
        CheckConstraint("hourly_rate >= 0", name="rate_nonnegative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Estimate(Base):
    __tablename__ = "estimates"
    __table_args__ = (
        UniqueConstraint("request_item_id", "version", name="uq_estimates_item_version"),
        CheckConstraint("status in ('DRAFT','APPROVED')", name="status"),
        CheckConstraint("subtotal >= 0", name="subtotal_nonnegative"),
        CheckConstraint("timeline_days is null or timeline_days >= 0", name="timeline_nonnegative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=False)
    request_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_items.id"), nullable=False, index=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("findings.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_card_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    timeline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class EstimateLine(Base):
    __tablename__ = "estimate_lines"
    __table_args__ = (
        CheckConstraint("kind in ('HOURLY','FIXED')", name="kind"),
        CheckConstraint("hours is null or hours >= 0", name="hours_nonnegative"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        UniqueConstraint("estimate_id", "ordinal", name="uq_estimate_lines_estimate_ordinal"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    estimate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class ChangeOrder(Base):
    __tablename__ = "change_orders"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_change_orders_project_number"),
        CheckConstraint(
            "status in ('DRAFT','INTERNAL_REVIEW','APPROVED_INTERNAL','EXPORTED','CANCELLED')", name="status"
        ),
        UniqueConstraint("project_id", "idempotency_key", name="uq_change_orders_project_idem"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_order_revisions.id", use_alter=True), nullable=True
    )
    approved_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_order_revisions.id", use_alter=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ChangeOrderRevision(Base):
    """Immutable snapshot of a change order's content (enforced by DB trigger)."""

    __tablename__ = "change_order_revisions"
    __table_args__ = (UniqueConstraint("change_order_id", "revision_no", name="uq_co_revisions_co_no"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    change_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_orders.id"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Approval(Base):
    """Append-only approval decisions bound to an exact revision + content hash."""

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("target_type in ('CHANGE_ORDER_REVISION','SCOPE_BASELINE','ESTIMATE')", name="target_type"),
        CheckConstraint("decision in ('APPROVED','CHANGES_REQUESTED','REJECTED')", name="decision"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_at: Mapped[datetime] = created_at_col()


class ChangeOrderExport(Base):
    __tablename__ = "change_order_exports"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    change_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_orders.id"), nullable=False, index=True
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_order_revisions.id"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_draft: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


__all__ = [
    "Approval",
    "ChangeOrder",
    "ChangeOrderExport",
    "ChangeOrderRevision",
    "Estimate",
    "EstimateLine",
    "RateCard",
]
