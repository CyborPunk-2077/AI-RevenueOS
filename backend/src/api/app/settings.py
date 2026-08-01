"""Re-export of the shared settings module for the API layer.

The definition lives in `shared.settings`: application services, infrastructure
adapters and workers all depend on configuration, and importing it from `api`
would invert the mandated layering.
"""

from __future__ import annotations

from shared.settings import (
    Environment,
    FeatureFlagDefaults,
    Settings,
    get_settings,
)

__all__ = ["Environment", "FeatureFlagDefaults", "Settings", "get_settings"]
