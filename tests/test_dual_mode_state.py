"""Tests for persisted per-display Dual Mode state."""

from dual_mode_state import (
    is_dual_mode_active,
    normalize_dual_mode_states,
    update_dual_mode_settings,
)


def test_legacy_boolean_state_is_ignored():
    assert normalize_dual_mode_states(True) == {}


def test_two_actions_keep_display_state_independent():
    first_action_display = 1
    second_action_display = 2
    settings: dict[str, object] = {}

    settings = update_dual_mode_settings(settings, first_action_display, True)

    states = normalize_dual_mode_states(settings["dual_mode_active"])
    assert is_dual_mode_active(states, first_action_display) is True
    assert is_dual_mode_active(states, second_action_display) is False
    assert settings["dual_mode_active"] == {"1": True}


def test_state_update_preserves_another_display():
    settings: dict[str, object] = {"dual_mode_active": {"1": True}}

    settings = update_dual_mode_settings(settings, 2, False)

    assert settings["dual_mode_active"] == {"1": True, "2": False}
