"""Voice adapter - HARD DISABLED.

EXTERNAL GATE: telecom provider (Exotel/Twilio), number ownership, recording and
consent disclosure copy, escalation path, concurrency budget and legal sign-off are
all unresolved. Every entry point refuses until `VoiceControls.all_signed_off()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from application.ports import ProviderResult, VoicePort

ACTIVATION_PREREQUISITE = (
    "Telecom provider agreement, number ownership, legal-approved recording and "
    "disclosure copy, DPDP consent flow, defined human escalation path, concurrency "
    "and spend budget, and written legal/compliance sign-off."
)


@dataclass(frozen=True, slots=True)
class VoiceControls:
    """Every control must be independently signed off before voice can be enabled."""

    disclosure_copy_approved: bool = False
    recording_consent_flow_approved: bool = False
    escalation_path_defined: bool = False
    concurrency_limit_set: bool = False
    budget_limit_set: bool = False
    legal_signoff: bool = False
    provider_contracted: bool = False

    def outstanding(self) -> list[str]:
        return (
            [name for name, value in self.__dict__.items() if value is not True]
            if False
            else [
                name
                for name in (
                    "disclosure_copy_approved",
                    "recording_consent_flow_approved",
                    "escalation_path_defined",
                    "concurrency_limit_set",
                    "budget_limit_set",
                    "legal_signoff",
                    "provider_contracted",
                )
                if not getattr(self, name)
            ]
        )

    def all_signed_off(self) -> bool:
        return not self.outstanding()


class VoiceAdapter(VoicePort):
    provider = "none"

    def __init__(
        self,
        *,
        provider: str = "none",
        enabled: bool = False,
        controls: VoiceControls | None = None,
    ) -> None:
        self.provider = provider
        self._enabled = enabled
        self._controls = controls or VoiceControls()

    def is_configured(self) -> bool:
        """False until every control is signed off - the flag alone is not enough."""
        return bool(self._enabled and self.provider != "none" and self._controls.all_signed_off())

    def activation_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled_flag": self._enabled,
            "configured": self.is_configured(),
            "outstanding_controls": self._controls.outstanding(),
            "decision_gate": "Legal: recording/voice disclosures and DPDP consent",
            "activation_prerequisite": ACTIVATION_PREREQUISITE,
        }

    async def place_call(self, *, tenant_id: UUID, payload: dict[str, Any]) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="place_call",
                error_code="FEATURE_NOT_AVAILABLE",
                error_message="Voice is disabled pending consent, disclosure and legal sign-off.",
                raw=self.activation_status(),
            )
        raise NotImplementedError(
            "the concrete telecom client is implemented once the provider decision is recorded"
        )
