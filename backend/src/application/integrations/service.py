"""Tenant configuration requests with encrypted secrets and truthful activation state."""

from __future__ import annotations

import json
from typing import Any

from domain.auth.permissions import Scope
from domain.base import DomainEvent
from domain.events.catalog import INTEGRATION_CONFIGURED, INTEGRATION_UPDATED
from shared.exceptions import FeatureNotAvailable, Forbidden, ValidationError
from shared.settings import get_settings
from shared.utils.ids import uuid7

CHANNEL_SPECS: dict[str, dict[str, Any]] = {
    "whatsapp": {
        "settings": {"business_phone", "business_name"},
        "credentials": {"phone_number_id", "access_token", "app_secret", "verify_token"},
    },
    "email": {
        "settings": {"provider", "from_address", "from_name"},
        "credentials": {"api_key"},
    },
    "sms": {
        "settings": {"provider", "sender_id"},
        "credentials": {"api_token"},
    },
    "voice": {
        "settings": {"provider", "from_number"},
        "credentials": {"account_sid", "auth_token"},
    },
    "web_chat": {
        "settings": {"allowed_origins", "brand_name"},
        "credentials": set(),
    },
}

INTEGRATION_SPECS: dict[str, dict[str, Any]] = {
    "razorpay": {
        "settings": {"requested_mode", "account_label"},
        "credentials": {"key_id", "key_secret", "webhook_secret"},
    },
    "google_calendar": {
        "settings": {"calendar_id", "account_label"},
        "credentials": {"client_id", "client_secret", "refresh_token"},
    },
}


def get_encryptor() -> Any:
    from infrastructure.auth.encryption import EnvelopeEncryptor

    master_key = get_settings().encryption_master_key
    if not master_key:
        raise FeatureNotAvailable(
            "Secret storage is unavailable until ENCRYPTION_MASTER_KEY is configured."
        )
    return EnvelopeEncryptor(master_key)


def _assert_global_configuration(principal: Any, permission: str) -> None:
    if permission not in principal.permissions:
        raise Forbidden(
            "You do not have permission to configure integrations.",
            details={"required_permission": permission},
        )
    if principal.scope is not Scope.GLOBAL:
        raise Forbidden("Integration configuration requires global tenant scope.")


def _validate_map(
    provider: str,
    values: dict[str, Any],
    *,
    allowed: set[str],
    kind: str,
) -> dict[str, Any]:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValidationError(
            f"Unsupported {provider} {kind} fields.", details={"unsupported_fields": unknown}
        )
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        if value in (None, ""):
            raise ValidationError(f"Configuration field '{key}' may not be empty.")
        cleaned[key] = value
    return cleaned


def _channel_runtime_ready(channel: str) -> bool:
    from application.crm.inbox import channel_ready

    return channel_ready(channel)


def _integration_runtime_ready(provider: str) -> bool:
    cfg = get_settings()
    if provider == "razorpay":
        from application.payments.registry import get_razorpay_adapter

        return bool(cfg.features.payments_enabled and get_razorpay_adapter().is_configured())
    return bool(
        cfg.features.calendar_sync_enabled and cfg.google_client_id and cfg.google_client_secret
    )


def _activation_issues(provider: str, *, channel: bool, has_credentials: bool) -> list[str]:
    issues: list[str] = []
    if not has_credentials and provider != "web_chat":
        issues.append("credentials have not been recorded")
    if channel:
        runtime_ready = _channel_runtime_ready(provider)
        if not runtime_ready:
            issues.append("runtime feature flag and deployed provider credentials are not active")
            issues.extend(
                {
                    "whatsapp": ["BSP business verification and template approval are external"],
                    "email": ["sending-domain DNS verification is external"],
                    "sms": ["provider contracting and India DLT registration are external"],
                    "voice": ["legal disclosure and recording-consent approval are external"],
                    "web_chat": [],
                }[provider]
            )
    else:
        runtime_ready = _integration_runtime_ready(provider)
        if not runtime_ready:
            issues.append("runtime feature flag and deployed provider credentials are not active")
            issues.append(
                "Razorpay commercial approval is external"
                if provider == "razorpay"
                else "Google OAuth application verification is external"
            )
    return issues


def _serialize_channel(row: Any) -> dict[str, Any]:
    has_credentials = bool(row.encrypted_credentials)
    credential_requirement_met = has_credentials or (
        row.channel_type == "email" and dict(row.settings or {}).get("provider") == "ses"
    )
    issues = _activation_issues(
        row.channel_type,
        channel=True,
        has_credentials=credential_requirement_met,
    )
    return {
        "id": str(row.id),
        "kind": "channel",
        "provider": row.channel_type,
        "identifier": row.identifier,
        "display_name": row.display_name,
        "settings": {k: v for k, v in dict(row.settings or {}).items() if not k.startswith("_")},
        "credentials_present": has_credentials,
        "credential_fields": list(dict(row.settings or {}).get("_credential_fields", [])),
        "ready": not issues,
        "status": "ready" if not issues else "pending_activation",
        "activation_issues": issues,
        "version": row.version,
    }


def _serialize_integration(row: Any) -> dict[str, Any]:
    has_credentials = bool(row.encrypted_config)
    issues = _activation_issues(row.provider, channel=False, has_credentials=has_credentials)
    return {
        "id": str(row.id),
        "kind": "integration",
        "provider": row.provider,
        "identifier": row.name,
        "display_name": row.name,
        "settings": {
            k: v for k, v in dict(row.health_detail or {}).items() if not k.startswith("_")
        },
        "credentials_present": has_credentials,
        "credential_fields": list(dict(row.health_detail or {}).get("_credential_fields", [])),
        "ready": not issues,
        "status": "ready" if not issues else "pending_activation",
        "activation_issues": issues,
        "version": row.version,
    }


async def list_configurations(principal: Any) -> dict[str, Any]:
    if not ({"integration:read", "channel:read"} & set(principal.permissions)):
        raise Forbidden("You do not have permission to read integration configuration.")
    from sqlalchemy import select

    from infrastructure.database.models.communications import Channel
    from infrastructure.database.models.operational import IntegrationConnection
    from infrastructure.database.session import tenant_session

    async with tenant_session(principal.tenant_id) as session:
        channels = list(
            (
                await session.execute(
                    select(Channel)
                    .where(Channel.deleted_at.is_(None))
                    .order_by(Channel.channel_type, Channel.identifier)
                )
            )
            .scalars()
            .all()
        )
        integrations = list(
            (
                await session.execute(
                    select(IntegrationConnection).order_by(
                        IntegrationConnection.provider, IntegrationConnection.name
                    )
                )
            )
            .scalars()
            .all()
        )
    configured = [_serialize_channel(row) for row in channels] + [
        _serialize_integration(row) for row in integrations
    ]
    configured_providers = {str(row["provider"]) for row in configured}
    for provider in [*CHANNEL_SPECS, *INTEGRATION_SPECS]:
        if provider in configured_providers:
            continue
        is_channel = provider in CHANNEL_SPECS
        configured.append(
            {
                "id": None,
                "kind": "channel" if is_channel else "integration",
                "provider": provider,
                "identifier": "default",
                "display_name": "",
                "settings": {},
                "credentials_present": False,
                "credential_fields": [],
                "ready": False,
                "status": "not_configured",
                "activation_issues": _activation_issues(
                    provider, channel=is_channel, has_credentials=False
                ),
                "version": 0,
            }
        )
    return {"configurations": configured, "live_activation_claimed": False}


async def configure_channel(
    principal: Any, channel_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    _assert_global_configuration(principal, "channel:configure")
    spec = CHANNEL_SPECS.get(channel_type)
    if spec is None:
        raise ValidationError("Unknown channel provider.")
    return await _configure(principal, channel_type, payload, spec, channel=True)


async def configure_integration(
    principal: Any, provider: str, payload: dict[str, Any]
) -> dict[str, Any]:
    _assert_global_configuration(principal, "integration:configure")
    spec = INTEGRATION_SPECS.get(provider)
    if spec is None:
        raise ValidationError("Unknown integration provider.")
    return await _configure(principal, provider, payload, spec, channel=False)


async def _configure(
    principal: Any,
    provider: str,
    payload: dict[str, Any],
    spec: dict[str, Any],
    *,
    channel: bool,
) -> dict[str, Any]:
    from sqlalchemy import select, text

    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.communications import Channel
    from infrastructure.database.models.operational import IntegrationConnection
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
    from shared.utils.timeutil import utcnow

    identifier = str(payload.get("identifier") or "default").strip()
    display_name = str(payload.get("display_name") or "").strip()
    settings = _validate_map(
        provider,
        dict(payload.get("settings") or {}),
        allowed=set(spec["settings"]),
        kind="settings",
    )
    supplied_credentials = _validate_map(
        provider,
        dict(payload.get("credentials") or {}),
        allowed=set(spec["credentials"]),
        kind="credential",
    )
    if provider == "email" and settings.get("provider") not in {"ses", "sendgrid"}:
        raise ValidationError("Email provider must be 'ses' or 'sendgrid'.")
    if provider == "razorpay" and settings.get("requested_mode", "sandbox") not in {
        "sandbox",
        "live",
    }:
        raise ValidationError("Razorpay requested_mode must be sandbox or live.")

    encryptor = get_encryptor() if spec["credentials"] else None
    model = Channel if channel else IntegrationConnection
    identity = (
        (Channel.channel_type == provider) & (Channel.identifier == identifier)
        if channel
        else (IntegrationConnection.provider == provider)
        & (IntegrationConnection.name == identifier)
    )
    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        await uow.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"provider-config:{principal.tenant_id}:{provider}:{identifier}"},
        )
        row_result = await uow.session.execute(select(model).where(identity).with_for_update())
        row: Any = row_result.scalar_one_or_none()
        existing_credentials: dict[str, Any] = {}
        encrypted = (row.encrypted_credentials if channel and row is not None else None) or (
            row.encrypted_config if not channel and row is not None else None
        )
        if encrypted and encryptor:
            existing_credentials = json.loads(
                encryptor.decrypt_str(encrypted, tenant_id=str(principal.tenant_id))
            )
        credentials = {**existing_credentials, **supplied_credentials}
        missing = sorted(set(spec["credentials"]) - set(credentials))
        if missing and provider not in {"email", "web_chat"}:
            raise ValidationError(
                "Required provider credentials are missing.", details={"missing_fields": missing}
            )
        if (
            provider == "email"
            and settings.get("provider") == "sendgrid"
            and "api_key" not in credentials
        ):
            raise ValidationError(
                "SendGrid requires an API key.", details={"missing_fields": ["api_key"]}
            )
        encrypted_value = (
            encryptor.encrypt(
                json.dumps(credentials, sort_keys=True, separators=(",", ":")),
                tenant_id=str(principal.tenant_id),
            )
            if credentials and encryptor
            else None
        )
        credential_fields = sorted(credentials)
        public_settings = {**settings, "_credential_fields": credential_fields}
        is_new = row is None
        unchanged = False
        if row is not None:
            old_settings = dict(row.settings if channel else row.health_detail or {})
            old_public = {k: v for k, v in old_settings.items() if not k.startswith("_")}
            unchanged = (
                old_public == settings
                and set(old_settings.get("_credential_fields", [])) == set(credential_fields)
                and existing_credentials == credentials
                and (row.display_name == display_name if channel else True)
            )
        if unchanged:
            serialized = _serialize_channel(row) if channel else _serialize_integration(row)
            return {**serialized, "duplicate": True}

        if row is None:
            if channel:
                row = Channel(
                    id=uuid7(),
                    tenant_id=principal.tenant_id,
                    channel_type=provider,
                    identifier=identifier,
                    version=1,
                )
            else:
                row = IntegrationConnection(
                    id=uuid7(),
                    tenant_id=principal.tenant_id,
                    provider=provider,
                    name=identifier,
                    version=1,
                )
            uow.session.add(row)
        else:
            row.version += 1

        credential_requirement_met = bool(credentials) or (
            channel and provider == "email" and settings.get("provider") == "ses"
        )
        issues = _activation_issues(
            provider,
            channel=channel,
            has_credentials=credential_requirement_met,
        )
        if channel:
            row.display_name = display_name
            row.settings = public_settings
            row.encrypted_credentials = encrypted_value or row.encrypted_credentials
            row.is_active = not issues
            row.health_status = "healthy" if not issues else "pending_activation"
            row.health_detail = {"activation_issues": issues}
        else:
            row.health_detail = public_settings
            row.encrypted_config = encrypted_value or row.encrypted_config
            row.status = "connected" if not issues else "pending_activation"
            row.connected_at = utcnow() if not issues else None
        AuditRecorder(uow.session).record(
            action="config.updated",
            resource_type="channel" if channel else "integration",
            resource_id=row.id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            new_values={
                "provider": provider,
                "credential_fields": credential_fields,
                "status": "ready" if not issues else "pending_activation",
            },
        )
        if supplied_credentials:
            AuditRecorder(uow.session).record(
                action="provider.configured",
                resource_type="channel" if channel else "integration",
                resource_id=row.id,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                new_values={"provider": provider, "credential_fields": credential_fields},
            )
        uow.collect(
            DomainEvent(
                event_type=INTEGRATION_CONFIGURED if is_new else INTEGRATION_UPDATED,
                tenant_id=principal.tenant_id,
                resource_type="channel" if channel else "integration",
                resource_id=row.id,
                actor_id=principal.user_id,
                payload={
                    "provider": provider,
                    "status": "ready" if not issues else "pending_activation",
                },
            )
        )
    serialized = _serialize_channel(row) if channel else _serialize_integration(row)
    return {**serialized, "duplicate": False}
