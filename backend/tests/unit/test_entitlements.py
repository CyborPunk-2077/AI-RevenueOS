"""Plan, feature and quota enforcement must behave identically on every surface."""

from __future__ import annotations

import pytest

from domain.tenants.entitlements import (
    EXTERNALLY_GATED,
    PLANS,
    UNLIMITED,
    Feature,
    Meter,
    PlanCode,
    check_feature,
    check_quota,
    get_plan,
    plan_catalog,
    quota_warning_threshold,
)


class TestPlanCatalog:
    def test_three_plans_are_defined_and_ordered(self) -> None:
        catalog = plan_catalog()
        assert [p["code"] for p in catalog] == ["starter", "growth", "enterprise"]

    def test_prices_are_positive_and_increasing(self) -> None:
        prices = [
            PLANS[c].price_inr for c in (PlanCode.STARTER, PlanCode.GROWTH, PlanCode.ENTERPRISE)
        ]
        assert all(p > 0 for p in prices)
        assert prices == sorted(prices)

    def test_documented_limits_match_the_specification(self) -> None:
        assert get_plan("starter").limits[Meter.CONTACTS] == 1_000
        assert get_plan("growth").limits[Meter.CONTACTS] == 10_000
        assert get_plan("enterprise").limits[Meter.CONTACTS] == UNLIMITED
        assert get_plan("starter").api_rate_per_minute == 300
        assert get_plan("growth").api_rate_per_minute == 1_000
        assert get_plan("enterprise").api_rate_per_minute == 5_000
        assert get_plan("starter").audit_retention_days == 90
        assert get_plan("enterprise").audit_retention_days == 2_555


class TestFeatureGating:
    def test_included_feature_is_allowed(self) -> None:
        assert check_feature("starter", Feature.WEBCHAT).allowed is True

    def test_excluded_feature_is_refused_with_an_upgrade_hint(self) -> None:
        decision = check_feature("starter", Feature.CUSTOM_ROLES)
        assert decision.allowed is False
        assert decision.code == "FEATURE_NOT_AVAILABLE"
        assert decision.detail["upgrade_available"] is True

    def test_an_externally_gated_feature_cannot_be_unlocked_by_an_upgrade_alone(self) -> None:
        decision = check_feature("starter", Feature.PAYMENTS)
        assert decision.allowed is False
        assert decision.detail["upgrade_available"] is False
        assert decision.detail["activation_prerequisite"]

    def test_flag_off_reports_the_external_activation_prerequisite(self) -> None:
        decision = check_feature("growth", Feature.WHATSAPP, flag_enabled=False)
        assert decision.allowed is False
        assert decision.detail["reason"] == "external_activation_pending"
        assert "template approval" in decision.detail["activation_prerequisite"]

    def test_tenant_override_can_disable_an_included_feature(self) -> None:
        decision = check_feature("enterprise", Feature.WORKFLOWS, tenant_override=False)
        assert decision.allowed is False
        assert decision.detail["reason"] == "tenant_override"

    def test_tenant_override_can_enable_a_plan_excluded_feature(self) -> None:
        assert check_feature("starter", Feature.PAYMENTS, tenant_override=True).allowed is True

    def test_voice_is_not_granted_by_any_plan(self) -> None:
        for code in PlanCode:
            assert Feature.VOICE not in get_plan(code).features

    def test_every_externally_gated_feature_documents_its_prerequisite(self) -> None:
        assert Feature.VOICE in EXTERNALLY_GATED
        assert all(text for text in EXTERNALLY_GATED.values())


class TestQuotaEnforcement:
    def test_under_limit_allows(self) -> None:
        assert check_quota("starter", Meter.CONTACTS, current=10).allowed is True

    def test_at_limit_blocks_the_next_unit(self) -> None:
        decision = check_quota("starter", Meter.CONTACTS, current=1_000)
        assert decision.allowed is False
        assert decision.code == "QUOTA_EXCEEDED"
        assert decision.detail["limit"] == 1_000

    def test_bulk_request_is_evaluated_as_a_whole(self) -> None:
        assert check_quota("starter", Meter.LEADS, current=990, requested=20).allowed is False
        assert check_quota("starter", Meter.LEADS, current=990, requested=10).allowed is True

    def test_unlimited_never_blocks(self) -> None:
        assert check_quota("enterprise", Meter.CONTACTS, current=10_000_000).allowed is True

    def test_override_limit_wins(self) -> None:
        assert (
            check_quota("starter", Meter.CONTACTS, current=5_000, override_limit=10_000).allowed
            is True
        )

    def test_eighty_percent_triggers_a_warning(self) -> None:
        assert quota_warning_threshold(800, 1_000) is True
        assert quota_warning_threshold(799, 1_000) is False
        assert quota_warning_threshold(10**9, UNLIMITED) is False

    @pytest.mark.parametrize("meter", list(Meter))
    def test_every_meter_is_defined_on_every_plan(self, meter: Meter) -> None:
        for code in PlanCode:
            assert meter in get_plan(code).limits
