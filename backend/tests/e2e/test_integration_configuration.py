"""Encrypted provider configuration with audit/outbox and forced RLS."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from application.integrations.service import (
    configure_channel,
    configure_integration,
    list_configurations,
)
from domain.auth.permissions import Scope
from infrastructure.auth.encryption import EnvelopeEncryptor
from infrastructure.database.models.audit import AuditLog, EventOutbox
from infrastructure.database.models.communications import Channel
from infrastructure.database.models.operational import IntegrationConnection
from infrastructure.database.session import tenant_session
from shared.exceptions import Forbidden
from shared.utils.ids import uuid7


def _principal(tenant_id: Any, *, scope: Scope = Scope.GLOBAL) -> Any:
    return SimpleNamespace(
        tenant_id=tenant_id,
        user_id=uuid7(),
        permissions=frozenset(
            {
                "channel:read",
                "channel:configure",
                "integration:read",
                "integration:configure",
            }
        ),
        scope=scope,
    )


def _whatsapp(identifier: str = "primary") -> dict[str, Any]:
    return {
        "identifier": identifier,
        "display_name": "Primary WhatsApp",
        "settings": {"business_phone": "+919876543210", "business_name": "Acme"},
        "credentials": {
            "phone_number_id": "123456",
            "access_token": "wa-access-secret",
            "app_secret": "wa-app-secret",
            "verify_token": "wa-verify-secret",
        },
    }


@pytest.mark.postgres
async def test_channel_secrets_are_encrypted_idempotent_and_never_returned(
    wired_engine: Any, seeded_tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_a, tenant_b = seeded_tenants
    encryptor = EnvelopeEncryptor("integration-test-master-key-material-32-bytes")
    monkeypatch.setattr("application.integrations.service.get_encryptor", lambda: encryptor)
    principal = _principal(tenant_a)
    identifier = f"primary-{uuid4().hex}"
    payload = _whatsapp(identifier)

    first = await configure_channel(principal, "whatsapp", payload)
    duplicate = await configure_channel(principal, "whatsapp", payload)
    assert first["duplicate"] is False and duplicate["duplicate"] is True
    assert first["ready"] is False and first["status"] == "pending_activation"
    assert first["credentials_present"] is True
    assert set(first["credential_fields"]) == {
        "phone_number_id",
        "access_token",
        "app_secret",
        "verify_token",
    }
    serialized = repr(first)
    assert "wa-access-secret" not in serialized
    assert first["activation_issues"]

    async with tenant_session(tenant_a) as session:
        row = (
            await session.execute(
                select(Channel).where(
                    Channel.channel_type == "whatsapp", Channel.identifier == identifier
                )
            )
        ).scalar_one()
        assert row.encrypted_credentials is not None
        assert "wa-access-secret" not in row.encrypted_credentials
        decrypted = encryptor.decrypt_str(row.encrypted_credentials, tenant_id=str(tenant_a))
        assert "wa-access-secret" in decrypted
        audits = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.resource_id == row.id)
        )
        outbox = await session.scalar(
            select(func.count()).select_from(EventOutbox).where(EventOutbox.resource_id == row.id)
        )
        assert audits == 2 and outbox == 1
    listed_a = await list_configurations(principal)
    assert any(
        item["provider"] == "whatsapp" and item["identifier"] == identifier
        for item in listed_a["configurations"]
    )
    listed_b = await list_configurations(_principal(tenant_b))
    assert not any(
        item["provider"] == "whatsapp" and item["identifier"] == identifier
        for item in listed_b["configurations"]
    )


@pytest.mark.postgres
async def test_integration_configuration_is_pending_and_tenant_isolated(
    wired_engine: Any, seeded_tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_a, tenant_b = seeded_tenants
    encryptor = EnvelopeEncryptor("integration-test-master-key-material-32-bytes")
    monkeypatch.setattr("application.integrations.service.get_encryptor", lambda: encryptor)
    identifier = f"razorpay-{uuid4().hex}"
    result = await configure_integration(
        _principal(tenant_a),
        "razorpay",
        {
            "identifier": identifier,
            "display_name": "Razorpay",
            "settings": {"requested_mode": "live", "account_label": "Acme"},
            "credentials": {
                "key_id": "rzp_live_id",
                "key_secret": "rzp_live_secret",
                "webhook_secret": "rzp_webhook_secret",
            },
        },
    )
    assert result["ready"] is False
    assert result["status"] == "pending_activation"
    assert result["activation_issues"]
    assert result["settings"]["requested_mode"] == "live"
    assert "rzp_live_secret" not in repr(result)
    async with tenant_session(tenant_b) as session:
        assert await session.scalar(select(func.count()).select_from(IntegrationConnection)) == 0


@pytest.mark.postgres
async def test_configuration_requires_global_scope_and_rolls_back_with_audit(
    wired_engine: Any, seeded_tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_a, _ = seeded_tenants
    encryptor = EnvelopeEncryptor("integration-test-master-key-material-32-bytes")
    monkeypatch.setattr("application.integrations.service.get_encryptor", lambda: encryptor)
    with pytest.raises(Forbidden):
        await configure_channel(
            _principal(tenant_a, scope=Scope.SELF), "whatsapp", _whatsapp("denied")
        )

    def fail_audit(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("audit partition unavailable")

    monkeypatch.setattr("application.audit.recorder.AuditRecorder.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit partition"):
        await configure_channel(_principal(tenant_a), "whatsapp", _whatsapp("rollback"))
    async with tenant_session(tenant_a) as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Channel).where(Channel.identifier == "rollback")
            )
            == 0
        )
