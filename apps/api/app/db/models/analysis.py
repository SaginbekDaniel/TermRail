from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

CATEGORIES = ("IN_SCOPE", "BUG_FIX", "CHANGE_CANDIDATE", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE")
_CAT_SQL = "('IN_SCOPE','BUG_FIX','CHANGE_CANDIDATE','AMBIGUOUS','INSUFFICIENT_EVIDENCE')"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("status in ('QUEUED','RUNNING','SUCCEEDED','NEEDS_REVIEW','FAILED')", name="status"),
        UniqueConstraint("request_id", "idempotency_key", name="uq_analysis_runs_request_idem"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id"), nullable=False, index=True
    )
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scope_baselines.id"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "request_item_id", name="uq_findings_run_item"),
        CheckConstraint(f"category in {_CAT_SQL}", name="category"),
        CheckConstraint(f"ai_category is null or ai_category in {_CAT_SQL}", name="ai_category"),
        CheckConstraint(f"final_category is null or final_category in {_CAT_SQL}", name="final_category"),
        CheckConstraint(
            "review_status in ('PENDING','AUTO_ACCEPTED','ACCEPTED','OVERRIDDEN','CLARIFICATION_REQUESTED')",
            name="review_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_items.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # after server policy gates
    ai_category: Mapped[str | None] = mapped_column(String(30), nullable=True)  # raw model output
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    uncertainties: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    clarifying_questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    policy_notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    validation_errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    final_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    __table_args__ = (CheckConstraint("polarity in ('SUPPORTING','COUNTER')", name="polarity"),)

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True
    )
    source_span_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_spans.id"), primary_key=True
    )
    polarity: Mapped[str] = mapped_column(String(20), primary_key=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    scope_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_items.id"), nullable=True
    )


class FindingReview(Base):
    """Append-only manager decisions on a finding."""

    __tablename__ = "finding_reviews"
    __table_args__ = (
        CheckConstraint("decision in ('ACCEPT','OVERRIDE','REQUEST_CLARIFICATION')", name="decision"),
        CheckConstraint(f"category in {_CAT_SQL}", name="category"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at_col()
