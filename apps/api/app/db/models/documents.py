from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Computed, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

PARSE_STATUSES = ("PENDING", "PARSING", "PARSED", "NEEDS_OCR_OR_REVIEW", "FAILED")


class StoredFile(Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("project_id", "sha256", name="uq_files_project_sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_name: Mapped[str] = mapped_column(String(300), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_document_versions_project_version"),
        CheckConstraint(
            "parse_status in ('PENDING','PARSING','PARSED','NEEDS_OCR_OR_REVIEW','FAILED')", name="parse_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    parser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class SourceSpan(Base):
    """An immutable, citable fragment of a parsed document with an exact anchor."""

    __tablename__ = "source_spans"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_source_spans_doc_ordinal"),
        CheckConstraint("anchor_type in ('PDF_PAGE','DOCX_PARAGRAPH','DOCX_TABLE_CELL')", name="anchor_type"),
        CheckConstraint("char_end > char_start", name="char_range"),
        Index("ix_source_spans_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-based, PDF only
    paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # DOCX body paragraph index
    table_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)  # DOCX "t{n}:r{r}:c{c}"
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)  # offset within page / paragraph raw text
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    exact_quote: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', normalized_text)", persisted=True))
    created_at: Mapped[datetime] = created_at_col()
