"""Razorpay adapter wiring."""

from __future__ import annotations

from functools import lru_cache

from infrastructure.integrations.razorpay import RazorpayAdapter
from shared.settings import Settings, get_settings


@lru_cache(maxsize=1)
def get_razorpay_adapter(settings: Settings | None = None) -> RazorpayAdapter:
    cfg = settings or get_settings()
    return RazorpayAdapter(
        key_id=cfg.razorpay_key_id,
        key_secret=cfg.razorpay_key_secret,
        webhook_secret=cfg.razorpay_webhook_secret,
        enabled=cfg.features.payments_enabled,
    )
