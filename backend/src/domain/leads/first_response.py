"""What counts as answering a prospect.

The whole leakage story rests on one question: *has anyone actually got back to
this person?* If that is answered loosely the number is worse than useless,
because it looks like a measurement while quietly rewarding the wrong behaviour -
a team that assigns and scores every enquiry and calls nobody would show a clean
dashboard.

So the rule is deliberately narrow, and it is stated here, in the domain, rather
than inside whichever service happens to write the row:

**A first response is the first outbound communication from the business to the
customer.**

Two independent conditions, both required:

* the channel must actually reach the customer - a call, an email, a WhatsApp
  message, a meeting that took place. A note, a task or a status change is the
  business talking to itself.
* the direction must be outbound. An inbound call *from* the prospect is the
  enquiry, not the reply to it. Logging it must never clear the warning.

This module is pure: no ORM, no session, no clock. It exists so that when real
WhatsApp, email and webchat events arrive later they can be asked the same
question, in the same words, and get the same answer - a provider event carries a
channel and a direction, which is exactly what these functions take.
"""

from __future__ import annotations

from typing import Final

# Channels that put the business in front of the customer.
CUSTOMER_CONTACT_CHANNELS: Final[frozenset[str]] = frozenset(
    {
        "call",
        "email",
        "whatsapp",
        "meeting",
        # Reserved for the gated providers. Listing them now means switching a
        # provider on does not also require reopening this rule.
        "sms",
        "webchat",
    }
)

# Recorded against the customer, but internal. Named explicitly rather than left
# as "anything not in the set above", so that adding a new activity type forces a
# decision instead of silently counting as contact.
INTERNAL_ONLY_CHANNELS: Final[frozenset[str]] = frozenset(
    {
        "note",
        "task",
        "status_change",
        "system",
    }
)

OUTBOUND: Final = "outbound"
INBOUND: Final = "inbound"
DIRECTIONS: Final[frozenset[str]] = frozenset({OUTBOUND, INBOUND})


def is_customer_contact(channel: str) -> bool:
    """True when the channel reaches the customer at all, in either direction."""
    return channel in CUSTOMER_CONTACT_CHANNELS


def qualifies_as_first_response(*, channel: str, direction: str) -> bool:
    """The single rule. Outbound, on a channel that reaches the customer.

    Anything unrecognised is `False` on purpose: an unknown channel must not be
    able to mark a prospect as answered by default.
    """
    return direction == OUTBOUND and is_customer_contact(channel)


def default_direction() -> str:
    """What a human logging an activity by hand almost always means.

    Somebody typing a call or a WhatsApp message into the timeline is recording
    that *they* made contact; that is why the form defaults this way. It is only a
    default - the caller may say otherwise, and an inbound call recorded as
    inbound will not count.

    Internal channels get `outbound` too, which is harmless: they can never
    qualify, because `qualifies_as_first_response` also demands a customer
    channel.
    """
    return OUTBOUND
