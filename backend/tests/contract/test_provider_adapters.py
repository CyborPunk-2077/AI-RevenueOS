"""Provider contract tests. Every adapter must fail closed without credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest

from application.ports import OutboundMessage
from infrastructure.integrations.email import EmailAdapter
from infrastructure.integrations.razorpay import RazorpayAdapter
from infrastructure.integrations.storage import (
    APPROVED_EXCEPTION_LIMIT,
    PUBLIC_UPLOAD_LIMIT,
    ClamAvScanner,
    S3Storage,
    archive_ratio_safe,
    assert_download_allowed,
    content_is_safe,
    object_key,
    sanitize_csv_cell,
    validate_upload_request,
    verify_magic_bytes,
)
from infrastructure.integrations.voice import VoiceAdapter, VoiceControls
from infrastructure.integrations.whatsapp import WhatsAppAdapter
from shared.exceptions import Forbidden, ValidationError

pytestmark = pytest.mark.contract

TENANT = uuid4()
APP_SECRET = "whatsapp-app-secret"
RZP_WEBHOOK_SECRET = "razorpay-webhook-secret"


def configured_whatsapp(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> WhatsAppAdapter:
    transport = httpx.MockTransport(handler) if handler else None
    return WhatsAppAdapter(
        phone_number_id="1234567890",
        access_token="token",
        app_secret=APP_SECRET,
        verify_token="verify-me",
        enabled=True,
        client=httpx.AsyncClient(transport=transport) if transport else None,
    )


class TestWhatsAppGating:
    def test_unconfigured_adapter_reports_false(self) -> None:
        adapter = WhatsAppAdapter(
            phone_number_id=None, access_token=None, app_secret=None, enabled=False
        )
        assert adapter.is_configured() is False

    def test_flag_off_with_credentials_is_still_unconfigured(self) -> None:
        adapter = WhatsAppAdapter(
            phone_number_id="1", access_token="t", app_secret="s", enabled=False
        )
        assert adapter.is_configured() is False

    def test_activation_status_names_the_missing_configuration(self) -> None:
        status = WhatsAppAdapter(
            phone_number_id=None, access_token=None, app_secret=None
        ).activation_status()
        assert status["configured"] is False
        assert "WHATSAPP_ACCESS_TOKEN" in status["missing_configuration"]
        assert "template" in status["activation_prerequisite"].lower()

    async def test_send_without_credentials_queues_rather_than_failing_hard(self) -> None:
        adapter = WhatsAppAdapter(phone_number_id=None, access_token=None, app_secret=None)
        result = await adapter.send(OutboundMessage(TENANT, "+919876543210", "whatsapp", body="hi"))
        assert result.ok is False
        assert result.queued is True
        assert result.error_code == "PROVIDER_NOT_CONFIGURED"


class TestWhatsAppWebhookSecurity:
    def test_valid_signature_accepted(self) -> None:
        adapter = configured_whatsapp()
        body = b'{"entry":[]}'
        signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert (
            adapter.verify_webhook(
                body=body, headers={"x-hub-signature-256": f"sha256={signature}"}
            )
            is True
        )

    def test_tampered_body_rejected(self) -> None:
        adapter = configured_whatsapp()
        signature = hmac.new(APP_SECRET.encode(), b'{"entry":[]}', hashlib.sha256).hexdigest()
        assert (
            adapter.verify_webhook(
                body=b'{"entry":[{"evil":1}]}',
                headers={"x-hub-signature-256": f"sha256={signature}"},
            )
            is False
        )

    def test_missing_or_malformed_header_rejected(self) -> None:
        adapter = configured_whatsapp()
        assert adapter.verify_webhook(body=b"{}", headers={}) is False
        assert adapter.verify_webhook(body=b"{}", headers={"x-hub-signature-256": "abc"}) is False

    def test_no_secret_means_no_verification_passes(self) -> None:
        adapter = WhatsAppAdapter(phone_number_id="1", access_token="t", app_secret=None)
        assert (
            adapter.verify_webhook(body=b"{}", headers={"x-hub-signature-256": "sha256=x"}) is False
        )

    def test_replay_window_is_five_minutes(self) -> None:
        now = time.time()
        assert WhatsAppAdapter.is_replay(int(now), now=now) is False
        assert WhatsAppAdapter.is_replay(int(now - 400), now=now) is True
        assert WhatsAppAdapter.is_replay("not-a-timestamp", now=now) is True

    def test_subscription_challenge_requires_the_verify_token(self) -> None:
        adapter = configured_whatsapp()
        assert adapter.verify_challenge(mode="subscribe", token="verify-me", challenge="42") == "42"
        assert adapter.verify_challenge(mode="subscribe", token="wrong", challenge="42") is None


class TestWhatsAppPayloadParsing:
    ADAPTER = configured_whatsapp()

    def test_inbound_text_message(self) -> None:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.1",
                                        "from": "919876543210",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "Hello"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = self.ADAPTER.parse_webhook(payload)
        assert events[0]["kind"] == "inbound_message"
        assert events[0]["from"] == "+919876543210"
        assert events[0]["content"] == "Hello"
        assert events[0]["external_id"] == "wamid.1"

    def test_delivery_status_update(self) -> None:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.1",
                                        "status": "delivered",
                                        "timestamp": "1700000000",
                                        "recipient_id": "919876543210",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = self.ADAPTER.parse_webhook(payload)
        assert events[0]["kind"] == "status_update"
        assert events[0]["status"] == "delivered"

    def test_failed_status_carries_the_error(self) -> None:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.2",
                                        "status": "failed",
                                        "recipient_id": "919876543210",
                                        "errors": [
                                            {"code": 131047, "title": "Re-engagement message"}
                                        ],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = self.ADAPTER.parse_webhook(payload)
        assert events[0]["status"] == "failed"
        assert events[0]["error"]["code"] == 131047

    def test_media_message_metadata(self) -> None:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.3",
                                        "from": "919876543210",
                                        "type": "document",
                                        "document": {
                                            "id": "media-1",
                                            "mime_type": "application/pdf",
                                            "filename": "pan.pdf",
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = self.ADAPTER.parse_webhook(payload)
        assert events[0]["content_type"] == "document"
        assert events[0]["media"]["mime_type"] == "application/pdf"

    def test_empty_payload_produces_no_events(self) -> None:
        assert self.ADAPTER.parse_webhook({}) == []

    @pytest.mark.parametrize(
        "text", ["STOP", "stop", " Unsubscribe ", "opt out", "CANCEL", "band karo"]
    )
    def test_opt_out_keywords_are_recognised(self, text: str) -> None:
        assert WhatsAppAdapter.is_opt_out(text) is True

    def test_ordinary_message_is_not_an_opt_out(self) -> None:
        assert WhatsAppAdapter.is_opt_out("Please stop by the office tomorrow") is False
        assert WhatsAppAdapter.is_opt_out(None) is False

    def test_template_payload_shape(self) -> None:
        payload = self.ADAPTER.build_payload(
            OutboundMessage(
                TENANT,
                "+919876543210",
                "whatsapp",
                template_name="site_visit_invite",
                template_variables={"1": "Asha", "_language": "en"},
            )
        )
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "site_visit_invite"
        assert payload["template"]["language"]["code"] == "en"
        assert payload["to"] == "919876543210"


class TestWhatsAppSendBehaviour:
    async def test_successful_send_returns_the_provider_message_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"messages": [{"id": "wamid.out.1"}]})

        adapter = configured_whatsapp(handler)
        result = await adapter.send(
            OutboundMessage(TENANT, "+919876543210", "whatsapp", body="hi", idempotency_key="k1")
        )
        assert result.ok is True and result.external_id == "wamid.out.1"

    async def test_client_error_is_not_queued_for_retry(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"error": {"code": 131_026, "message": "undeliverable"}}
            )

        result = await configured_whatsapp(handler).send(
            OutboundMessage(TENANT, "+919876543210", "whatsapp", body="hi")
        )
        assert result.ok is False and result.queued is False

    async def test_server_error_is_queued_for_retry(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": {"message": "upstream"}})

        result = await configured_whatsapp(handler).send(
            OutboundMessage(TENANT, "+919876543210", "whatsapp", body="hi")
        )
        assert result.ok is False and result.queued is True


class TestRazorpayAdapter:
    def _adapter(
        self, handler: Callable[[httpx.Request], httpx.Response] | None = None, **over: Any
    ) -> RazorpayAdapter:
        args: dict[str, Any] = {
            "key_id": "rzp_test_key",
            "key_secret": "secret",
            "webhook_secret": RZP_WEBHOOK_SECRET,
            "enabled": True,
        }
        args.update(over)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler)) if handler else None
        return RazorpayAdapter(client=client, **args)

    def test_unconfigured_without_credentials(self) -> None:
        assert (
            RazorpayAdapter(key_id=None, key_secret=None, webhook_secret=None).is_configured()
            is False
        )

    def test_activation_status_lists_missing_secrets(self) -> None:
        status = RazorpayAdapter(
            key_id=None, key_secret=None, webhook_secret=None
        ).activation_status()
        assert "RAZORPAY_KEY_SECRET" in status["missing_configuration"]

    async def test_order_without_credentials_queues_for_reconciliation(self) -> None:
        adapter = RazorpayAdapter(key_id=None, key_secret=None, webhook_secret=None)
        result = await adapter.create_order(
            tenant_id=TENANT,
            amount_minor=250_000,
            currency="INR",
            receipt="r1",
            notes={},
            idempotency_key="k",
        )
        assert result.ok is False and result.queued is True

    async def test_non_inr_currency_refused_before_any_call(self) -> None:
        result = await self._adapter().create_order(
            tenant_id=TENANT,
            amount_minor=100,
            currency="USD",
            receipt="r",
            notes={},
            idempotency_key="k",
        )
        assert result.error_code == "VALIDATION_ERROR"

    async def test_non_positive_amount_refused(self) -> None:
        result = await self._adapter().create_order(
            tenant_id=TENANT,
            amount_minor=0,
            currency="INR",
            receipt="r",
            notes={},
            idempotency_key="k",
        )
        assert result.error_code == "VALIDATION_ERROR"

    async def test_order_sends_the_server_derived_amount_and_idempotency_key(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"id": "order_1", "amount": 250_000, "currency": "INR"})

        result = await self._adapter(handler).create_order(
            tenant_id=TENANT,
            amount_minor=250_000,
            currency="INR",
            receipt="inv-1",
            notes={"invoice": "inv-1"},
            idempotency_key="idem-1",
        )
        assert result.ok is True and result.external_id == "order_1"
        assert captured["json"]["amount"] == 250_000
        assert captured["headers"]["x-razorpay-idempotency-key"] == "idem-1"
        assert captured["json"]["notes"]["tenant_id"] == str(TENANT)

    def test_webhook_signature_verification(self) -> None:
        adapter = self._adapter()
        body = b'{"event":"payment.captured"}'
        signature = hmac.new(RZP_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert adapter.verify_webhook_signature(body=body, signature=signature) is True
        assert adapter.verify_webhook_signature(body=body, signature="deadbeef") is False
        assert adapter.verify_webhook_signature(body=b"{}", signature=signature) is False

    def test_checkout_handback_signature(self) -> None:
        adapter = self._adapter()
        expected = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
        assert (
            adapter.verify_payment_signature(
                order_id="order_1", payment_id="pay_1", signature=expected
            )
            is True
        )
        assert (
            adapter.verify_payment_signature(
                order_id="order_1", payment_id="pay_1", signature="wrong"
            )
            is False
        )

    def test_webhook_parsing_maps_events_to_statuses(self) -> None:
        parsed = RazorpayAdapter.parse_webhook(
            {
                "id": "evt_1",
                "event": "payment.captured",
                "created_at": 1_700_000_000,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_1",
                            "order_id": "order_1",
                            "amount": 250_000,
                            "currency": "INR",
                            "method": "upi",
                        }
                    }
                },
            }
        )
        assert parsed["status"] == "captured"
        assert parsed["external_payment_id"] == "pay_1"
        assert parsed["amount_minor"] == 250_000
        assert parsed["external_event_id"] == "evt_1"

    def test_card_data_is_stripped_from_parsed_entities(self) -> None:
        parsed = RazorpayAdapter.parse_webhook(
            {
                "id": "evt_2",
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_2",
                            "amount": 100,
                            "card": {"card_number": "4111111111111111"},
                        }
                    }
                },
            }
        )
        assert "4111111111111111" not in json.dumps(parsed)


class TestEmailAdapterGate:
    def test_default_provider_is_none_and_unconfigured(self) -> None:
        adapter = EmailAdapter()
        assert adapter.provider == "none"
        assert adapter.is_configured() is False

    async def test_send_queues_with_the_activation_prerequisite(self) -> None:
        result = await EmailAdapter().send(
            OutboundMessage(TENANT, "asha@example.in", "email", body="hi")
        )
        assert result.queued is True
        assert "SPF/DKIM/DMARC" in result.raw["activation_prerequisite"]

    def test_activation_status_names_the_decision_gate(self) -> None:
        assert EmailAdapter().activation_status()["decision_gate"].startswith("Email and voice")

    def test_bounce_parsing_marks_hard_bounces(self) -> None:
        events = EmailAdapter().parse_webhook(
            {
                "Records": [
                    {
                        "eventType": "Bounce",
                        "bounce": {"bounceType": "Permanent"},
                        "mail": {"messageId": "m1", "destination": ["a@b.in"]},
                    }
                ]
            }
        )
        assert events[0]["status"] == "bounced"
        assert events[0]["hard_bounce"] is True

    def test_delivery_and_complaint_mapping(self) -> None:
        adapter = EmailAdapter()
        assert (
            adapter.parse_webhook([{"event": "delivered", "email": "a@b.in"}])[0]["status"]
            == "delivered"
        )
        assert (
            adapter.parse_webhook([{"event": "spamreport", "email": "a@b.in"}])[0]["status"]
            == "failed"
        )


class TestVoiceIsHardDisabled:
    def test_default_adapter_is_not_configured(self) -> None:
        assert VoiceAdapter().is_configured() is False

    def test_enabling_the_flag_alone_does_not_enable_voice(self) -> None:
        adapter = VoiceAdapter(provider="exotel", enabled=True)
        assert adapter.is_configured() is False
        assert adapter.activation_status()["outstanding_controls"]

    def test_every_control_must_be_signed_off(self) -> None:
        controls = VoiceControls(
            disclosure_copy_approved=True,
            recording_consent_flow_approved=True,
            escalation_path_defined=True,
            concurrency_limit_set=True,
            budget_limit_set=True,
            legal_signoff=True,
            provider_contracted=True,
        )
        assert controls.all_signed_off() is True
        assert (
            VoiceAdapter(provider="exotel", enabled=True, controls=controls).is_configured() is True
        )

    def test_one_missing_control_keeps_voice_disabled(self) -> None:
        controls = VoiceControls(
            disclosure_copy_approved=True,
            recording_consent_flow_approved=True,
            escalation_path_defined=True,
            concurrency_limit_set=True,
            budget_limit_set=True,
            legal_signoff=False,
            provider_contracted=True,
        )
        adapter = VoiceAdapter(provider="exotel", enabled=True, controls=controls)
        assert adapter.is_configured() is False
        assert adapter.activation_status()["outstanding_controls"] == ["legal_signoff"]

    async def test_placing_a_call_is_refused(self) -> None:
        result = await VoiceAdapter(provider="exotel", enabled=True).place_call(
            tenant_id=TENANT, payload={"to": "+919876543210"}
        )
        assert result.ok is False
        assert result.error_code == "FEATURE_NOT_AVAILABLE"


class TestFileSecurity:
    def test_placeholder_bucket_never_counts_as_configured(self) -> None:
        adapter = S3Storage(bucket="airevenueos-local-uploads", client=object())
        assert adapter.is_configured() is False
        assert adapter.activation_status()["configured"] is False

    def test_injected_client_and_real_bucket_complete_the_adapter_configuration(self) -> None:
        adapter = S3Storage(bucket="acme-private-uploads", client=object())
        assert adapter.is_configured() is True
        assert adapter.activation_status()["configured"] is True

    def test_object_keys_are_uuid_based_and_tenant_scoped(self) -> None:
        key = object_key(TENANT)
        assert str(TENANT) in key
        assert key.startswith("uploads/")

    def test_permitted_upload(self) -> None:
        assert (
            validate_upload_request(
                declared_mime="application/pdf", size_bytes=1_000, filename="quote.pdf"
            ).ok
            is True
        )

    def test_disallowed_mime_rejected(self) -> None:
        assert (
            validate_upload_request(
                declared_mime="application/x-msdownload", size_bytes=10, filename="a.exe"
            ).ok
            is False
        )

    @pytest.mark.parametrize("name", ["payload.exe", "script.sh", "macro.js", "installer.msi"])
    def test_executable_extensions_rejected(self, name: str) -> None:
        assert (
            validate_upload_request(
                declared_mime="application/pdf", size_bytes=10, filename=name
            ).ok
            is False
        )

    def test_double_extension_rejected(self) -> None:
        assert (
            validate_upload_request(
                declared_mime="application/pdf", size_bytes=10, filename="invoice.exe.pdf"
            ).ok
            is False
        )

    def test_public_upload_limit_is_lower(self) -> None:
        assert (
            validate_upload_request(
                declared_mime="application/pdf",
                size_bytes=PUBLIC_UPLOAD_LIMIT + 1,
                filename="a.pdf",
                is_public=True,
            ).ok
            is False
        )

    def test_approved_exception_raises_the_limit(self) -> None:
        size = APPROVED_EXCEPTION_LIMIT - 1
        assert (
            validate_upload_request(
                declared_mime="application/pdf", size_bytes=size, filename="a.pdf"
            ).ok
            is False
        )
        assert (
            validate_upload_request(
                declared_mime="application/pdf",
                size_bytes=size,
                filename="a.pdf",
                approved_exception=True,
            ).ok
            is True
        )

    def test_daily_allowance_is_enforced(self) -> None:
        assert (
            validate_upload_request(
                declared_mime="application/pdf",
                size_bytes=10 * 1024 * 1024,
                filename="a.pdf",
                user_daily_bytes=495 * 1024 * 1024,
            ).ok
            is False
        )

    def test_magic_bytes_must_match_the_declared_type(self) -> None:
        assert verify_magic_bytes("application/pdf", b"%PDF-1.7") is True
        assert verify_magic_bytes("application/pdf", b"MZ\x90\x00") is False
        assert verify_magic_bytes("image/png", b"\x89PNG\r\n\x1a\n") is True

    def test_unsafe_svg_and_pdf_javascript_rejected(self) -> None:
        assert content_is_safe("image/svg+xml", b"<svg onload=alert(1)>").ok is False
        assert content_is_safe("application/pdf", b"%PDF-1.7 /JavaScript (evil)").ok is False
        assert content_is_safe("application/pdf", b"%PDF-1.7 normal content").ok is True

    def test_archive_expansion_ratio_capped(self) -> None:
        assert archive_ratio_safe(1_000, 50_000) is True
        assert archive_ratio_safe(1_000, 200_000) is False
        assert archive_ratio_safe(0, 100) is False

    @pytest.mark.parametrize("cell", ["=1+1", "+1", "-1", "@SUM(A1)"])
    def test_csv_formula_injection_neutralised(self, cell: str) -> None:
        assert sanitize_csv_cell(cell).startswith("'")

    def test_ordinary_csv_cell_untouched(self) -> None:
        assert sanitize_csv_cell("Asha Kumar") == "Asha Kumar"

    def test_unscanned_file_cannot_be_downloaded(self) -> None:
        with pytest.raises(ValidationError):
            assert_download_allowed(
                scan_status="pending", file_tenant_id=TENANT, requester_tenant_id=TENANT
            )

    def test_quarantined_file_cannot_be_downloaded(self) -> None:
        with pytest.raises(ValidationError):
            assert_download_allowed(
                scan_status="quarantined", file_tenant_id=TENANT, requester_tenant_id=TENANT
            )

    def test_cross_tenant_download_is_forbidden(self) -> None:
        with pytest.raises(Forbidden):
            assert_download_allowed(
                scan_status="clean", file_tenant_id=TENANT, requester_tenant_id=uuid4()
            )

    def test_clean_same_tenant_download_is_allowed(self) -> None:
        assert_download_allowed(
            scan_status="clean", file_tenant_id=TENANT, requester_tenant_id=TENANT
        )

    async def test_scanner_without_configuration_leaves_the_file_unavailable(self) -> None:
        result = await ClamAvScanner(host=None).scan(bucket="b", key="k")
        assert result.ok is False and result.queued is True

    @pytest.mark.parametrize(
        ("response", "ok", "error_code"),
        [
            (b"stream: OK\0", True, None),
            (b"stream: Eicar-Test-Signature FOUND\0", False, "MALWARE_FOUND"),
        ],
    )
    async def test_clamd_instream_protocol(
        self, response: bytes, ok: bool, error_code: str | None
    ) -> None:
        import asyncio
        from io import BytesIO

        received = bytearray()

        async def handler(reader: Any, writer: Any) -> None:
            assert await reader.readuntil(b"\0") == b"zINSTREAM\0"
            while True:
                size = int.from_bytes(await reader.readexactly(4), "big")
                if size == 0:
                    break
                received.extend(await reader.readexactly(size))
            writer.write(response)
            await writer.drain()
            writer.close()

        class Body:
            def __init__(self) -> None:
                self._body = BytesIO(b"%PDF-1.7 test")

            def read(self, size: int) -> bytes:
                return self._body.read(size)

            def close(self) -> None:
                self._body.close()

        class S3:
            def get_object(self, **_kwargs: Any) -> dict[str, Any]:
                return {"Body": Body()}

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = int(server.sockets[0].getsockname()[1])
            result = await ClamAvScanner(
                host="127.0.0.1", port=port, client=S3(), timeout_seconds=2
            ).scan(bucket="private", key="tenant/file")
        finally:
            server.close()
            await server.wait_closed()
        assert bytes(received) == b"%PDF-1.7 test"
        assert result.ok is ok and result.error_code == error_code
