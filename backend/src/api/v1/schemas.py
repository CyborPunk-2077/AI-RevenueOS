"""Pydantic boundary models. Strict, unknown fields forbidden, snake_case JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.utils.phone import InvalidPhone, normalize_phone
from shared.utils.text import normalize_email

STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class StrictModel(BaseModel):
    model_config = STRICT


class LoginRequest(StrictModel):
    email: Annotated[str, Field(min_length=3, max_length=320)]
    password: Annotated[str, Field(min_length=1, max_length=256)]

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class RefreshRequest(StrictModel):
    refresh_token: Annotated[str, Field(min_length=8, max_length=512)]


class SignupRequest(StrictModel):
    email: Annotated[str, Field(min_length=3, max_length=320)]
    # The policy floor is 12; enforcing a minimum here too means an obviously
    # short password is refused before it is ever hashed.
    password: Annotated[str, Field(min_length=12, max_length=256)]
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    organisation: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class ForgotPasswordRequest(StrictModel):
    email: Annotated[str, Field(min_length=3, max_length=320)]


class ResetPasswordRequest(StrictModel):
    token: Annotated[str, Field(min_length=16, max_length=512)]
    password: Annotated[str, Field(min_length=12, max_length=256)]


class VerifyEmailRequest(StrictModel):
    token: Annotated[str, Field(min_length=16, max_length=512)]


class MfaVerifyRequest(StrictModel):
    """Serves both roles: completing a login challenge, and stepping up in place.

    With `mfa_token` it finishes a pending sign-in. Without it, the caller must
    already hold a session and is re-proving the factor to unlock a sensitive
    operation. `code` accepts a recovery code too, which is longer than 6 digits.
    """

    code: Annotated[str, Field(min_length=6, max_length=32)]
    mfa_token: Annotated[str | None, Field(max_length=512)] = None


class MfaSetupConfirmRequest(StrictModel):
    pending: Annotated[str, Field(min_length=16, max_length=4096)]
    code: Annotated[str, Field(min_length=6, max_length=8)]


class MfaDisableRequest(StrictModel):
    password: Annotated[str, Field(min_length=1, max_length=256)]
    code: Annotated[str, Field(min_length=6, max_length=32)]


class MfaRecoveryRequest(StrictModel):
    code: Annotated[str, Field(min_length=6, max_length=8)]


class ApiKeyCreateRequest(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    scopes: Annotated[list[str], Field(max_length=200)] = []


class ContactIdentity(StrictModel):
    email: str | None = None
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return normalize_email(v) if v else None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return normalize_phone(v)
        except InvalidPhone as exc:
            raise ValueError(str(exc)) from exc


class ContactCreate(ContactIdentity):
    """At least one of email/phone is required; the table enforces it too."""

    first_name: Annotated[str, Field(min_length=1, max_length=120)]
    last_name: Annotated[str | None, Field(max_length=120)] = None
    company: Annotated[str | None, Field(max_length=200)] = None
    title: Annotated[str | None, Field(max_length=150)] = None
    source: Annotated[str, Field(max_length=80)] = "manual"
    tags: Annotated[list[str], Field(max_length=50)] = []
    address: dict[str, Any] = Field(default_factory=dict)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    account_id: UUID | None = None
    assignee_id: UUID | None = None
    branch_id: UUID | None = None
    team_id: UUID | None = None


class ContactUpdate(StrictModel):
    first_name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    last_name: Annotated[str | None, Field(max_length=120)] = None
    email: str | None = None
    phone: str | None = None
    company: Annotated[str | None, Field(max_length=200)] = None
    title: Annotated[str | None, Field(max_length=150)] = None
    status: Literal["active", "inactive", "archived"] | None = None
    tags: Annotated[list[str] | None, Field(max_length=50)] = None
    # Explicitly nullable: sending null unlinks the account, which is different
    # from omitting the field.
    account_id: UUID | None = None
    assignee_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return normalize_email(v) if v else None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return normalize_phone(v)
        except InvalidPhone as exc:
            raise ValueError(str(exc)) from exc


class AccountCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    industry: Annotated[str | None, Field(max_length=100)] = None
    website: Annotated[str | None, Field(max_length=300)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    employee_count: Annotated[int | None, Field(ge=0, le=10_000_000)] = None
    address: dict[str, Any] = Field(default_factory=dict)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None


class AccountUpdate(StrictModel):
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    industry: Annotated[str | None, Field(max_length=100)] = None
    website: Annotated[str | None, Field(max_length=300)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    employee_count: Annotated[int | None, Field(ge=0, le=10_000_000)] = None
    owner_id: UUID | None = None


class LeadCreate(ContactIdentity):
    first_name: Annotated[str, Field(min_length=1, max_length=120)]
    last_name: Annotated[str | None, Field(max_length=120)] = None
    source: Annotated[str, Field(max_length=80)] = "manual"
    source_channel: Annotated[str | None, Field(max_length=50)] = None
    capture: dict[str, Any] = Field(default_factory=dict)
    utm: dict[str, Any] = Field(default_factory=dict)
    assignee_id: UUID | None = None
    branch_id: UUID | None = None
    team_id: UUID | None = None

    @field_validator("capture", "utm")
    @classmethod
    def _bounded(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 100:
            raise ValueError("at most 100 keys are permitted")
        return v


class LeadUpdate(StrictModel):
    first_name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    last_name: Annotated[str | None, Field(max_length=120)] = None
    status: (
        Literal[
            "new", "qualified", "contacted", "nurturing", "converted", "disqualified", "archived"
        ]
        | None
    ) = None
    assignee_id: UUID | None = None
    capture: dict[str, Any] | None = None
    disqualify_reason: Annotated[str | None, Field(max_length=200)] = None


class LeadQualifyRequest(StrictModel):
    mode: Literal["ai", "manual", "rule"] = "rule"
    manual_score: Annotated[int | None, Field(ge=0, le=100)] = None
    notes: Annotated[str | None, Field(max_length=1000)] = None


class LeadReviewRequest(StrictModel):
    decision: Literal["accepted", "edited", "rejected", "deferred"]
    edited_score: Annotated[int | None, Field(ge=0, le=100)] = None
    note: Annotated[str | None, Field(max_length=1000)] = None


class LeadResource(StrictModel):
    id: UUID
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    source: str
    status: str
    qualification_score: int | None = None
    category: str | None = None
    assignee_id: UUID | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PublicFormSubmission(StrictModel):
    """Public submissions are validated against the published schema, then normalised."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    first_name: Annotated[str, Field(min_length=1, max_length=120)]
    last_name: Annotated[str | None, Field(max_length=120)] = None
    email: str | None = None
    phone: str | None = None
    consent: bool = False
    anti_abuse_token: Annotated[str, Field(min_length=8, max_length=512)]
    utm: dict[str, str] = Field(default_factory=dict)


class AiChatRequest(StrictModel):
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    conversation_id: UUID | None = None
    entity_type: Literal["lead", "contact", "deal", "conversation"] | None = None
    entity_id: UUID | None = None
    stream: bool = False


class AiTaskRequest(StrictModel):
    task: Literal["generate", "classify", "extract", "summarize", "search", "analyze", "translate"]
    input: Annotated[str, Field(min_length=1, max_length=32_000)]
    entity_type: str | None = None
    entity_id: UUID | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class WorkflowValidateRequest(StrictModel):
    document: dict[str, Any]


class WorkflowPublishRequest(StrictModel):
    document: dict[str, Any]
    changelog: Annotated[str, Field(max_length=2000)] = ""


class TenantPatch(StrictModel):
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    locale: Annotated[str | None, Field(max_length=10)] = None
    branding: dict[str, Any] | None = None
    business_hours: dict[str, Any] | None = None
    billing_gstin: Annotated[str | None, Field(max_length=20)] = None


class OnboardingPatch(StrictModel):
    step: Literal["welcome", "tenant", "industry", "channels", "team", "billing"]
    data: dict[str, Any] = Field(default_factory=dict)
