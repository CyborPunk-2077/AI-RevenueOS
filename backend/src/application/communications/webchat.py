"""Webchat: widget configuration, visitor sessions, and the public message surface.

This is the only place in the product where an anonymous stranger writes rows
into a tenant's database, so the constraints are stricter than anywhere else and
each one is here for a stated reason.

**The origin is the authentication.** A widget is identified by a public key that
is, by design, visible in the page source of every site that embeds it. The key
says *which* tenant; the `Origin` header says *whether this page is allowed to
speak for them*. A widget with no allowed origins is inert rather than open:
fail-closed, because the empty list is what a half-finished configuration looks
like.

**A session token is not a login.** It is an opaque bearer string, stored only as
a SHA-256, scoped to one conversation, and expiring in two hours. Holding one
lets you continue a conversation you started. It grants no read access to
anything else, and it never becomes a `Principal`.

**Nothing here can reach another tenant.** Every write goes through
`tenant_session`, so RLS applies to the anonymous path exactly as it does to the
authenticated one.

**Consent is recorded, not assumed.** The widget shows the tenant's consent copy;
the visitor's acceptance is stored on the session. A conversation without consent
can still happen - someone asking a question is not a marketing opt-in - but it
cannot be used as a basis for later outbound contact, which is what
`consent_granted` is read for downstream.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select

from application.audit.recorder import AuditRecorder
from domain.leads.form_schema import validate_origins
from infrastructure.database.models.communications import (
    Conversation,
    Message,
    WebchatSession,
    WebchatWidget,
)
from infrastructure.database.session import platform_session, tenant_session
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span
from shared.exceptions import Forbidden, NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.communications.webchat")

SESSION_TTL: Final = timedelta(hours=2)
MAX_MESSAGE_CHARS: Final = 2_000
MAX_MESSAGES_PER_SESSION: Final = 200
CHANNEL: Final = "web_chat"

#: The shape `new_public_key` actually produces. `token_urlsafe` draws from the
#: URL-safe base64 alphabet, so a key may contain `-` and `_` - and this pattern
#: used to allow neither, which made the cheap "is this even a key" guard reject
#: about two thirds of the keys the product had just minted. The widget then
#: reported itself unavailable to its own site, and the tests that caught it
#: passed or failed on the luck of the draw. Whatever the generator emits, this
#: must accept.
_PUBLIC_KEY = re.compile(r"^wck_[A-Za-z0-9_-]{32}$")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_public_key() -> str:
    """Visible in page source by design; it identifies, it does not authorise."""
    return f"wck_{secrets.token_urlsafe(32)[:32]}"


def normalise_origin(raw: str | None) -> str:
    """Scheme + host + port, lowercased, no trailing slash and no path."""
    origin = (raw or "").strip().rstrip("/")
    if origin.count("/") > 2:
        parts = origin.split("/")
        origin = "/".join(parts[:3])
    return origin.lower()[:300]


def origin_allowed(origin: str, allowed: list[Any]) -> bool:
    """Fail closed. An empty allow-list means the widget is not configured yet."""
    if not allowed:
        return False
    return normalise_origin(origin) in {normalise_origin(str(a)) for a in allowed}


@dataclass(frozen=True, slots=True)
class VisitorSession:
    session_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    token: str
    greeting: str
    consent_copy: str
    handoff_enabled: bool


# ---------------------------------------------------------------- configuration


def _serialize_widget(widget: WebchatWidget, *, include_key: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(widget.id),
        "allowed_origins": list(widget.allowed_origins or []),
        "branding": widget.branding,
        "greeting": widget.greeting,
        "consent_copy": widget.consent_copy,
        "ai_suggestions_enabled": widget.ai_suggestions_enabled,
        "handoff_enabled": widget.handoff_enabled,
        "is_active": widget.is_active,
        "version": widget.version,
    }
    if include_key:
        data["public_key"] = widget.public_key
    return data


async def get_widget(*, tenant_id: UUID) -> dict[str, Any] | None:
    async with tenant_session(tenant_id) as session:
        widget: WebchatWidget | None = (
            await session.execute(select(WebchatWidget).where(WebchatWidget.tenant_id == tenant_id))
        ).scalar_one_or_none()
        return _serialize_widget(widget, include_key=True) if widget else None


async def configure_widget(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    allowed_origins: list[Any] | None = None,
    greeting: str | None = None,
    consent_copy: str | None = None,
    branding: dict[str, Any] | None = None,
    handoff_enabled: bool | None = None,
    ai_suggestions_enabled: bool | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    """Create or update the tenant's single widget.

    Activating with no origins is refused rather than silently accepted: the
    widget would be embeddable from any site that copies the key.
    """
    origins = validate_origins(allowed_origins) if allowed_origins is not None else None

    async with tenant_session(tenant_id) as session:
        widget: WebchatWidget | None = (
            await session.execute(select(WebchatWidget).where(WebchatWidget.tenant_id == tenant_id))
        ).scalar_one_or_none()

        created = widget is None
        if widget is None:
            widget = WebchatWidget(
                id=uuid7(),
                tenant_id=tenant_id,
                public_key=new_public_key(),
                allowed_origins=[],
                branding={},
                greeting="",
                consent_copy="",
                is_active=False,
                version=1,
            )
            session.add(widget)

        if origins is not None:
            widget.allowed_origins = origins
        if greeting is not None:
            widget.greeting = greeting.strip()[:500]
        if consent_copy is not None:
            widget.consent_copy = consent_copy.strip()[:1000]
        if branding is not None:
            widget.branding = branding
        if handoff_enabled is not None:
            widget.handoff_enabled = handoff_enabled
        if ai_suggestions_enabled is not None:
            widget.ai_suggestions_enabled = ai_suggestions_enabled
        if is_active is not None:
            if is_active and not (widget.allowed_origins or []):
                raise ValidationError(
                    "List the sites allowed to embed this widget before activating it.",
                    details={"field": "allowed_origins"},
                )
            widget.is_active = is_active
        if not created:
            widget.version += 1

        AuditRecorder(session).record(
            action="webchat.widget_configured" if not created else "webchat.widget_created",
            resource_type="webchat_widget",
            resource_id=widget.id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={
                "is_active": widget.is_active,
                "origins": len(widget.allowed_origins or []),
                "handoff_enabled": widget.handoff_enabled,
            },
        )
        return _serialize_widget(widget, include_key=True)


async def rotate_public_key(*, tenant_id: UUID, actor_id: UUID) -> dict[str, Any]:
    """Issue a new key. Every embedded snippet must be updated after this."""
    async with tenant_session(tenant_id) as session:
        widget: WebchatWidget | None = (
            await session.execute(select(WebchatWidget).where(WebchatWidget.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if widget is None:
            raise NotFound("This organisation has no webchat widget.")

        widget.public_key = new_public_key()
        widget.version += 1
        AuditRecorder(session).record(
            action="webchat.key_rotated",
            resource_type="webchat_widget",
            resource_id=widget.id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"rotated": True},
        )
        return _serialize_widget(widget, include_key=True)


# ------------------------------------------------------------------ public path


async def _widget_by_key(public_key: str) -> WebchatWidget | None:
    """Resolve a key to its tenant.

    This is the one query that cannot be tenant-scoped - the caller is anonymous
    and the key is what names the tenant - so it reads exactly one row by a unique
    indexed column and everything after it runs inside `tenant_session`.

    It cannot be *unscoped* either: under the tenant policy a session with nothing
    bound sees no rows, so this returned None for every widget, and the whole
    visitor path answered "this chat widget is not available". The
    `public_surface_lookup` policy added in migration 0012 exposes active widgets
    only, and only under a deliberately bound platform context, which is logged.
    """
    if not _PUBLIC_KEY.match(public_key or ""):
        return None
    async with platform_session("webchat widget lookup") as session:
        widget: WebchatWidget | None = (
            await session.execute(
                select(WebchatWidget).where(
                    WebchatWidget.public_key == public_key,
                    WebchatWidget.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        return widget


async def widget_config(*, public_key: str, origin: str) -> dict[str, Any]:
    """What the embedded script may know before anyone has said anything."""
    widget = await _widget_by_key(public_key)
    if widget is None:
        raise NotFound("This chat widget is not available.")
    if not origin_allowed(origin, list(widget.allowed_origins or [])):
        raise Forbidden("This site is not allowed to embed this chat widget.")

    return {
        "greeting": widget.greeting,
        "consent_copy": widget.consent_copy,
        "branding": widget.branding,
        "handoff_enabled": widget.handoff_enabled,
    }


async def start_session(
    *,
    public_key: str,
    origin: str,
    visitor_ref: str | None = None,
    consent_granted: bool = False,
    ip: str | None = None,
) -> VisitorSession:
    """Open a visitor session and its conversation."""
    widget = await _widget_by_key(public_key)
    if widget is None:
        raise NotFound("This chat widget is not available.")
    if not origin_allowed(origin, list(widget.allowed_origins or [])):
        raise Forbidden("This site is not allowed to embed this chat widget.")

    tenant_id = widget.tenant_id
    token = f"{tenant_id}.{secrets.token_urlsafe(32)}"
    session_id = uuid7()
    conversation_id = uuid7()

    with start_span(
        "webchat session start",
        attributes={"tenant.id": str(tenant_id), "event.type": "webchat.session_started"},
    ):
        async with tenant_session(tenant_id) as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    primary_channel=CHANNEL,
                    subject="Website chat",
                    status="active",
                    last_message_at=utcnow(),
                    metadata_json={"source": "webchat", "origin": normalise_origin(origin)},
                    version=1,
                )
            )
            session.add(
                WebchatSession(
                    id=session_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    session_token_hash=_hash(token),
                    origin=normalise_origin(origin),
                    # A caller-supplied reference is untrusted input used only to
                    # stitch a returning visitor's tabs together, never to identify.
                    visitor_ref=(visitor_ref or uuid7().hex)[:64],
                    ip_hash=_hash(ip)[:64] if ip else None,
                    consent_granted=consent_granted,
                    expires_at=utcnow() + SESSION_TTL,
                )
            )

    logger.info("webchat_session_started", tenant_id=str(tenant_id))
    return VisitorSession(
        session_id=session_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        token=token,
        greeting=widget.greeting,
        consent_copy=widget.consent_copy,
        handoff_enabled=widget.handoff_enabled,
    )


def _split(token: str) -> tuple[UUID, str]:
    prefix, _, secret = (token or "").partition(".")
    if not prefix or not secret:
        raise NotFound("This chat session has ended.")
    try:
        return UUID(prefix), _hash(token)
    except ValueError as exc:
        raise NotFound("This chat session has ended.") from exc


async def _resolve(session: Any, tenant_id: UUID, token_hash: str) -> WebchatSession:
    row: WebchatSession | None = (
        await session.execute(
            select(WebchatSession).where(
                WebchatSession.tenant_id == tenant_id,
                WebchatSession.session_token_hash == token_hash,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.ended_at is not None or row.expires_at <= utcnow():
        raise NotFound("This chat session has ended.")
    return row


async def post_visitor_message(*, token: str, body: str, origin: str) -> dict[str, Any]:
    """Append an inbound message. The visitor may only write to their own session."""
    text = (body or "").strip()
    if not text:
        raise ValidationError("Type a message first.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValidationError(
            f"Messages are limited to {MAX_MESSAGE_CHARS} characters.",
            details={"limit": MAX_MESSAGE_CHARS},
        )

    tenant_id, token_hash = _split(token)

    with start_span(
        "webchat message", attributes={"tenant.id": str(tenant_id), "event.type": "webchat.message"}
    ):
        async with tenant_session(tenant_id) as session:
            visitor = await _resolve(session, tenant_id, token_hash)
            if normalise_origin(origin) != visitor.origin:
                # The session was opened from one site; a different page holding
                # the token is either a leak or an embed nobody authorised.
                raise Forbidden("This site is not allowed to use this chat session.")

            conversation_id = visitor.conversation_id
            if conversation_id is None:
                raise NotFound("This chat session has ended.")

            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Message)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.conversation_id == conversation_id,
                    )
                )
            ).scalar_one()
            if count >= MAX_MESSAGES_PER_SESSION:
                raise ValidationError(
                    "This conversation has reached its message limit.",
                    details={"limit": MAX_MESSAGES_PER_SESSION},
                )

            now = utcnow()
            message_id = uuid7()
            session.add(
                Message(
                    id=message_id,
                    created_at=now,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    channel=CHANNEL,
                    direction="inbound",
                    sender_type="contact",
                    content=text,
                    content_type="text",
                    status="delivered",
                    delivered_at=now,
                )
            )

            conversation: Conversation = (
                await session.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
            ).scalar_one()
            conversation.last_message_at = now
            conversation.unread_count += 1

            return {
                "message_id": str(message_id),
                "conversation_id": str(conversation_id),
                "created_at": now.isoformat(),
            }


async def visitor_transcript(*, token: str) -> dict[str, Any]:
    """The visitor's own conversation, and nothing else."""
    tenant_id, token_hash = _split(token)

    async with tenant_session(tenant_id) as session:
        visitor = await _resolve(session, tenant_id, token_hash)
        rows = (
            (
                await session.execute(
                    select(Message)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.conversation_id == visitor.conversation_id,
                    )
                    .order_by(Message.created_at)
                    .limit(MAX_MESSAGES_PER_SESSION)
                )
            )
            .scalars()
            .all()
        )

    return {
        "conversation_id": str(visitor.conversation_id),
        "expires_at": visitor.expires_at.isoformat(),
        "messages": [
            {
                "id": str(message.id),
                "direction": message.direction,
                # Agent identity is never exposed to the visitor: the tenant's
                # staffing is not the visitor's business.
                "author": "you" if message.direction == "inbound" else "agent",
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            for message in rows
        ],
    }


async def end_session(*, token: str) -> dict[str, Any]:
    """Close the visitor's session. The conversation stays in the inbox."""
    tenant_id, token_hash = _split(token)
    async with tenant_session(tenant_id) as session:
        visitor = await _resolve(session, tenant_id, token_hash)
        visitor.ended_at = utcnow()
        return {"ended": True, "conversation_id": str(visitor.conversation_id)}


async def active_session_count(*, tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(WebchatSession)
                    .where(
                        WebchatSession.tenant_id == tenant_id,
                        WebchatSession.ended_at.is_(None),
                        WebchatSession.expires_at > utcnow(),
                    )
                )
            ).scalar_one()
        )
