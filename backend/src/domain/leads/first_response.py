"""What counts as answering a prospect.

The whole leakage story rests on one question: *has anyone actually got back to
this person?* If that is answered loosely the number is worse than useless,
because it looks like a measurement while quietly rewarding the wrong behaviour -
a team that assigns and scores every enquiry and calls nobody would show a clean
dashboard.

So the rule is deliberately narrow, and it is stated here, in the domain, rather
than inside whichever service happens to write the row.

**A first response is the first time a human on the business side actually
engaged with the customer.**

Three independent conditions, all required:

* the **channel** must actually reach the customer - a call, an email, a WhatsApp
  message, a meeting. A note, a task or a status change is the business talking
  to itself.
* the **direction** decides what the record means on its own: an outbound contact
  is the business reaching out, an inbound one is the customer arriving. Inbound
  alone is the enquiry, not the reply to it.
* the **outcome** decides whether the contact actually happened. This is the part
  session 4 dogfooding proved was missing. A call that rang out, a message that
  the provider rejected and a meeting that is merely in the diary are all real
  records of real intent, and none of them is a reply. Before this existed, the
  founders' "No answer" was decorative text on the subject line and the prospect
  was silently marked as answered.

Two consequences worth stating, because they are the point:

* **A missed inbound call does not answer anything.** Receiving an event is not
  engaging with a person. But an inbound call somebody *picked up and spoke on*
  is a genuine first engagement, and refusing to count it would punish a business
  for answering its phone quickly.
* **A scheduled meeting is a promise, a held meeting is a conversation.** Only
  the second one can be a first response.

This module is pure: no ORM, no session, no clock. It exists so that when real
WhatsApp, email and webchat events arrive they can be asked the same question, in
the same words, and get the same answer - a provider event carries a channel, a
direction and a delivery status, which is exactly what these functions take. It
is the only place any of this is decided; nothing downstream may re-implement it.
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

# --- outcomes -----------------------------------------------------------------
#
# Deliberately few, and named the way the founders and their salespeople speak.
# "spoke" is what somebody types after picking up the phone; "no_answer" is what
# they type after it rang out. A vocabulary a salesperson would not use is a
# vocabulary that gets filled in wrongly, and a wrongly filled outcome now
# changes a number.

# The business and the customer actually interacted.
SPOKE: Final = "spoke"  # a call where they talked
MEETING_HELD: Final = "meeting_held"  # a meeting that took place
SENT: Final = "sent"  # a message the provider genuinely accepted

# Real records that are not an interaction.
NO_ANSWER: Final = "no_answer"  # rang out, missed, went to voicemail
MEETING_SCHEDULED: Final = "meeting_scheduled"  # in the diary, has not happened
RECEIVED: Final = "received"  # an inbound message sitting there unanswered
FAILED: Final = "failed"  # the provider rejected or could not deliver it
CANCELLED: Final = "cancelled"  # called off before it happened
NO_SHOW: Final = "no_show"  # arranged, nobody came

#: Outcomes that mean a human on each side was actually in contact.
ENGAGED_OUTCOMES: Final[frozenset[str]] = frozenset({SPOKE, MEETING_HELD, SENT})

#: Outcomes that record something real which is *not* an interaction. Named
#: explicitly rather than inferred, so a new outcome cannot default to "counts".
UNENGAGED_OUTCOMES: Final[frozenset[str]] = frozenset(
    {NO_ANSWER, MEETING_SCHEDULED, RECEIVED, FAILED, CANCELLED, NO_SHOW}
)

OUTCOMES: Final[frozenset[str]] = ENGAGED_OUTCOMES | UNENGAGED_OUTCOMES

#: Which outcomes make sense against which channel, so the API can reject
#: "a call that was meeting_held" instead of storing a record nobody can read.
OUTCOMES_BY_CHANNEL: Final[dict[str, frozenset[str]]] = {
    "call": frozenset({SPOKE, NO_ANSWER}),
    "meeting": frozenset({MEETING_HELD, MEETING_SCHEDULED, CANCELLED, NO_SHOW}),
    "email": frozenset({SENT, RECEIVED, FAILED}),
    "whatsapp": frozenset({SENT, RECEIVED, FAILED}),
    "sms": frozenset({SENT, RECEIVED, FAILED}),
    "webchat": frozenset({SENT, RECEIVED, FAILED}),
}

#: Inbound engagement is narrower than outbound engagement on purpose. Somebody
#: answering the phone engaged with the customer; a message merely arriving did
#: not, and neither did the business "sending" something inbound, which is not a
#: thing that can happen.
INBOUND_ENGAGED_OUTCOMES: Final[frozenset[str]] = frozenset({SPOKE, MEETING_HELD})


def is_customer_contact(channel: str) -> bool:
    """True when the channel reaches the customer at all, in either direction."""
    return channel in CUSTOMER_CONTACT_CHANNELS


def is_valid_outcome(*, channel: str, outcome: str) -> bool:
    """True when this outcome is meaningful for this channel."""
    return outcome in OUTCOMES_BY_CHANNEL.get(channel, frozenset())


def qualifies_as_first_response(
    *, channel: str, direction: str, outcome: str | None = None
) -> bool:
    """The single rule. Nothing anywhere else may decide this.

    `outcome` is optional so that callers which genuinely do not know one - older
    records, and any provider event that carries no delivery state - keep the
    behaviour they have always had: an outbound contact on a customer-reaching
    channel counts, an inbound one does not. Supplying an outcome only ever makes
    the rule *stricter* or lets a genuine inbound engagement through; it can never
    turn an internal record into a reply.

    Anything unrecognised is `False` on purpose: an unknown channel or an unknown
    outcome must not be able to mark a prospect as answered by default.
    """
    if not is_customer_contact(channel):
        return False
    if direction not in DIRECTIONS:
        return False

    if outcome is None:
        # No outcome recorded. This is the session-2 rule, unchanged.
        return direction == OUTBOUND

    if outcome not in OUTCOMES:
        return False
    if outcome in UNENGAGED_OUTCOMES:
        # A missed call, a diary entry, a failed send or an unanswered inbound
        # message. Real, recorded, and not a reply - whichever way it points.
        return False

    if direction == OUTBOUND:
        return True
    return outcome in INBOUND_ENGAGED_OUTCOMES


def default_direction() -> str:
    """What a human logging an activity by hand almost always means.

    Somebody typing a call or a WhatsApp message into the timeline is recording
    that *they* made contact; that is why the form defaults this way. It is only a
    default - the caller may say otherwise, and an inbound call recorded as
    inbound will not count unless somebody actually answered it.

    Internal channels get `outbound` too, which is harmless: they can never
    qualify, because `qualifies_as_first_response` also demands a customer
    channel.
    """
    return OUTBOUND


def describe_outcome(outcome: str | None) -> str:
    """Plain words for the timeline, in the language the founders already use."""
    return {
        SPOKE: "spoke with them",
        NO_ANSWER: "no answer",
        MEETING_HELD: "meeting happened",
        MEETING_SCHEDULED: "meeting scheduled",
        SENT: "sent",
        RECEIVED: "received",
        FAILED: "failed to send",
        CANCELLED: "cancelled",
        NO_SHOW: "nobody came",
    }.get(outcome or "", "")
