"""Channel adapter wiring. Every adapter reports its own activation gate."""

from __future__ import annotations

from infrastructure.integrations.email import EmailAdapter
from infrastructure.integrations.voice import VoiceAdapter
from infrastructure.integrations.whatsapp import WhatsAppAdapter
from shared.settings import Settings, get_settings


def get_whatsapp_adapter(settings: Settings | None = None) -> WhatsAppAdapter:
    cfg = settings or get_settings()
    return WhatsAppAdapter(
        phone_number_id=cfg.whatsapp_phone_number_id,
        access_token=cfg.whatsapp_access_token,
        app_secret=cfg.whatsapp_app_secret,
        verify_token=cfg.whatsapp_verify_token,
        enabled=cfg.features.whatsapp_enabled,
    )


def get_email_adapter(settings: Settings | None = None) -> EmailAdapter:
    cfg = settings or get_settings()
    return EmailAdapter(
        provider=cfg.email_provider,
        api_key=cfg.email_api_key,
        from_address=cfg.email_from_address,
        enabled=cfg.features.email_enabled,
    )


def get_voice_adapter(settings: Settings | None = None) -> VoiceAdapter:
    cfg = settings or get_settings()
    return VoiceAdapter(provider=cfg.voice_provider, enabled=cfg.features.voice_enabled)


def channel_activation_report() -> dict[str, object]:
    """Surfaced in settings and in the GA activation checklist."""
    return {
        "whatsapp": get_whatsapp_adapter().activation_status(),
        "email": get_email_adapter().activation_status(),
        "voice": get_voice_adapter().activation_status(),
    }
