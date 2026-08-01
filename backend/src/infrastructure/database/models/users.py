"""Identity, RBAC, sessions and MFA."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import (
    SCHEMA_APP,
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
    register_tenant_table,
)

USER_STATUSES = ("invited", "active", "suspended", "deactivated")


class User(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"status IN {USER_STATUSES}", name="status_valid"),
        Index(
            "uq_users_tenant_email_active",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_history: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_recovery_codes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )


class Role(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="role_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="self")


class RolePermission(IdMixin, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_code", name="role_permission"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False)


class UserRole(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="user_role"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.roles.id", ondelete="CASCADE"),
        nullable=False,
    )


class RefreshToken(IdMixin, TimestampMixin, Base):
    """Opaque, hashed, rotating. Family reuse revokes every session in the family."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_family", "user_id", "family_id"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    parent_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class GoogleIdentity(IdMixin, TimestampMixin, Base):
    __tablename__ = "google_identities"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    google_sub: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Invitation(IdMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    invited_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordReset(IdMixin, TimestampMixin, Base):
    __tablename__ = "password_resets"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailVerification(IdMixin, TimestampMixin, Base):
    """Single-use email-confirmation token. Only the hash is stored."""

    __tablename__ = "email_verifications"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(IdMixin, TimestampMixin, Base):
    """Developer-only credential. The plaintext value is revealed exactly once."""

    __tablename__ = "api_keys"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_allowlist: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class SupportAccessGrant(IdMixin, TimestampMixin, Base):
    """Tiered, purpose-bound, time-limited. Never direct production database access."""

    __tablename__ = "support_access_grants"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    support_user_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="read")
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    second_approver: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


for _t in (
    "users",
    "roles",
    "role_permissions",
    "user_roles",
    "refresh_tokens",
    "google_identities",
    "invitations",
    "password_resets",
    "email_verifications",
    "api_keys",
    "support_access_grants",
):
    register_tenant_table(_t)
