"""JSON-safe helpers for persisted per-display Dual Mode state."""

from collections.abc import Mapping

_SETTINGS_KEY = "dual_mode_active"


def normalize_dual_mode_states(raw: object) -> dict[str, bool]:
    """Return valid display-state pairs from persisted settings."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(display): active
        for display, active in raw.items()
        if isinstance(active, bool)
    }


def is_dual_mode_active(states: Mapping[str, bool], display: int) -> bool:
    """Return the tracked Dual Mode state for one ddcutil display."""
    return states.get(str(display), False)


def update_dual_mode_settings(
    settings: Mapping[str, object], display: int, active: bool
) -> dict[str, object]:
    """Return settings with one display's tracked state updated."""
    updated = dict(settings)
    states = normalize_dual_mode_states(updated.get(_SETTINGS_KEY))
    states[str(display)] = active
    updated[_SETTINGS_KEY] = states
    return updated
