"""Feature-flag registry for per-tenant capability toggles (DDS §2 feature_flag).

Flags are validated against this registry — no freeform keys (DMS #5).
``DEFAULT_ENABLED_FLAGS`` is the enablement set applied at provisioning.
"""

from __future__ import annotations

# registry key -> human label
FEATURE_FLAG_REGISTRY: dict[str, str] = {
    "bookings": "Online bookings",
    "payments": "Card payments",
    "channel_manager": "Channel manager sync",
}

DEFAULT_ENABLED_FLAGS: frozenset[str] = frozenset({"bookings", "payments"})


def is_valid_flag(flag_key: str) -> bool:
    return flag_key in FEATURE_FLAG_REGISTRY
