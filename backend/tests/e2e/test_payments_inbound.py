"""Verified Razorpay events are durable, atomic and tenant-derived."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from shared.utils.ids import uuid7

pytestmark = pytest.mark.postgres


async def _seed_payment(
    session_factory: Any,
    tenant_id: Any,
    *,
    status: str = "attempted",
    amount_minor: int = 250_000,
) -> tuple[Any, str]:
    from infrastructure.database.models.payments import Payment
    from infrastructure.database.session import bind_tenant

    order_id = f"order_{uuid7()}"
    async with session_factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        payment = Payment(
            tenant_id=tenant_id,
            external_order_id=order_id,
            amount_minor=amount_minor,
            currency="INR",
            status=status,
            method="unknown",
            provider="razorpay",
            provider_payload={},
            reconciliation_status="pending",
        )
        session.add(payment)
        await session.flush()
        return payment.id, order_id


def _captured_event(order_id: str, *, event_id: str | None = None) -> dict[str, Any]:
    return {
        "event": "payment.captured",
        "external_event_id": event_id or f"evt_{uuid7()}",
        "status": "captured",
        "external_payment_id": f"pay_{uuid7()}",
        "external_order_id": order_id,
        "amount_minor": 250_000,
        "currency": "INR",
        "method": "upi",
        "entity": {"id": "provider-id", "card": {"card_number": "4111111111111111"}},
    }


async def test_captured_event_commits_transition_audit_outbox_and_durable_duplicate_noop(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.payments.inbound import accept_verified_razorpay_event
    from infrastructure.caching.redis import get_redis
    from infrastructure.database.session import bind_tenant

    tenant_id, other_tenant = seeded_tenants
    payment_id, order_id = await _seed_payment(session_factory, tenant_id)
    parsed = _captured_event(order_id)

    receipt = await accept_verified_razorpay_event(
        parsed, correlation_id="payments-e2e", session_factory=session_factory
    )
    await get_redis().flushall()
    duplicate = await accept_verified_razorpay_event(
        parsed, correlation_id="payments-e2e-replay", session_factory=session_factory
    )

    assert receipt.state == "applied"
    assert receipt.processed is True
    assert receipt.payment_id == str(payment_id)
    assert duplicate.duplicate is True
    assert duplicate.state == "duplicate"

    async with session_factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        payment = (
            await session.execute(
                text(
                    "SELECT status, method, external_payment_id, reconciliation_status "
                    "FROM app.payments WHERE id = :id"
                ),
                {"id": payment_id},
            )
        ).one()
        counts = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM app.provider_webhook_events "
                    " WHERE external_event_id = :event_id), "
                    "(SELECT count(*) FROM app.payment_transitions WHERE payment_id = :id), "
                    "(SELECT count(*) FROM audit.audit_logs "
                    " WHERE resource_id = :id AND action = 'payment.captured'), "
                    "(SELECT count(*) FROM audit.event_outbox "
                    " WHERE resource_id = :id AND tenant_id = :tenant_id "
                    " AND event_type = 'payment.captured')"
                ),
                {
                    "id": payment_id,
                    "event_id": parsed["external_event_id"],
                    "tenant_id": tenant_id,
                },
            )
        ).one()
        event = (
            await session.execute(
                text(
                    "SELECT signature_verified, attempts, processed_at, payload "
                    "FROM app.provider_webhook_events WHERE external_event_id = :event_id"
                ),
                {"event_id": parsed["external_event_id"]},
            )
        ).one()

    assert tuple(payment)[:2] == ("captured", "upi")
    assert payment.external_payment_id == parsed["external_payment_id"]
    assert payment.reconciliation_status == "matched"
    assert tuple(counts) == (1, 1, 1, 1)
    assert event.signature_verified is True
    assert event.attempts == 1
    assert event.processed_at is not None
    assert "4111111111111111" not in json.dumps(event.payload)

    async with session_factory() as session, session.begin():
        await bind_tenant(session, other_tenant)
        hidden = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM app.payments WHERE id = :id), "
                    "(SELECT count(*) FROM app.provider_webhook_events "
                    " WHERE external_event_id = :event_id), "
                    "(SELECT count(*) FROM audit.audit_logs WHERE resource_id = :id)"
                ),
                {"id": payment_id, "event_id": parsed["external_event_id"]},
            )
        ).one()
    assert tuple(hidden) == (0, 0, 0)


async def test_unknown_mapping_stays_durably_pending_without_fabricating_a_tenant(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.payments.inbound import accept_verified_razorpay_event
    from infrastructure.database.session import bind_tenant

    tenant_id, _ = seeded_tenants
    missing_order_id = f"missing_{uuid7()}"
    parsed = _captured_event(missing_order_id)
    receipt = await accept_verified_razorpay_event(parsed, session_factory=session_factory)

    assert receipt.accepted is True
    assert receipt.processed is False
    assert receipt.state == "pending_mapping"
    assert receipt.detail == "payment mapping not found"
    async with session_factory() as session, session.begin():
        row = (
            await session.execute(
                text(
                    "SELECT tenant_id, signature_verified, processed_at, attempts, last_error "
                    "FROM app.provider_webhook_events WHERE external_event_id = :event_id"
                ),
                {"event_id": parsed["external_event_id"]},
            )
        ).one()
    assert row.tenant_id is None
    assert row.signature_verified is True
    assert row.processed_at is None
    assert row.attempts == 1
    assert row.last_error == "payment mapping not found"

    # A later authoritative order mapping can recover the same durable receipt;
    # the provider-controlled payload never supplies the tenant.
    async with session_factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        from infrastructure.database.models.payments import Payment

        session.add(
            Payment(
                tenant_id=tenant_id,
                external_order_id=missing_order_id,
                amount_minor=250_000,
                currency="INR",
                status="attempted",
                method="unknown",
                provider="razorpay",
                provider_payload={},
                reconciliation_status="pending",
            )
        )
    recovered = await accept_verified_razorpay_event(parsed, session_factory=session_factory)
    assert recovered.state == "applied"
    async with session_factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        rebound = (
            await session.execute(
                text(
                    "SELECT tenant_id, processed_at, attempts, last_error "
                    "FROM app.provider_webhook_events WHERE external_event_id = :event_id"
                ),
                {"event_id": parsed["external_event_id"]},
            )
        ).one()
    assert rebound.tenant_id == tenant_id
    assert rebound.processed_at is not None
    assert rebound.attempts == 2
    assert rebound.last_error is None


async def test_out_of_order_event_is_durably_ignored_without_business_side_effects(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.payments.inbound import accept_verified_razorpay_event
    from infrastructure.database.session import bind_tenant

    tenant_id, _ = seeded_tenants
    payment_id, order_id = await _seed_payment(session_factory, tenant_id, status="created")
    parsed = _captured_event(order_id)
    receipt = await accept_verified_razorpay_event(parsed, session_factory=session_factory)

    assert receipt.state == "ignored"
    assert receipt.processed is True
    assert "out-of-order" in (receipt.detail or "")
    async with session_factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        state = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM app.payments WHERE id = :id), "
                    "(SELECT count(*) FROM app.payment_transitions WHERE payment_id = :id), "
                    "(SELECT count(*) FROM audit.audit_logs WHERE resource_id = :id), "
                    "(SELECT count(*) FROM audit.event_outbox WHERE resource_id = :id)"
                ),
                {"id": payment_id},
            )
        ).one()
    assert tuple(state) == ("created", 0, 0, 0)


async def test_audit_failure_rolls_back_receipt_payment_transition_and_outbox(
    wired_engine: Any,
    seeded_tenants: Any,
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from application.payments.inbound import accept_verified_razorpay_event
    from infrastructure.database.session import bind_tenant

    tenant_id, _ = seeded_tenants
    payment_id, order_id = await _seed_payment(session_factory, tenant_id)
    parsed = _captured_event(order_id)

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("application.payments.inbound.AuditRecorder.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await accept_verified_razorpay_event(parsed, session_factory=session_factory)

    async with session_factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        state = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM app.payments WHERE id = :id), "
                    "(SELECT count(*) FROM app.provider_webhook_events "
                    " WHERE external_event_id = :event_id), "
                    "(SELECT count(*) FROM app.payment_transitions WHERE payment_id = :id), "
                    "(SELECT count(*) FROM audit.event_outbox WHERE resource_id = :id)"
                ),
                {"id": payment_id, "event_id": parsed["external_event_id"]},
            )
        ).one()
    assert tuple(state) == ("attempted", 0, 0, 0)


async def test_forged_signature_is_rejected_before_any_durable_receipt(
    wired_engine: Any, session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.app.factory import create_app
    from api.app.settings import Settings
    from infrastructure.integrations.razorpay import RazorpayAdapter

    secret = "webhook-secret-for-e2e"
    adapter = RazorpayAdapter(
        key_id="rzp_test_key",
        key_secret="rzp_test_secret",
        webhook_secret=secret,
        enabled=True,
    )
    monkeypatch.setattr("application.payments.registry.get_razorpay_adapter", lambda: adapter)
    event_id = f"evt_{uuid7()}"
    body = json.dumps({"id": event_id, "event": "payment.captured"}).encode()
    app = create_app(
        Settings(
            environment="local",
            trusted_hosts=["testserver"],
            cors_allowed_origins=["http://localhost:3000"],
            log_json=False,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        forged = await client.post(
            "/v1/webhooks/inbound/razorpay",
            content=body,
            headers={"x-razorpay-signature": "forged"},
        )
    assert forged.status_code == 403

    async with session_factory() as session, session.begin():
        receipt_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM app.provider_webhook_events "
                    "WHERE external_event_id = :event_id"
                ),
                {"event_id": event_id},
            )
        ).scalar_one()
    assert receipt_count == 0
