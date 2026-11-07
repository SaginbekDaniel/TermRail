from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

REQUEST_STATUSES = ("NEW", "ANALYZING", "NEEDS_REVIEW", "REVIEWED", "FAILED")


class ClientRequest(Base):
    """An incoming client message (the raw text is immutable)."""

    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint("channel in ('MANUAL','EMAIL')", name="channel"),
        CheckConstraint("status in ('NEW','ANALYZING','NEEDS_REVIEW','REVIEWED','FAILED')", name="status"),
        CheckConstraint("length(btrim(message_text)) > 0", name="message_not_empty"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_requests_project_idem"),
        Index(
            "uq_requests_external",
            "workspace_id",
            "channel",
            "external_id",
            unique=True,
            postgresql_where=text("external_id is not null"),
        ),
        Index("ix_requests_ws_project_status", "workspace_id", "project_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sender: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="NEW")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class RequestItem(Base):
    """One atomic requirement; exact_text == message_text[start_offset:end_offset]."""

    __tablename__ = "request_items"
    __table_args__ = (
        UniqueConstraint("request_id", "ordinal", name="uq_request_items_request_ordinal"),
        CheckConstraint("end_offset > start_offset and start_offset >= 0", name="offsets"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    exact_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at_col()
