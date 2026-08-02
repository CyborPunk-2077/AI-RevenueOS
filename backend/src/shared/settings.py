"""Typed, environment-overridable configuration.

Lives in `shared` rather than `api` because application services, infrastructure
adapters, workers and the scheduler all need it. Configuration is not an HTTP
concern. No secret ever ships in an image.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "sandbox", "prod"]


class FeatureFlagDefaults(BaseSettings):
    """Global kill switches. Every externally gated capability defaults OFF."""

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    whatsapp_enabled: bool = False  # gate: BSP/Cloud API + template approval
    email_enabled: bool = False  # gate: provider + domain/DNS ownership
    sms_enabled: bool = False  # gate: provider decision + India DLT registration
    voice_enabled: bool = False  # gate: legal disclosure + recording consent
    payments_enabled: bool = False  # gate: Razorpay commercial model
    ai_enabled: bool = True  # safe: degrades to manual without credentials
    workflows_enabled: bool = True
    webchat_enabled: bool = True
    n8n_authoring_enabled: bool = False  # gate: hosting/licensing owner
    calendar_sync_enabled: bool = False  # gate: OAuth verification scope
    signatures_enabled: bool = False  # gate: signature provider agreement
    storage_enabled: bool = False  # gate: AWS + bucket policy + malware scanner verification
    pilot_cohort_enabled: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    environment: Environment = "local"
    debug: bool = False
    service_name: str = "airevenueos-api"
    api_version: str = "v1"
    release: str = "0.24.0"
    root_path: str = ""

    # --- data plane -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://airevenueos:airevenueos@localhost:5432/airevenueos"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_statement_timeout_ms: int = 15_000
    # Partition creation and retention DDL need CREATE on the schemas. The runtime
    # application role deliberately does not have it, so maintenance connects with
    # a separate, elevated credential. Absent it, maintenance DDL is skipped and
    # reported rather than silently failing.
    maintenance_database_url: str | None = Field(default=None, repr=False)
    redis_url: str = "redis://localhost:6379/0"

    # --- identity ---------------------------------------------------------
    jwt_algorithm: Literal["RS256"] = "RS256"
    jwt_issuer: str = "https://api.airevenueos.io"
    jwt_private_key: str | None = Field(default=None, repr=False)
    jwt_public_key: str | None = Field(default=None, repr=False)
    jwt_kid: str = "local-dev"
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 604_800  # 7 days sliding
    max_sessions_per_user: int = 10
    idle_reauth_seconds: int = 7_200  # 2 hours
    hard_reauth_seconds: int = 28_800  # 8 hours
    password_min_length: int = 12
    password_history: int = 5
    admin_password_max_age_days: int = 90
    hibp_check_enabled: bool = True

    encryption_master_key: str | None = Field(default=None, repr=False)

    # --- edge -------------------------------------------------------------
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    api_host_template: str = "api.{tenant_slug}.airevenueos.io"
    json_body_limit_bytes: int = 10 * 1024 * 1024
    protected_upload_limit_bytes: int = 50 * 1024 * 1024
    public_upload_limit_bytes: int = 25 * 1024 * 1024

    # --- defaults ---------------------------------------------------------
    default_timezone: str = "Asia/Kolkata"
    default_currency: str = "INR"
    default_locale: str = "en-IN"

    # --- providers (all optional; absence disables the feature, never fabricated) --
    anthropic_api_key: str | None = Field(default=None, repr=False)
    openai_api_key: str | None = Field(default=None, repr=False)
    google_ai_api_key: str | None = Field(default=None, repr=False)
    razorpay_key_id: str | None = Field(default=None, repr=False)
    razorpay_key_secret: str | None = Field(default=None, repr=False)
    razorpay_webhook_secret: str | None = Field(default=None, repr=False)
    whatsapp_phone_number_id: str | None = Field(default=None, repr=False)
    whatsapp_access_token: str | None = Field(default=None, repr=False)
    whatsapp_app_secret: str | None = Field(default=None, repr=False)
    whatsapp_verify_token: str | None = Field(default=None, repr=False)
    email_provider: Literal["none", "ses", "sendgrid"] = "none"
    email_api_key: str | None = Field(default=None, repr=False)
    email_from_address: str | None = None
    voice_provider: Literal["none", "exotel", "twilio"] = "none"
    google_client_id: str | None = None
    google_client_secret: str | None = Field(default=None, repr=False)
    google_redirect_uri: str = "http://localhost:3000/api/auth/google/callback"

    # --- storage ----------------------------------------------------------
    s3_bucket_uploads: str = "airevenueos-local-uploads"
    s3_bucket_documents: str = "airevenueos-local-documents"
    s3_bucket_exports: str = "airevenueos-local-exports"
    s3_region: str = "ap-south-1"
    s3_endpoint_url: str | None = None
    presigned_upload_ttl_seconds: int = 900
    presigned_download_ttl_seconds: int = 300
    clamav_host: str | None = None

    # --- observability ----------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    sentry_dsn: str | None = Field(default=None, repr=False)
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = Field(default=None, repr=False)
    metrics_allowed_cidrs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1/32", "10.0.0.0/8"]
    )

    features: FeatureFlagDefaults = Field(default_factory=FeatureFlagDefaults)

    @field_validator(
        "cors_allowed_origins", "trusted_hosts", "metrics_allowed_cidrs", mode="before"
    )
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")

    def storage_configuration_issues(self) -> list[str]:
        """Return declarative storage gaps without contacting AWS.

        This validates configuration only. Provider activation still requires the
        live checks in the storage activation runbook; a bucket name is not proof
        that the bucket exists or that the task role can use it.
        """
        issues: list[str] = []
        buckets = {
            "S3_BUCKET_UPLOADS": self.s3_bucket_uploads,
            "S3_BUCKET_DOCUMENTS": self.s3_bucket_documents,
            "S3_BUCKET_EXPORTS": self.s3_bucket_exports,
        }
        for name, value in buckets.items():
            if not value or value.startswith("airevenueos-local-"):
                issues.append(f"{name} must name a real private bucket")
        values = [value for value in buckets.values() if value]
        if len(set(values)) != len(values):
            issues.append("storage buckets must be distinct")
        if not self.s3_region.strip():
            issues.append("S3_REGION is required")
        if self.s3_endpoint_url and not self.s3_endpoint_url.startswith("https://"):
            issues.append("S3_ENDPOINT_URL must use HTTPS")
        if not self.clamav_host:
            issues.append("CLAMAV_HOST is required before uploads can be enabled")
        return issues

    def assert_production_safe(self) -> None:
        """Fail fast rather than boot production with a missing critical secret."""
        if not self.is_production:
            return
        missing = [
            name
            for name, value in (
                ("JWT_PRIVATE_KEY", self.jwt_private_key),
                ("JWT_PUBLIC_KEY", self.jwt_public_key),
                ("ENCRYPTION_MASTER_KEY", self.encryption_master_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"production configuration incomplete: {', '.join(missing)}")
        if "*" in self.cors_allowed_origins:
            raise RuntimeError("wildcard CORS origin is forbidden in production")
        if self.debug:
            raise RuntimeError("debug must be disabled in production")
        if self.features.storage_enabled:
            issues = self.storage_configuration_issues()
            if issues:
                raise RuntimeError(f"storage configuration incomplete: {'; '.join(issues)}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_safe()
    return settings
