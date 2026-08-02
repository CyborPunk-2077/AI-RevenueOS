from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from application.workflows.triggers import handle_outbound_webhook
from infrastructure.auth.encryption import EnvelopeEncryptor
from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.webhook import _deliver_once
from infrastructure.database.models.audit import AuditLog, EventOutbox
from infrastructure.database.models.workflows import (
    OutboundWebhookConfig,
    OutboundWebhookDelivery,
)
from infrastructure.database.session import platform_session, tenant_session
from infrastructure.integrations.webhook import WebhookResult


def _context(tenant_id: Any) -> TaskContext:
    return TaskContext(tenant_id, "webhook-test", None, "system")


async def _clean_webhooks(*tenant_ids: Any) -> None:
    for tenant_id in tenant_ids:
        async with tenant_session(tenant_id) as session:
            await session.execute(delete(OutboundWebhookDelivery))
            await session.execute(delete(OutboundWebhookConfig))


async def _config(tenant_id: Any, *, master_key: str, suffix: str) -> Any:
    secret = EnvelopeEncryptor(master_key).encrypt(f"secret-{suffix}", tenant_id=str(tenant_id))
    async with tenant_session(tenant_id) as session:
        config = OutboundWebhookConfig(
            tenant_id=tenant_id,
            name=f"Endpoint {suffix}",
            url="https://example.com/webhook",
            event_types=["contact.created"],
            signing_secret_encrypted=secret,
            is_active=True,
            failure_count=0,
        )
        session.add(config)
        await session.flush()
        return config.id


@pytest.mark.postgres
async def test_public_events_queue_once_and_remain_tenant_isolated(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    await _clean_webhooks(tenant_a, tenant_b)
    master_key = "webhook-test-master-key-that-is-long-enough"
    config_a = await _config(tenant_a, master_key=master_key, suffix="a")
    await _config(tenant_b, master_key=master_key, suffix="b")
    event_id = uuid4()
    payload = {
        "event_id": str(event_id),
        "event_type": "contact.created",
        "tenant_id": str(tenant_a),
        "data": {"contact_id": str(uuid4())},
    }

    await handle_outbound_webhook(payload)
    await handle_outbound_webhook(payload)
    await handle_outbound_webhook({**payload, "event_type": "consent.granted"})

    async with tenant_session(tenant_a) as session:
        deliveries = list((await session.execute(select(OutboundWebhookDelivery))).scalars())
        assert len(deliveries) == 1
        assert deliveries[0].config_id == config_a
        assert deliveries[0].payload == payload
    async with tenant_session(tenant_b) as session:
        count = await session.scalar(select(func.count()).select_from(OutboundWebhookDelivery))
        assert count == 0


@pytest.mark.postgres
async def test_delivery_decrypts_secret_retries_and_is_durable_duplicate(
    wired_engine: Any,
    seeded_tenants: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a, _ = seeded_tenants
    await _clean_webhooks(tenant_a)
    master_key = "webhook-test-master-key-that-is-long-enough"
    config_id = await _config(tenant_a, master_key=master_key, suffix="delivery")
    event_id = uuid4()
    await handle_outbound_webhook(
        {
            "event_id": str(event_id),
            "event_type": "contact.created",
            "tenant_id": str(tenant_a),
            "data": {"contact_id": str(uuid4())},
        }
    )
    async with tenant_session(tenant_a) as session:
        delivery = (
            await session.execute(
                select(OutboundWebhookDelivery).where(
                    OutboundWebhookDelivery.config_id == config_id
                )
            )
        ).scalar_one()
        delivery_id = delivery.id

    import shared.settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: SimpleNamespace(encryption_master_key=master_key),
    )
    calls: list[dict[str, Any]] = []

    async def retrying_sender(**kwargs: Any) -> WebhookResult:
        calls.append(kwargs)
        return WebhookResult(False, False, 503, "temporarily unavailable")

    first = await _deliver_once(_context(tenant_a), str(delivery_id), sender=retrying_sender)
    assert first == {"delivered": False, "attempt": 1, "terminal": False, "status_code": 503}
    async with tenant_session(tenant_a) as session:
        row = await session.get(OutboundWebhookDelivery, delivery_id)
        assert row is not None
        assert row.status == "pending"
        assert row.next_attempt_at is not None
        assert row.attempts == 1

    async def successful_sender(**kwargs: Any) -> WebhookResult:
        calls.append(kwargs)
        return WebhookResult(True, False, 204)

    second = await _deliver_once(_context(tenant_a), str(delivery_id), sender=successful_sender)
    duplicate = await _deliver_once(_context(tenant_a), str(delivery_id), sender=successful_sender)

    assert second["delivered"] is True
    assert duplicate == {"delivered": True, "duplicate": True}
    assert len(calls) == 2
    assert calls[0]["secret"] == "secret-delivery"
    async with tenant_session(tenant_a) as session:
        row = await session.get(OutboundWebhookDelivery, delivery_id)
        config = await session.get(OutboundWebhookConfig, config_id)
        assert row is not None and config is not None
        assert row.status == "delivered"
        assert row.attempts == 2
        assert row.delivered_at is not None
        assert row.next_attempt_at is None
        assert config.failure_count == 0


@pytest.mark.postgres
async def test_terminal_response_and_platform_sweep_policy(
    wired_engine: Any,
    seeded_tenants: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a, tenant_b = seeded_tenants
    await _clean_webhooks(tenant_a, tenant_b)
    master_key = "webhook-test-master-key-that-is-long-enough"
    terminal_config_id = await _config(tenant_a, master_key=master_key, suffix="terminal")
    await _config(tenant_b, master_key=master_key, suffix="other")
    ids: list[Any] = []
    for tenant_id in (tenant_a, tenant_b):
        event_id = uuid4()
        await handle_outbound_webhook(
            {
                "event_id": str(event_id),
                "event_type": "contact.created",
                "tenant_id": str(tenant_id),
                "data": {},
            }
        )
        async with tenant_session(tenant_id) as session:
            ids.append(
                await session.scalar(
                    select(OutboundWebhookDelivery.id).where(
                        OutboundWebhookDelivery.event_id == event_id
                    )
                )
            )

    async with platform_session("webhook_delivery_sweep") as session:
        visible = set((await session.scalars(select(OutboundWebhookDelivery.id))).all())
    assert visible == set(ids)

    import shared.settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: SimpleNamespace(encryption_master_key=master_key),
    )
    async with tenant_session(tenant_a) as session:
        config = await session.get(OutboundWebhookConfig, terminal_config_id)
        assert config is not None
        config.failure_count = 9

    async def terminal_sender(**_kwargs: Any) -> WebhookResult:
        return WebhookResult(False, True, 422, "invalid payload")

    result = await _deliver_once(_context(tenant_a), str(ids[0]), sender=terminal_sender)
    assert result["terminal"] is True
    async with tenant_session(tenant_a) as session:
        row = await session.get(OutboundWebhookDelivery, ids[0])
        config = await session.get(OutboundWebhookConfig, terminal_config_id)
        assert row is not None
        assert config is not None
        assert row.status == "failed"
        assert row.next_attempt_at is None
        assert config.is_active is False
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "config.updated",
                AuditLog.resource_id == terminal_config_id,
            )
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(EventOutbox)
            .where(
                EventOutbox.event_type == "system.integration_disconnected",
                EventOutbox.resource_id == terminal_config_id,
            )
        )
        assert audit_count == 1
        assert outbox_count == 1
