"""Lead lifecycle, duplicate handling and qualification banding."""

from __future__ import annotations

import pytest

from domain.base import InvalidTransition
from domain.leads.lifecycle import (
    ALLOWED_TRANSITIONS,
    LeadStatus,
    assert_transition,
    can_transition,
    dedupe_key,
    duplicate_resolution,
    find_duplicates,
)
from domain.leads.qualification import (
    Category,
    Criterion,
    ReviewState,
    apply_human_decision,
    categorize,
    degraded_result,
    score_from_rubric,
)


class TestLifecycle:
    def test_happy_path(self) -> None:
        assert assert_transition(LeadStatus.NEW, LeadStatus.QUALIFIED) is LeadStatus.QUALIFIED
        assert assert_transition("qualified", "converted") is LeadStatus.CONVERTED

    def test_converted_is_terminal(self) -> None:
        assert ALLOWED_TRANSITIONS[LeadStatus.CONVERTED] == frozenset()
        with pytest.raises(InvalidTransition):
            assert_transition(LeadStatus.CONVERTED, LeadStatus.NEW)

    def test_disqualification_requires_a_reason(self) -> None:
        with pytest.raises(InvalidTransition, match="reason is required"):
            assert_transition(LeadStatus.NEW, LeadStatus.DISQUALIFIED)
        assert (
            assert_transition(LeadStatus.NEW, LeadStatus.DISQUALIFIED, reason="budget too low")
            is LeadStatus.DISQUALIFIED
        )

    def test_self_transition_is_idempotent(self) -> None:
        assert assert_transition("new", "new") is LeadStatus.NEW

    def test_archived_can_be_restored_only_to_new(self) -> None:
        assert can_transition(LeadStatus.ARCHIVED, LeadStatus.NEW) is True
        assert can_transition(LeadStatus.ARCHIVED, LeadStatus.CONVERTED) is False

    def test_every_status_has_a_transition_entry(self) -> None:
        assert set(ALLOWED_TRANSITIONS) == set(LeadStatus)


class TestDedupe:
    def test_email_wins_over_phone(self) -> None:
        assert dedupe_key(email="A@B.com", phone="9876543210") == "e:a@b.com"

    def test_phone_is_normalised_into_the_key(self) -> None:
        assert dedupe_key(phone="09876543210") == "p:+919876543210"

    def test_falls_back_to_name(self) -> None:
        assert dedupe_key(name="Ravi Shankar") == "n:ravi shankar"

    def test_returns_none_without_any_identity(self) -> None:
        assert dedupe_key() is None

    def test_exact_email_match_is_auto_merge(self) -> None:
        existing = [{"id": "1", "email": "asha@example.in", "first_name": "Asha"}]
        found = find_duplicates({"email": "ASHA@example.in "}, existing)
        assert found[0].match_reason == "email_exact"
        assert duplicate_resolution(found) == "merge"

    def test_phone_match_across_formats(self) -> None:
        existing = [{"id": "1", "phone": "+919876543210", "first_name": "Ravi"}]
        found = find_duplicates({"phone": "09876543210"}, existing)
        assert found[0].match_reason == "phone_exact"

    def test_name_and_company_is_reviewed_not_merged(self) -> None:
        existing = [{"id": "1", "first_name": "Ravi", "last_name": "K", "company": "Acme Ltd"}]
        found = find_duplicates(
            {"first_name": "RAVI", "last_name": "k", "company": "acme  ltd"}, existing
        )
        assert found[0].match_reason == "name_and_company"
        assert duplicate_resolution(found) == "review"

    def test_no_match_creates(self) -> None:
        assert duplicate_resolution(find_duplicates({"email": "new@x.in"}, [])) == "create"

    def test_candidates_are_sorted_by_confidence(self) -> None:
        existing = [
            {"id": "weak", "first_name": "A", "last_name": "B", "company": "C"},
            {"id": "strong", "email": "a@b.in"},
        ]
        found = find_duplicates(
            {"email": "a@b.in", "first_name": "A", "last_name": "B", "company": "C"}, existing
        )
        assert found[0].lead_id == "strong"


class TestQualification:
    @pytest.mark.parametrize(
        ("score", "category"),
        [
            (0, Category.COLD),
            (39, Category.COLD),
            (40, Category.WARM),
            (79, Category.WARM),
            (80, Category.HOT),
            (100, Category.HOT),
        ],
    )
    def test_band_boundaries(self, score: int, category: Category) -> None:
        assert categorize(score) is category

    @pytest.mark.parametrize("score", [-1, 101])
    def test_out_of_range_rejected(self, score: int) -> None:
        with pytest.raises(ValueError):
            categorize(score)

    def test_rubric_scoring_reports_evidence_and_missing_fields(self) -> None:
        rubric = [
            Criterion("budget", "Budget", 40, required=True),
            Criterion("location", "Location", 30),
            Criterion("timeline", "Timeline", 30),
        ]
        result = score_from_rubric(rubric, {"budget": "50L", "location": "Pune"})
        assert result.score == 70
        assert result.category is Category.WARM
        assert result.missing_fields == ["timeline"]
        assert {e.criterion for e in result.evidence} == {"budget", "location"}
        assert all(e.source == "capture" for e in result.evidence)

    def test_empty_values_count_as_missing(self) -> None:
        rubric = [Criterion("a", "A", 50), Criterion("b", "B", 50)]
        result = score_from_rubric(rubric, {"a": "", "b": []})
        assert result.score == 0
        assert result.missing_fields == ["a", "b"]

    def test_degraded_result_is_neutral_and_flagged(self) -> None:
        result = degraded_result("provider circuit open")
        assert result.score == 50
        assert result.degraded is True
        assert result.review_state is ReviewState.PENDING
        assert "Manual review required" in result.reasons[0]

    def test_human_accept_preserves_score(self) -> None:
        base = score_from_rubric([Criterion("a", "A", 100)], {"a": 1})
        accepted = apply_human_decision(base, decision="accepted")
        assert accepted.score == base.score
        assert accepted.review_state is ReviewState.ACCEPTED

    def test_human_edit_overrides_and_recategorises(self) -> None:
        base = score_from_rubric([Criterion("a", "A", 100)], {})
        edited = apply_human_decision(base, decision="edited", edited_score=85)
        assert edited.score == 85
        assert edited.category is Category.HOT
        assert edited.qualified_by == "manual"

    def test_edit_without_score_is_rejected(self) -> None:
        base = degraded_result("x")
        with pytest.raises(ValueError):
            apply_human_decision(base, decision="edited")

    def test_reject_and_defer_are_representable(self) -> None:
        base = degraded_result("x")
        assert apply_human_decision(base, decision="rejected").review_state is ReviewState.REJECTED
        assert apply_human_decision(base, decision="deferred").review_state is ReviewState.DEFERRED

    def test_serialisation_includes_provenance(self) -> None:
        payload = score_from_rubric([Criterion("a", "A", 100)], {"a": 1}).to_dict()
        assert payload["provenance"]["method"] == "rubric"
        assert payload["qualified_by"] == "rule"
