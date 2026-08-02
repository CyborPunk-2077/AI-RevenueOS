from application.crm.inbox import channel_ready
from application.workflows.actions import AUDIT_ACTIONS, action_correlation
from domain.workflows.dsl import ACTION_CATALOG
from shared.settings import FeatureFlagDefaults, Settings


def test_retry_attempts_share_one_durable_action_receipt() -> None:
    assert action_correlation("execution:node:1") == action_correlation("execution:node:2")
    assert action_correlation("execution:node:1") != action_correlation("execution:other:1")


def test_every_action_is_dispatched_or_truthfully_external_gated() -> None:
    assert set(ACTION_CATALOG) - set(AUDIT_ACTIONS) == {
        "document.send",
        "payment.create_link",
        "payment.refund",
    }


def test_sms_has_an_independent_fail_closed_activation_gate() -> None:
    assert FeatureFlagDefaults.model_fields["sms_enabled"].default is False
    assert ACTION_CATALOG["message.send_sms"].feature_flag == "sms_enabled"


def test_a_flag_without_provider_credentials_does_not_report_ready() -> None:
    settings = Settings(
        features=FeatureFlagDefaults(
            whatsapp_enabled=True,
            email_enabled=True,
            voice_enabled=True,
            sms_enabled=True,
        )
    )
    assert channel_ready("whatsapp", settings) is False
    assert channel_ready("email", settings) is False
    assert channel_ready("voice", settings) is False
    assert channel_ready("sms", settings) is False
