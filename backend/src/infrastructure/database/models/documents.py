"""Files, documents, signatures, extraction review and RAG chunk storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import (
    SCHEMA_APP,
    ActorMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
    register_tenant_table,
)

SCAN_STATUSES = ("pending", "scanning", "clean", "quarantined", "rejected")
DOCUMENT_STATUSES = ("draft", "generated", "sent", "viewed", "signed", "expired", "void")
EMBEDDING_DIM = 1536


class FileObject(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(f"scan_status IN {SCAN_STATUSES}", name="scan_status_valid"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        UniqueConstraint("tenant_id", "object_key", name="tenant_object"),
        Index("ix_files_tenant_sha", "tenant_id", "sha256"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    owner_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    bucket: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(
        String(150), nullable=False, default="application/octet-stream"
    )
    declared_mime: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scan_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification: Mapped[str] = mapped_column(String(4), nullable=False, default="P2")
    is_public_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)


class DocumentTemplate(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "document_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="document_template_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Document(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"status IN {DOCUMENT_STATUSES}", name="status_valid"),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    template_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    deal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_requests"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    requested_types: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    upload_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignatureRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "signature_requests"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="none")
    external_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    signers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_trail: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class DocumentExtraction(IdMixin, TimestampMixin, Base):
    """Extracted facts never silently become truth: provenance plus explicit review."""

    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint(
            "review_state IN ('pending','accepted','edited','rejected')", name="review_state_valid"
        ),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    schema_key: Mapped[str] = mapped_column(String(80), nullable=False)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_to: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class KnowledgeArticle(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "knowledge_articles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="tenant_slug"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DocumentChunk(IdMixin, TimestampMixin, Base):
    """Tenant filter on retrieval is mandatory, not advisory."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_type", "source_id", "chunk_index", name="source_chunk"
        ),
        Index("ix_document_chunks_tenant_source", "tenant_id", "source_type", "source_id"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    classification: Mapped[str] = mapped_column(String(4), nullable=False, default="P2")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class LeadEmbedding(IdMixin, TimestampMixin, Base):
    __tablename__ = "lead_embeddings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "lead_id", name="tenant_lead"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    lead_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80), nullable=True)


for _t in (
    "files",
    "document_templates",
    "documents",
    "document_requests",
    "signature_requests",
    "document_extractions",
    "knowledge_articles",
    "document_chunks",
    "lead_embeddings",
):
    register_tenant_table(_t)
