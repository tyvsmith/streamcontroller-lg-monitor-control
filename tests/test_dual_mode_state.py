"""Tests for persisted per-display Dual Mode state."""

import importlib

import pytest


def _state_module():
    try:
        return importlib.import_module("dual_mode_state")
    except ModuleNotFoundError:
        pytest.fail("dual_mode_state module is not implemented")


def test_legacy_boolean_state_is_ignored():
    state = _state_module()

    assert state.normalize_dual_mode_states(True) == {}


def test_two_actions_keep_display_state_independent():
    state = _state_module()
    first_action_display = 1
    second_action_display = 2
    settings: dict[str, object] = {}

    settings = state.update_dual_mode_settings(settings, first_action_display, True)

    states = state.normalize_dual_mode_states(settings["dual_mode_active"])
    assert state.is_dual_mode_active(states, first_action_display) is True
    assert state.is_dual_mode_active(states, second_action_display) is False
    assert settings["dual_mode_active"] == {"1": True}


def test_state_update_preserves_another_display():
    state = _state_module()
    settings: dict[str, object] = {"dual_mode_active": {"1": True}}

    settings = state.update_dual_mode_settings(settings, 2, False)

    assert settings["dual_mode_active"] == {"1": True, "2": False}
