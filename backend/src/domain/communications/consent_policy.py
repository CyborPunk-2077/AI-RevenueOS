"""Send-eligibility policy.

Consent, suppression, opt-out, quiet hours, frequency caps, channel preference and
deliverability are evaluated before EVERY outbound customer contact - manual,
automated, AI-suggested or workflow-driven. There is exactly one code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum, StrEnum
from typing import Any

from shared.utils.timeutil import to_local


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"
    WEB_CHAT = "web_chat"
    IN_APP = "in_app"


class ConsentType(StrEnum):
    MARKETING = "marketing"
    COMMUNICATION = "communication"
    DATA_PROCESSING = "data_processing"
    WHATSAPP_OPTIN = "whatsapp_optin"


class Block(Enum):
    """Ordered by severity. The first match wins and is surfaced to the operator."""

    OPTED_OUT = "opted_out"
    SUPPRESSED = "suppressed"
    NO_CONSENT = "no_consent"
    CONSENT_EXPIRED = "consent_expired"
    CHANNEL_DISABLED = "channel_disabled"
    CHANNEL_UNHEALTHY = "channel_unhealthy"
    FEATURE_DISABLED = "feature_disabled"
    QUIET_HOURS = "quiet_hours"
    FREQUENCY_CAP = "frequency_cap"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNDELIVERABLE = "undeliverable"
    AUTOMATION_STOPPED = "automation_stopped"
    TEMPLATE_NOT_APPROVED = "template_not_approved"
    FREEFORM_WINDOW_CLOSED = "freeform_window_closed"


HUMAN_MESSAGES: dict[Block, str] = {
    Block.OPTED_OUT: "The recipient has opted out of this channel.",
    Block.SUPPRESSED: "This address or number is on the suppression list.",
    Block.NO_CONSENT: "No valid consent record exists for this purpose.",
    Block.CONSENT_EXPIRED: "The recorded consent has expired.",
    Block.CHANNEL_DISABLED: "The channel is not connected for this tenant.",
    Block.CHANNEL_UNHEALTHY: "The channel is currently unhealthy; the message was queued.",
    Block.FEATURE_DISABLED: "This channel is not enabled on the current plan or environment.",
    Block.QUIET_HOURS: "It is outside the permitted contact hours for this recipient.",
    Block.FREQUENCY_CAP: "The daily contact limit for this recipient has been reached.",
    Block.BUDGET_EXHAUSTED: "The tenant messaging budget is exhausted.",
    Block.UNDELIVERABLE: "The last delivery attempt hard-failed for this address.",
    Block.AUTOMATION_STOPPED: "Automation is stopped on this conversation after human handoff.",
    Block.TEMPLATE_NOT_APPROVED: "The message template is not approved by the provider.",
    Block.FREEFORM_WINDOW_CLOSED: (
        "The freeform window has closed; an approved template is required."
    ),
}

# Marketing needs explicit marketing consent; transactional needs communication consent.
PURPOSE_CONSENT: dict[str, ConsentType] = {
    "marketing": ConsentType.MARKETING,
    "promotional": ConsentType.MARKETING,
    "transactional": ConsentType.COMMUNICATION,
    "utility": ConsentType.COMMUNICATION,
    "service": ConsentType.COMMUNICATION,
    "authentication": ConsentType.COMMUNICATION,
}

# Purposes exempt from quiet hours because withholding them harms the recipient.
QUIET_HOURS_EXEMPT = frozenset({"authentication", "appointment_reminder_urgent", "security"})

DEFAULT_QUIET_HOURS = {"start": "21:00", "end": "09:00", "timezone": "Asia/Kolkata"}
DEFAULT_FREQUENCY_CAP_PER_DAY = 5
WHATSAPP_FREEFORM_WINDOW_HOURS = 24


@dataclass(frozen=True, slots=True)
class SendContext:
    channel: Channel
    purpose: str = "transactional"
    now: datetime | None = None
    tenant_timezone: str = "Asia/Kolkata"

    # subject state
    opted_out: bool = False
    suppressed: bool = False
    consent_granted: bool = False
    consent_expires_at: datetime | None = None
    last_inbound_at: datetime | None = None
    sends_today: int = 0
    hard_bounced: bool = False

    # tenant/channel state
    channel_connected: bool = True
    channel_healthy: bool = True
    feature_enabled: bool = True
    budget_remaining: int = 1
    automation_stopped: bool = False

    # policy configuration
    quiet_hours: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_QUIET_HOURS))
    frequency_cap_per_day: int | None = DEFAULT_FREQUENCY_CAP_PER_DAY

    # message shape
    uses_template: bool = False
    template_approved: bool = False
    is_automated: bool = True


@dataclass(frozen=True, slots=True)
class SendDecision:
    allowed: bool
    blocks: tuple[Block, ...] = ()
    queued: bool = False
    requires_template: bool = False

    @property
    def primary_block(self) -> Block | None:
        return self.blocks[0] if self.blocks else None

    @property
    def reason(self) -> str | None:
        block = self.primary_block
        return HUMAN_MESSAGES[block] if block else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "queued": self.queued,
            "requires_template": self.requires_template,
            "blocks": [b.value for b in self.blocks],
            "reason": self.reason,
        }


def _parse_hhmm(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))


def in_quiet_hours(now: datetime, quiet_hours: dict[str, Any], fallback_tz: str) -> bool:
    """Quiet hours are evaluated in the recipient's local time and may wrap midnight."""
    if not quiet_hours or quiet_hours.get("enabled") is False:
        return False
    tz_name = quiet_hours.get("timezone") or fallback_tz
    local = to_local(now, tz_name).time()
    start = _parse_hhmm(str(quiet_hours.get("start", "21:00")))
    end = _parse_hhmm(str(quiet_hours.get("end", "09:00")))
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def freeform_window_open(last_inbound_at: datetime | None, now: datetime) -> bool:
    if last_inbound_at is None:
        return False
    return now - last_inbound_at < timedelta(hours=WHATSAPP_FREEFORM_WINDOW_HOURS)


def evaluate_send(ctx: SendContext) -> SendDecision:
    """Single decision point for outbound customer contact."""
    now = ctx.now or datetime.now(tz=to_local(datetime.now(), ctx.tenant_timezone).tzinfo)
    blocks: list[Block] = []

    # Hard stops: never queued, never retried, never overridable by automation.
    if ctx.opted_out:
        blocks.append(Block.OPTED_OUT)
    if ctx.suppressed:
        blocks.append(Block.SUPPRESSED)
    if ctx.automation_stopped and ctx.is_automated:
        blocks.append(Block.AUTOMATION_STOPPED)

    required = PURPOSE_CONSENT.get(ctx.purpose, ConsentType.COMMUNICATION)
    if ctx.channel in (Channel.WHATSAPP, Channel.EMAIL, Channel.SMS, Channel.VOICE):
        if not ctx.consent_granted:
            blocks.append(Block.NO_CONSENT)
        elif ctx.consent_expires_at is not None and ctx.consent_expires_at <= now:
            blocks.append(Block.CONSENT_EXPIRED)
    if (
        required is ConsentType.MARKETING
        and not ctx.consent_granted
        and Block.NO_CONSENT not in blocks
    ):
        blocks.append(Block.NO_CONSENT)

    if not ctx.feature_enabled:
        blocks.append(Block.FEATURE_DISABLED)
    if not ctx.channel_connected:
        blocks.append(Block.CHANNEL_DISABLED)
    if ctx.hard_bounced:
        blocks.append(Block.UNDELIVERABLE)
    if ctx.budget_remaining <= 0:
        blocks.append(Block.BUDGET_EXHAUSTED)

    if ctx.purpose not in QUIET_HOURS_EXEMPT and in_quiet_hours(
        now, ctx.quiet_hours, ctx.tenant_timezone
    ):
        blocks.append(Block.QUIET_HOURS)

    cap = ctx.frequency_cap_per_day
    if cap is not None and ctx.sends_today >= cap:
        blocks.append(Block.FREQUENCY_CAP)

    requires_template = False
    if ctx.channel is Channel.WHATSAPP:
        window_open = freeform_window_open(ctx.last_inbound_at, now)
        if not window_open:
            requires_template = True
            if not ctx.uses_template:
                blocks.append(Block.FREEFORM_WINDOW_CLOSED)
            elif not ctx.template_approved:
                blocks.append(Block.TEMPLATE_NOT_APPROVED)
        elif ctx.uses_template and not ctx.template_approved:
            blocks.append(Block.TEMPLATE_NOT_APPROVED)

    # An unhealthy but otherwise permitted send is queued rather than rejected.
    if not blocks and not ctx.channel_healthy:
        return SendDecision(
            allowed=True,
            queued=True,
            blocks=(Block.CHANNEL_UNHEALTHY,),
            requires_template=requires_template,
        )

    ordered = tuple(sorted(set(blocks), key=lambda b: list(Block).index(b)))
    return SendDecision(
        allowed=not ordered, blocks=ordered, queued=False, requires_template=requires_template
    )


def revocation_cancels(purpose: str) -> bool:
    """Revocation immediately cancels queued and running work for every purpose
    except security and authentication, which are never marketing contact."""
    return purpose not in ("authentication", "security")
