"""Inbound provider webhooks.

Every route verifies the source signature, enforces a replay window, deduplicates by
event id and enqueues. No business work is ever performed synchronously.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from api.app.envelope import success
from shared.exceptions import Forbidden

router = APIRouter(prefix="/webhooks/inbound", tags=["webhooks"])


@router.get("/whatsapp/{provider}", summary="WhatsApp subscription verification")
async def whatsapp_verify(provider: str, request: Request) -> Response:
    from application.communications.registry import get_whatsapp_adapter

    adapter = get_whatsapp_adapter()
    challenge = adapter.verify_challenge(
        mode=request.query_params.get("hub.mode", ""),
        token=request.query_params.get("hub.verify_token", ""),
        challenge=request.query_params.get("hub.challenge", ""),
    )
    if challenge is None:
        raise Forbidden("Verification failed.")
    return Response(content=challenge, media_type="text/plain")


@router.post(
    "/whatsapp/{provider}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="WhatsApp delivery and inbound messages",
)
async def whatsapp_webhook(provider: str, request: Request) -> dict[str, Any]:
    from application.communications.inbound import enqueue_whatsapp_events
    from application.communications.registry import get_whatsapp_adapter

    body = await request.body()
    adapter = get_whatsapp_adapter()
    if not adapter.verify_webhook(body=body, headers=dict(request.headers)):
        raise Forbidden("Signature verification failed.")
    accepted = await enqueue_whatsapp_events(
        adapter.parse_webhook(await request.json()),
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return success(
        {"accepted": accepted}, request_id=getattr(request.state, "correlation_id", None)
    )


@router.post(
    "/razorpay",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Razorpay payment events",
)
async def razorpay_webhook(request: Request) -> dict[str, Any]:
    from application.payments.inbound import enqueue_razorpay_event
    from application.payments.registry import get_razorpay_adapter

    body = await request.body()
    adapter = get_razorpay_adapter()
    signature = request.headers.get("x-razorpay-signature", "")
    if not adapter.verify_webhook_signature(body=body, signature=signature):
        raise Forbidden("Signature verification failed.")
    parsed = adapter.parse_webhook(await request.json())
    accepted = await enqueue_razorpay_event(
        parsed, correlation_id=getattr(request.state, "correlation_id", None)
    )
    return success(
        {"accepted": accepted, "event": parsed["event"]},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post(
    "/email/{provider}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email delivery and bounce events",
)
async def email_webhook(provider: str, request: Request) -> dict[str, Any]:
    from application.communications.inbound import enqueue_email_events
    from application.communications.registry import get_email_adapter

    body = await request.body()
    adapter = get_email_adapter()
    if not adapter.verify_webhook(body=body, headers=dict(request.headers)):
        raise Forbidden("Signature verification failed.")
    accepted = await enqueue_email_events(adapter.parse_webhook(await request.json()))
    return success(
        {"accepted": accepted}, request_id=getattr(request.state, "correlation_id", None)
    )


@router.post(
    "/custom/{webhook_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tenant custom workflow ingress",
)
async def custom_webhook(webhook_id: str, request: Request) -> dict[str, Any]:
    """Acknowledge within 2 seconds; downstream work may be deferred or dead-lettered."""
    from application.workflows.ingress import accept_custom_webhook

    result = await accept_custom_webhook(
        webhook_id=webhook_id,
        body=await request.body(),
        headers=dict(request.headers),
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))
