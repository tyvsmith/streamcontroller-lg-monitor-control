"""Regression tests for display-aware Dual Mode actions."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import ddcutil
import dual_mode_state
from monitor_profile import DualModeConfig, MonitorProfile

_ROOT = Path(__file__).parent.parent


def _package(monkeypatch, name):
    module = types.ModuleType(name)
    module.__path__ = []
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load_dual_mode(monkeypatch):
    class FakeMixin:
        pass

    class FakeActionBase:
        pass

    class FakeInput:
        class Key:
            class Events:
                SHORT_UP = object()

    gi = types.ModuleType("gi")
    gi.__path__ = []

    def require_version(*_args):
        pass

    gi.require_version = require_version
    repository = types.ModuleType("gi.repository")
    repository.Adw = object()
    gi.repository = repository
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    for package in (
        "src",
        "src.backend",
        "src.backend.DeckManagement",
        "src.backend.PluginManager",
        "test_plugin",
        "test_plugin.actions",
        "test_plugin.actions.DualMode",
    ):
        _package(monkeypatch, package)

    input_module = types.ModuleType("src.backend.DeckManagement.InputIdentifier")
    input_module.Input = FakeInput
    action_module = types.ModuleType("src.backend.PluginManager.ActionBase")
    action_module.ActionBase = FakeActionBase
    monkeypatch.setitem(
        sys.modules,
        "src.backend.DeckManagement.InputIdentifier",
        input_module,
    )
    monkeypatch.setitem(
        sys.modules, "src.backend.PluginManager.ActionBase", action_module
    )

    action_base = types.ModuleType("test_plugin.action_base")
    action_base.MonitorActionMixin = FakeMixin
    icons = types.ModuleType("test_plugin.icons")
    icons.BG_ACTIVE = (0, 0, 0, 0)
    icons.BG_INACTIVE = (0, 0, 0, 0)
    icons.COLOR_ACTIVE = (0, 0, 0, 0)
    icons.COLOR_INACTIVE = (0, 0, 0, 0)
    icons.tint_icon = Mock(return_value=None)
    monkeypatch.setitem(sys.modules, "test_plugin.ddcutil", ddcutil)
    monkeypatch.setitem(sys.modules, "test_plugin.dual_mode_state", dual_mode_state)
    monkeypatch.setitem(sys.modules, "test_plugin.action_base", action_base)
    monkeypatch.setitem(sys.modules, "test_plugin.icons", icons)

    path = _ROOT / "actions" / "DualMode" / "DualMode.py"
    spec = importlib.util.spec_from_file_location(
        "test_plugin.actions.DualMode.DualMode", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_toggle_updates_only_the_selected_display(monkeypatch):
    module = _load_dual_mode(monkeypatch)
    profile = MonitorProfile(
        dual_mode=DualModeConfig(
            vcp=0xB1,
            on=0x2100,
            off=0x2200,
            on_label="ON",
            off_label="OFF",
        )
    )
    writes = []
    monkeypatch.setattr(module.ddcutil, "profile_for", lambda *_args: profile)
    monkeypatch.setattr(
        module.ddcutil,
        "set_dual_mode",
        lambda display, enabled, path: writes.append((display, enabled, path)) or True,
    )

    class Plugin:
        def __init__(self):
            self.dual_mode_active = {"1": False, "2": True}
            self.state_writes = []
            self.lm = types.SimpleNamespace(get=lambda key: key)

        def set_dual_mode_active(self, *args):
            self.state_writes.append(args)
            if len(args) == 2:
                display, active = args
                self.dual_mode_active[str(display)] = active

        def refresh_all(self):
            pass

    plugin = Plugin()
    action = object.__new__(module.DualMode)
    action.plugin_base = plugin
    action._display = Mock(return_value=1)
    action._bin = Mock(return_value="")
    action._prev_state = None
    action._get_tinted_icon = Mock(return_value="icon")
    action.set_media = Mock()
    action.set_background_color = Mock()
    action.set_bottom_label = Mock()

    action._handle_toggle()

    assert writes == [(1, True, "")]
    assert plugin.state_writes == [(1, True)]
    assert plugin.dual_mode_active == {"1": True, "2": True}
