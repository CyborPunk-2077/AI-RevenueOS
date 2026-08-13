"""The one rule that decides whether a prospect has been answered.

Every case here came from a sentence a founder actually said while dogfooding.
The rule is pure, so these run in milliseconds and there is no excuse for the
question being decided anywhere else.
"""

from __future__ import annotations

import pytest

from domain.leads.first_response import (
    CUSTOMER_CONTACT_CHANNELS,
    INTERNAL_ONLY_CHANNELS,
    OUTCOMES,
    OUTCOMES_BY_CHANNEL,
    default_direction,
    describe_outcome,
    is_valid_outcome,
    qualifies_as_first_response,
)


class TestOutboundContact:
    """We got in touch with them."""

    @pytest.mark.parametrize("channel", ["call", "email", "whatsapp", "meeting", "sms", "webchat"])
    def test_outbound_on_a_customer_channel_answers_the_enquiry(self, channel: str) -> None:
        assert qualifies_as_first_response(channel=channel, direction="outbound")

    def test_a_call_they_actually_spoke_on_counts(self) -> None:
        assert qualifies_as_first_response(channel="call", direction="outbound", outcome="spoke")

    def test_a_call_that_rang_out_does_not_count(self) -> None:
        # The defect this session exists to fix: "No answer" used to be decorative
        # text on the subject line while the prospect was marked as answered.
        assert not qualifies_as_first_response(
            channel="call", direction="outbound", outcome="no_answer"
        )

    def test_a_message_the_provider_rejected_does_not_count(self) -> None:
        assert not qualifies_as_first_response(
            channel="whatsapp", direction="outbound", outcome="failed"
        )

    def test_a_message_the_provider_accepted_counts(self) -> None:
        assert qualifies_as_first_response(channel="whatsapp", direction="outbound", outcome="sent")


class TestInboundContact:
    """They got in touch with us."""

    @pytest.mark.parametrize("channel", ["call", "email", "whatsapp", "meeting"])
    def test_inbound_alone_is_the_enquiry_not_the_reply(self, channel: str) -> None:
        assert not qualifies_as_first_response(channel=channel, direction="inbound")

    def test_an_inbound_call_somebody_answered_is_a_genuine_first_engagement(self) -> None:
        # Customer rings, an employee picks up and talks to them. Refusing to
        # count this would punish a business for answering its phone.
        assert qualifies_as_first_response(channel="call", direction="inbound", outcome="spoke")

    def test_a_missed_inbound_call_leaves_them_waiting(self) -> None:
        assert not qualifies_as_first_response(
            channel="call", direction="inbound", outcome="no_answer"
        )

    def test_an_inbound_message_merely_arriving_is_not_a_reply(self) -> None:
        # This is the WhatsApp case: the webhook fires, the enquiry exists, and
        # nobody has said anything back yet.
        assert not qualifies_as_first_response(
            channel="whatsapp", direction="inbound", outcome="received"
        )


class TestMeetings:
    def test_a_meeting_that_happened_can_answer_the_enquiry(self) -> None:
        assert qualifies_as_first_response(
            channel="meeting", direction="outbound", outcome="meeting_held"
        )

    def test_a_meeting_they_came_to_counts_even_when_they_asked_for_it(self) -> None:
        assert qualifies_as_first_response(
            channel="meeting", direction="inbound", outcome="meeting_held"
        )

    def test_a_meeting_merely_in_the_diary_does_not(self) -> None:
        assert not qualifies_as_first_response(
            channel="meeting", direction="outbound", outcome="meeting_scheduled"
        )

    @pytest.mark.parametrize("outcome", ["cancelled", "no_show"])
    def test_a_meeting_that_did_not_happen_does_not(self, outcome: str) -> None:
        assert not qualifies_as_first_response(
            channel="meeting", direction="outbound", outcome=outcome
        )


class TestInternalWork:
    """The business talking to itself never answers anybody."""

    @pytest.mark.parametrize("channel", sorted(INTERNAL_ONLY_CHANNELS))
    @pytest.mark.parametrize("direction", ["outbound", "inbound"])
    def test_internal_channels_never_qualify(self, channel: str, direction: str) -> None:
        assert not qualifies_as_first_response(channel=channel, direction=direction)

    @pytest.mark.parametrize("channel", sorted(INTERNAL_ONLY_CHANNELS))
    def test_an_outcome_cannot_promote_internal_work(self, channel: str) -> None:
        # Belt and braces: even the strongest engagement outcome must not let a
        # task or a note through.
        assert not qualifies_as_first_response(
            channel=channel, direction="outbound", outcome="spoke"
        )


class TestUnknownInput:
    """Anything unrecognised must fail closed."""

    def test_an_unknown_channel_does_not_qualify(self) -> None:
        assert not qualifies_as_first_response(channel="carrier_pigeon", direction="outbound")

    def test_an_unknown_direction_does_not_qualify(self) -> None:
        assert not qualifies_as_first_response(channel="call", direction="sideways")

    def test_an_unknown_outcome_does_not_qualify(self) -> None:
        assert not qualifies_as_first_response(
            channel="call", direction="outbound", outcome="vibes"
        )


class TestBackwardsCompatibility:
    """Records written before outcomes existed must keep their meaning."""

    def test_no_outcome_is_the_session_two_rule_unchanged(self) -> None:
        for channel in CUSTOMER_CONTACT_CHANNELS:
            assert qualifies_as_first_response(channel=channel, direction="outbound")
            assert not qualifies_as_first_response(channel=channel, direction="inbound")

    def test_the_default_direction_is_still_outbound(self) -> None:
        assert default_direction() == "outbound"


class TestVocabulary:
    def test_every_outcome_belongs_to_at_least_one_channel(self) -> None:
        used = set().union(*OUTCOMES_BY_CHANNEL.values())
        assert used == set(OUTCOMES)

    def test_outcomes_are_only_offered_for_customer_channels(self) -> None:
        assert set(OUTCOMES_BY_CHANNEL) <= set(CUSTOMER_CONTACT_CHANNELS)

    def test_a_call_cannot_end_in_a_meeting_outcome(self) -> None:
        assert not is_valid_outcome(channel="call", outcome="meeting_held")
        assert is_valid_outcome(channel="call", outcome="spoke")

    def test_every_outcome_has_plain_words_for_the_timeline(self) -> None:
        for outcome in OUTCOMES:
            assert describe_outcome(outcome), outcome

    def test_no_outcome_describes_as_nothing(self) -> None:
        assert describe_outcome(None) == ""
