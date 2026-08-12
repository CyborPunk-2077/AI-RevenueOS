"""Pydantic boundary models. Strict, unknown fields forbidden, snake_case JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class LeadMergeRequest(StrictModel):
    merge_id: UUID


class LeadDisqualifyRequest(StrictModel):
    # Long enough to be a sentence: an unexplained disqualification is
    # indistinguishable from a mis-click a quarter later.
    reason: Annotated[str, Field(min_length=3, max_length=200)]


class AssignmentRuleCreateRequest(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=150)]
    strategy: Literal["round_robin", "first_available", "load_balanced"] = "round_robin"
    conditions: dict[str, Any] = Field(default_factory=dict)
    targets: list[str] = Field(default_factory=list)
    position: int | None = None


class AssignmentRuleUpdateRequest(StrictModel):
    name: Annotated[str | None, Field(min_length=1, max_length=150)] = None
    strategy: Literal["round_robin", "first_available", "load_balanced"] | None = None
    conditions: dict[str, Any] | None = None
    targets: list[str] | None = None
    position: int | None = None
    is_active: bool | None = None


class ReorderRulesRequest(StrictModel):
    rule_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]


class WebchatWidgetRequest(StrictModel):
    allowed_origins: list[str] | None = None
    greeting: Annotated[str | None, Field(max_length=500)] = None
    consent_copy: Annotated[str | None, Field(max_length=1000)] = None
    branding: dict[str, Any] | None = None
    handoff_enabled: bool | None = None
    ai_suggestions_enabled: bool | None = None
    is_active: bool | None = None


class WebchatSessionRequest(StrictModel):
    public_key: Annotated[str, Field(min_length=8, max_length=64)]
    # Stitches a returning visitor's tabs together. Untrusted, and never used to
    # identify anyone.
    visitor_ref: Annotated[str | None, Field(max_length=64)] = None
    consent_granted: bool = False


class WebchatMessageRequest(StrictModel):
    session_token: Annotated[str, Field(min_length=8, max_length=512)]
    body: Annotated[str, Field(max_length=2000)] = ""


class FormCreateRequest(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=150)]
    type: Literal["embedded", "hosted", "popup"] = "embedded"
    # `schema` shadows a BaseModel attribute, so the field is `schema_` and the
    # JSON name stays `schema`.
    schema_: Annotated[dict[str, Any], Field(alias="schema")]
    allowed_origins: list[str] = Field(default_factory=list)
    source: Annotated[str | None, Field(max_length=80)] = None
    settings: dict[str, Any] = Field(default_factory=dict)


class FormUpdateRequest(StrictModel):
    name: Annotated[str | None, Field(min_length=1, max_length=150)] = None
    schema_: Annotated[dict[str, Any] | None, Field(alias="schema")] = None
    allowed_origins: list[str] | None = None
    source: Annotated[str | None, Field(max_length=80)] = None
    settings: dict[str, Any] | None = None


class InviteUserRequest(StrictModel):
    email: Annotated[str, Field(min_length=3, max_length=320)]
    # Not a free string: an unknown role would otherwise reach the service and be
    # rejected there, one layer further from the caller than necessary.
    role: Literal["owner", "admin", "manager", "member", "viewer"]

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class AcceptInvitationRequest(StrictModel):
    token: Annotated[str, Field(min_length=8, max_length=512)]
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    # The policy floor is 12; refusing an obviously short password here means it is
    # never hashed.
    password: Annotated[str, Field(min_length=12, max_length=256)]


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


class DealCreate(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=250)]
    # Minor units (paise). Storing money as an integer avoids float rounding.
    amount_minor: Annotated[int, Field(ge=0, le=10**15)] = 0
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "INR"
    stage_id: UUID | None = None
    contact_id: UUID | None = None
    account_id: UUID | None = None
    assignee_id: UUID | None = None
    expected_close_date: datetime | None = None


class DealUpdate(StrictModel):
    title: Annotated[str | None, Field(min_length=1, max_length=250)] = None
    amount_minor: Annotated[int | None, Field(ge=0, le=10**15)] = None
    expected_close_date: datetime | None = None
    assignee_id: UUID | None = None
    contact_id: UUID | None = None
    account_id: UUID | None = None


class DealStageMoveRequest(StrictModel):
    stage_id: UUID
    # Required by the domain policy when the target stage is a lost stage.
    loss_reason: Annotated[str | None, Field(max_length=200)] = None


class AppointmentBook(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=250)]
    start_at: datetime
    duration_minutes: Annotated[int, Field(ge=5, le=24 * 60)] = 30
    location_type: Literal["physical", "virtual", "phone"] = "physical"
    location_detail: Annotated[str | None, Field(max_length=500)] = None
    timezone: Annotated[str, Field(max_length=64)] = "Asia/Kolkata"
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    organizer_id: UUID | None = None


class AppointmentReschedule(StrictModel):
    start_at: datetime
    duration_minutes: Annotated[int | None, Field(ge=5, le=24 * 60)] = None


class AppointmentCancel(StrictModel):
    reason: Annotated[str | None, Field(max_length=300)] = None


class AppointmentOutcome(StrictModel):
    status: Literal["completed", "no_show"]
    outcome: Annotated[str | None, Field(max_length=80)] = None
    outcome_note: Annotated[str | None, Field(max_length=5000)] = None


class ConversationCreate(StrictModel):
    primary_channel: Literal["whatsapp", "email", "web_chat", "voice", "sms"] = "web_chat"
    subject: Annotated[str | None, Field(max_length=300)] = None
    contact_id: UUID | None = None
    assignee_id: UUID | None = None


class ConversationUpdate(StrictModel):
    subject: Annotated[str | None, Field(max_length=300)] = None
    status: Literal["active", "resolved", "archived", "spam"] | None = None
    assignee_id: UUID | None = None


class MessageCreate(StrictModel):
    content: Annotated[str, Field(min_length=1, max_length=20_000)]
    channel: Literal["whatsapp", "email", "web_chat", "voice", "sms"] | None = None


class TaskCreate(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=250)]
    description: Annotated[str | None, Field(max_length=5000)] = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_at: datetime | None = None
    assignee_id: UUID | None = None
    entity_type: Literal["contact", "account", "deal", "lead"] | None = None
    entity_id: UUID | None = None
    is_next_action: bool = False


class TaskUpdate(StrictModel):
    title: Annotated[str | None, Field(min_length=1, max_length=250)] = None
    description: Annotated[str | None, Field(max_length=5000)] = None
    status: Literal["open", "in_progress", "completed", "cancelled"] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    # Explicitly nullable: sending null clears the date or the owner.
    due_at: datetime | None = None
    assignee_id: UUID | None = None
    is_next_action: bool | None = None


class ActivityLogRequest(StrictModel):
    """Only the types a human may log by hand; `system` is platform-written."""

    activity_type: Literal["call", "email", "meeting", "note", "task", "whatsapp"]
    subject: Annotated[str, Field(min_length=1, max_length=300)]
    body: Annotated[str | None, Field(max_length=10_000)] = None


class NoteCreateRequest(StrictModel):
    body: Annotated[str, Field(min_length=1, max_length=10_000)]
    is_pinned: bool = False


class NoteUpdateRequest(StrictModel):
    body: Annotated[str | None, Field(min_length=1, max_length=10_000)] = None
    is_pinned: bool | None = None


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


class LeadBulkChanges(StrictModel):
    status: (
        Literal["new", "qualified", "contacted", "nurturing", "disqualified", "archived"] | None
    ) = None
    assignee_id: UUID | None = None
    disqualify_reason: Annotated[str | None, Field(max_length=200)] = None

    @model_validator(mode="after")
    def _has_mutation(self) -> LeadBulkChanges:
        if not ({"status", "assignee_id"} & self.model_fields_set):
            raise ValueError("bulk changes require status or assignee_id")
        if self.status == "disqualified" and not self.disqualify_reason:
            raise ValueError("disqualify_reason is required when disqualifying leads")
        return self


class LeadBulkUpdateRequest(StrictModel):
    lead_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    changes: LeadBulkChanges

    @field_validator("lead_ids")
    @classmethod
    def _unique_lead_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("lead_ids must be unique")
        return value


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


class WorkflowApprovalDecisionRequest(StrictModel):
    decision: Literal["approved", "rejected"]
    comment: Annotated[str, Field(max_length=1000)] = ""


class ConsentGrantRequest(StrictModel):
    subject_type: Literal["contact"] = "contact"
    subject_id: UUID
    consent_type: Literal["marketing", "communication", "data_processing", "whatsapp_optin"]
    channel: Literal["whatsapp", "email", "sms", "voice", "web_chat"]
    policy_version: Annotated[str, Field(min_length=1, max_length=30)]
    # Authenticated users cannot label evidence as provider/import/public-form
    # sourced; those labels are reserved for their trusted ingestion paths.
    source: Literal["api", "agent_confirmed"] = "api"
    evidence: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @field_validator("evidence")
    @classmethod
    def _bounded_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json

        if len(value) > 30:
            raise ValueError("consent evidence may contain at most 30 fields")
        if len(json.dumps(value, default=str)) > 16_000:
            raise ValueError("consent evidence may not exceed 16000 bytes")
        return value


class ConsentWithdrawRequest(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ProviderConfigurationRequest(StrictModel):
    identifier: Annotated[str, Field(min_length=1, max_length=200)] = "default"
    display_name: Annotated[str, Field(max_length=150)] = ""
    settings: dict[str, str | bool | int] = Field(default_factory=dict)
    credentials: dict[str, Annotated[str, Field(min_length=1, max_length=8000)]] = Field(
        default_factory=dict
    )

    @field_validator("settings", "credentials")
    @classmethod
    def _bounded_provider_map(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 30:
            raise ValueError("provider configuration may contain at most 30 fields")
        return value


class SupportAccessRequest(StrictModel):
    support_user_ref: Annotated[str, Field(min_length=3, max_length=200)]
    purpose: Annotated[str, Field(min_length=10, max_length=500)]
    duration_minutes: Annotated[int, Field(ge=5, le=60)] = 30


class PromptEvaluationCaseResult(StrictModel):
    case_id: Annotated[str, Field(min_length=1, max_length=120)]
    passed: bool
    detail: Annotated[str, Field(max_length=500)] = ""


class PromptEvaluationRequest(StrictModel):
    evaluation_set: Annotated[str, Field(min_length=1, max_length=120)] = "baseline"
    evaluation_version: Annotated[int, Field(ge=1)] = 1
    content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    results: Annotated[list[PromptEvaluationCaseResult], Field(min_length=1, max_length=500)]


class PromptPromotionRequest(StrictModel):
    evaluation_run_id: UUID


class PromptRollbackRequest(StrictModel):
    target_version: Annotated[int, Field(ge=1)]


class TenantPatch(StrictModel):
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    locale: Annotated[str | None, Field(max_length=10)] = None
    branding: dict[str, Any] | None = None
    business_hours: dict[str, Any] | None = None
    billing_gstin: Annotated[str | None, Field(max_length=20)] = None


class OnboardingPatch(StrictModel):
    step: Literal["welcome", "tenant", "industry", "channels", "team", "billing"]
    status: Literal["in_progress", "completed", "skipped"]


class FileUploadRequest(StrictModel):
    """Declared metadata for a file the caller intends to upload.

    The size and MIME type here are *claims*. They are checked again against the
    stored object once object storage exists, which is why the field names say
    "declared" downstream. Accepting them at this boundary only decides whether an
    upload is worth authorising at all.
    """

    name: Annotated[str, Field(min_length=1, max_length=300)]
    size_bytes: Annotated[int, Field(ge=1, le=100 * 1024 * 1024)]
    mime_type: Annotated[str, Field(min_length=3, max_length=150)]
    classification: Literal["P0", "P1", "P2", "P3"] = "P2"
    entity_type: Literal["contact", "account", "deal"] | None = None
    entity_id: UUID | None = None


class DocumentCreate(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    file_id: UUID | None = None


class DocumentUpdate(StrictModel):
    title: Annotated[str | None, Field(min_length=1, max_length=300)] = None
    # Timestamps for these transitions are stamped server-side, never supplied.
    status: Literal["draft", "generated", "sent", "viewed", "signed", "expired", "void"] | None = (
        None
    )
    file_id: UUID | None = None
