"""All eight mandatory templates must onboard a tenant with configuration only."""

from __future__ import annotations

import pytest

from domain.ai.guards import TEMPLATE_PROHIBITIONS
from domain.tenants.templates import (
    GENERIC_TEMPLATE_CODE,
    MANDATORY_TEMPLATE_CODES,
    apply_template,
    available_codes,
    get_template,
    pipeline_stages,
    prohibited_rules,
    qualification_criteria,
    terminology,
    upgrade_template,
    validate_catalog,
)


def test_catalog_is_structurally_valid() -> None:
    assert validate_catalog() == []


def test_all_eight_mandatory_templates_exist_plus_generic() -> None:
    codes = set(available_codes())
    assert set(MANDATORY_TEMPLATE_CODES) <= codes
    assert GENERIC_TEMPLATE_CODE in codes
    assert len(MANDATORY_TEMPLATE_CODES) == 8


@pytest.mark.parametrize("code", MANDATORY_TEMPLATE_CODES)
class TestEveryMandatoryTemplate:
    def test_provisions_a_full_configuration(self, code: str) -> None:
        applied = apply_template(code)
        assert applied.code == code
        assert applied.version >= 1
        for key in (
            "terminology",
            "lead_schema",
            "qualification_rubric",
            "pipeline_stages",
            "message_templates",
            "business_hours",
            "prohibited_ai_rules",
            "consent_copy",
        ):
            assert applied.configuration[key], f"{code} produced an empty {key}"

    def test_rubric_weights_total_one_hundred(self, code: str) -> None:
        assert sum(c["weight"] for c in qualification_criteria(code)) == 100

    def test_pipeline_has_won_and_lost_terminal_stages(self, code: str) -> None:
        stages = pipeline_stages(code)
        assert any(s["is_won"] for s in stages)
        assert any(s["is_lost"] for s in stages)
        assert [s["position"] for s in stages] == list(range(len(stages)))

    def test_lost_stage_requires_a_loss_reason(self, code: str) -> None:
        lost = next(s for s in pipeline_stages(code) if s["is_lost"])
        assert "loss_reason" in lost["required_fields"]

    def test_declares_at_least_one_prohibited_ai_rule(self, code: str) -> None:
        rules = prohibited_rules(code)
        assert rules
        assert all(r.get("rule") and r.get("detail") for r in rules)

    def test_guardrails_are_mirrored_in_the_output_guard(self, code: str) -> None:
        assert code in TEMPLATE_PROHIBITIONS
        assert TEMPLATE_PROHIBITIONS[code]

    def test_terminology_is_localised(self, code: str) -> None:
        words = terminology(code)
        assert words["lead"] and words["deal"] and words["contact"]

    def test_lead_schema_fields_carry_a_classification(self, code: str) -> None:
        for field in get_template(code)["lead_schema"]["fields"]:
            assert field["classification"] in ("P0", "P1", "P2", "P3", "P4")
            assert field["key"] and field["label"] and field["type"]

    def test_consent_copy_covers_whatsapp_and_data_processing(self, code: str) -> None:
        copy = get_template(code)["consent_copy"]
        assert "whatsapp_optin" in copy and "data_processing" in copy


class TestCustomisationPreservation:
    def test_customisation_survives_reapplication(self) -> None:
        custom = {"terminology": {"lead": "Site Visitor", "deal": "Sale", "contact": "Client"}}
        applied = apply_template("real_estate", existing_customisations=custom)
        assert applied.configuration["terminology"]["lead"] == "Site Visitor"
        assert "terminology" in applied.preserved_customisations
        assert applied.divergence["terminology"]["status"] == "customised"

    def test_uncustomised_keys_take_template_defaults(self) -> None:
        applied = apply_template("gyms", existing_customisations={"terminology": {"lead": "X"}})
        assert applied.configuration["pipeline_stages"] == pipeline_stages("gyms")

    def test_guardrails_cannot_be_weakened_by_a_tenant(self) -> None:
        applied = apply_template("clinics", existing_customisations={"prohibited_ai_rules": []})
        assert applied.configuration["prohibited_ai_rules"] == prohibited_rules("clinics")
        assert applied.divergence["prohibited_ai_rules"]["status"] == "override_rejected"

    def test_upgrade_records_the_version_delta(self) -> None:
        applied = upgrade_template(
            "recruitment",
            from_version=1,
            to_version=1,
            existing_customisations={
                "business_hours": {"monday": {"start": "08:00", "end": "20:00"}}
            },
        )
        assert applied.divergence["_upgrade"]["from_version"] == 1
        assert "business_hours" in applied.preserved_customisations
        assert applied.configuration["business_hours"]["monday"]["start"] == "08:00"

    def test_unknown_template_is_rejected(self) -> None:
        with pytest.raises(KeyError):
            apply_template("cryptocurrency_exchange")

    def test_unknown_version_is_rejected(self) -> None:
        with pytest.raises(KeyError):
            get_template("gyms", version=99)


class TestIndustrySpecificSafetyConfiguration:
    def test_clinic_declares_emergency_routing(self) -> None:
        routing = get_template("clinics")["emergency_routing"]
        assert routing["enabled"] is True
        assert routing["action"] == "immediate_human_handoff"
        assert "chest pain" in routing["keywords"]
        assert routing["script"]

    def test_coaching_declares_minor_data_handling(self) -> None:
        policy = get_template("coaching_institutes")["minor_policy"]
        assert policy["require_guardian_consent"] is True
        assert policy["contact_via_guardian_only"] is True

    def test_recruitment_requires_consent_before_profile_sharing(self) -> None:
        rules = {r["rule"] for r in prohibited_rules("recruitment")}
        assert "no_protected_trait_inference" in rules
        assert "no_autonomous_rejection" in rules
        assert "consent_before_share" in rules

    def test_ca_firm_restricts_financial_documents(self) -> None:
        rules = {r["rule"] for r in prohibited_rules("ca_firms")}
        assert "no_tax_opinion" in rules
        assert "restrict_financial_documents" in rules

    def test_dealership_requires_verified_commercial_data(self) -> None:
        rules = {r["rule"] for r in prohibited_rules("automobile_dealerships")}
        assert "verified_price_only" in rules


def test_no_industry_specific_code_module_exists() -> None:
    """Industry variation must be configuration; a per-industry package is a defect."""
    from pathlib import Path

    domain_root = Path(__file__).resolve().parents[2] / "src" / "domain"
    packages = {p.name for p in domain_root.iterdir() if p.is_dir()}
    assert not (packages & set(MANDATORY_TEMPLATE_CODES))
