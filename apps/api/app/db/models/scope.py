from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, updated_at_col, uuid_pk

INCLUSION_TYPES = ("INCLUDED", "EXCLUDED", "CONDITION")


class ScopeBaseline(Base):
    """DRAFT baselines are editable; APPROVED baselines are immutable (enforced by DB triggers)."""

    __tablename__ = "scope_baselines"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_scope_baselines_project_version"),
        CheckConstraint("status in ('DRAFT','APPROVED')", name="status"),
        Index(
            "uq_scope_baselines_one_draft",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    based_on_baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_baselines.id"), nullable=True
    )
    baseline_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class BaselineDocument(Base):
    __tablename__ = "baseline_documents"

    baseline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_baselines.id", ondelete="CASCADE"), primary_key=True
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id"), primary_key=True
    )


class ScopeItem(Base):
    __tablename__ = "scope_items"
    __table_args__ = (
        CheckConstraint("inclusion_type in ('INCLUDED','EXCLUDED','CONDITION')", name="inclusion_type"),
        CheckConstraint("origin in ('AI_CANDIDATE','MANUAL')", name="origin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    inclusion_type: Mapped[str] = mapped_column(String(20), nullable=False)
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ScopeEvidence(Base):
    __tablename__ = "scope_evidence"

    scope_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_items.id", ondelete="CASCADE"), primary_key=True
    )
    source_span_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_spans.id"), primary_key=True, index=True
    )
