# PR 5 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all three inline review comments on PR 5 without expanding into the optional docstring or Input Switch follow-ups.

**Architecture:** Keep Dual Mode profile validation in `monitor_profile.py` and enforce the same boundary in `ddcutil.py`. Put JSON-safe per-display state transformations in a small pure module, then have the plugin persist that mapping and the action resolve its display before every read and write.

**Tech Stack:** Python 3.11, dataclasses, TOML, pytest, unittest.mock, Ruff, Pyright

---

### Task 1: Reject incomplete Dual Mode profiles

**Files:**
- Modify: `tests/test_monitor_profile.py`
- Modify: `tests/test_ddcutil.py`
- Modify: `monitor_profile.py:42-83`
- Modify: `monitor_profile.py:138-145`
- Modify: `ddcutil.py:338-355`

- [ ] **Step 1: Write failing profile-loader tests**

Add these methods to `TestLoadToml` in `tests/test_monitor_profile.py`:

```python
    def test_dual_mode_missing_on_is_unsupported(self, tmp_path):
        path = tmp_path / "missing-on.toml"
        path.write_text(
            '[monitor]\nname = "Incomplete"\n\n'
            "[dual_mode]\nvcp = 0xB1\noff = 0x2200\n",
            encoding="utf-8",
        )

        p = _load_toml(path)

        assert p.dual_mode.on is None
        assert p.has_dual_mode is False

    def test_dual_mode_missing_off_is_unsupported(self, tmp_path):
        path = tmp_path / "missing-off.toml"
        path.write_text(
            '[monitor]\nname = "Incomplete"\n\n'
            "[dual_mode]\nvcp = 0xB1\non = 0x2100\n",
            encoding="utf-8",
        )

        p = _load_toml(path)

        assert p.dual_mode.off is None
        assert p.has_dual_mode is False
```

- [ ] **Step 2: Run the loader tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_monitor_profile.py::TestLoadToml::test_dual_mode_missing_on_is_unsupported tests/test_monitor_profile.py::TestLoadToml::test_dual_mode_missing_off_is_unsupported -v
```

Expected: both tests fail because missing values currently load as `0` and `has_dual_mode` only checks `vcp`.

- [ ] **Step 3: Write a failing DDC boundary test**

Add this method to `TestDualMode` in `tests/test_ddcutil.py`:

```python
    @patch("ddcutil.profile_for")
    @patch("ddcutil.setvcp")
    def test_set_dual_mode_incomplete_profile(self, mock_setvcp, mock_profile):
        mock_profile.return_value = MonitorProfile(
            dual_mode=DualModeConfig(vcp=0xB1, on=None, off=0x2200)
        )

        assert set_dual_mode(1, True) is False
        mock_setvcp.assert_not_called()
```

- [ ] **Step 4: Run the DDC test and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_ddcutil.py::TestDualMode::test_set_dual_mode_incomplete_profile -v
```

Expected: fail because the incomplete profile is currently treated as supported and `setvcp()` is called.

- [ ] **Step 5: Implement optional values and availability validation**

Change `DualModeConfig` and `MonitorProfile.has_dual_mode` in `monitor_profile.py` to:

```python
@dataclass
class DualModeConfig:
    vcp: int = 0
    i2c_source_addr: str = ""
    on: int | None = None
    off: int | None = None
    on_label: str = ""
    off_label: str = ""


@property
def has_dual_mode(self) -> bool:
    return (
        self.dual_mode.vcp != 0
        and self.dual_mode.on is not None
        and self.dual_mode.off is not None
    )
```

Change the `_load_toml()` construction to preserve missing values:

```python
        dual_mode=DualModeConfig(
            vcp=dual.get("vcp", 0),
            i2c_source_addr=dual.get("i2c_source_addr", ""),
            on=dual.get("on"),
            off=dual.get("off"),
            on_label=dual.get("on_label", ""),
            off_label=dual.get("off_label", ""),
        ),
```

In `ddcutil.set_dual_mode()`, select and validate the value before `setvcp()`:

```python
    p = profile_for(display, bin_path)
    if not p.has_dual_mode:
        return False
    value = p.dual_mode.on if enabled else p.dual_mode.off
    if value is None:
        return False
    return setvcp(
        display,
        p.dual_mode.vcp,
        value,
        bin_path,
        src_addr=p.dual_mode.i2c_source_addr,
        permit_unknown=True,
    )
```

- [ ] **Step 6: Run focused and related tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_monitor_profile.py tests/test_ddcutil.py::TestDualMode -v
```

Expected: all selected tests pass, including the existing complete-profile on/off tests.

- [ ] **Step 7: Commit the profile fix**

```bash
git add monitor_profile.py ddcutil.py tests/test_monitor_profile.py tests/test_ddcutil.py
git commit --no-gpg-sign -m "fix: reject incomplete dual mode profiles"
```

### Task 2: Add JSON-safe per-display state transformations

**Files:**
- Create: `dual_mode_state.py`
- Create: `tests/test_dual_mode_state.py`

- [ ] **Step 1: Write failing state regression tests**

Create `tests/test_dual_mode_state.py` with:

```python
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

    settings = state.update_dual_mode_settings(
        settings, first_action_display, True
    )

    states = state.normalize_dual_mode_states(settings["dual_mode_active"])
    assert state.is_dual_mode_active(states, first_action_display) is True
    assert state.is_dual_mode_active(states, second_action_display) is False
    assert settings["dual_mode_active"] == {"1": True}


def test_state_update_preserves_another_display():
    state = _state_module()
    settings: dict[str, object] = {"dual_mode_active": {"1": True}}

    settings = state.update_dual_mode_settings(settings, 2, False)

    assert settings["dual_mode_active"] == {"1": True, "2": False}
```

- [ ] **Step 2: Run state tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_dual_mode_state.py -v
```

Expected: three test failures stating that `dual_mode_state` is not implemented.

- [ ] **Step 3: Implement the pure state API**

Create `dual_mode_state.py` with:

```python
"""JSON-safe helpers for persisted per-display Dual Mode state."""

from collections.abc import Mapping

_SETTINGS_KEY = "dual_mode_active"


def normalize_dual_mode_states(raw: object) -> dict[str, bool]:
    """Return valid display-state pairs from persisted settings."""
    if not isinstance(raw, dict):
        return {}
    return {str(display): active for display, active in raw.items() if isinstance(active, bool)}


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
```

Format the comprehension if Ruff requests wrapping; do not change behavior.

- [ ] **Step 4: Run state tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_dual_mode_state.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit the state API**

```bash
git add dual_mode_state.py tests/test_dual_mode_state.py
git commit --no-gpg-sign -m "feat: add per-display dual mode state"
```

### Task 3: Wire actions to the resolved display and remove test duplication

**Files:**
- Create: `tests/test_dual_mode_action.py`
- Modify: `main.py:73-76`
- Modify: `main.py:187-191`
- Modify: `actions/DualMode/DualMode.py:14-18`
- Modify: `actions/DualMode/DualMode.py:72-118`
- Modify: `tests/test_monitor_profile.py:42-51`

- [ ] **Step 1: Write a failing action regression test**

Create `tests/test_dual_mode_action.py`. Load the action beneath a synthetic plugin package because StreamController and GTK imports exist only in the Flatpak runtime:

```python
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

    def require_version(*_args):
        pass

    gi.require_version = require_version
    repository = types.ModuleType("gi.repository")
    repository.Adw = object()
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

    input_module = types.ModuleType(
        "src.backend.DeckManagement.InputIdentifier"
    )
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
    monkeypatch.setitem(
        sys.modules, "test_plugin.dual_mode_state", dual_mode_state
    )
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
        lambda display, enabled, path: writes.append((display, enabled, path))
        or True,
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
```

- [ ] **Step 2: Run the action regression test and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_dual_mode_action.py -v
```

Expected: fail because the current action negates the entire dictionary and calls `set_dual_mode_active()` without a display number.

- [ ] **Step 3: Load and persist the normalized mapping in the plugin**

Import the state functions in `main.py`:

```python
from .dual_mode_state import (
    normalize_dual_mode_states,
    update_dual_mode_settings,
)
```

Replace initialization with:

```python
        self.dual_mode_active: dict[str, bool] = normalize_dual_mode_states(
            self.get_settings().get("dual_mode_active")
        )
```

Replace the setter with:

```python
    def set_dual_mode_active(self, display: int, active: bool) -> None:
        settings = update_dual_mode_settings(self.get_settings(), display, active)
        self.dual_mode_active = normalize_dual_mode_states(
            settings["dual_mode_active"]
        )
        self.set_settings(settings)
```

- [ ] **Step 4: Make the action read and write the selected display**

Import the read helper in `actions/DualMode/DualMode.py`:

```python
from ...dual_mode_state import is_dual_mode_active
```

Resolve `display` once in `_update_display()` and use it for both profile and state lookup:

```python
        display = self._display()
        p = ddcutil.profile_for(display, self._bin())

        if not p.has_dual_mode:
            active = False
            label = lm.get("status.unknown")
        elif is_dual_mode_active(self.plugin_base.dual_mode_active, display):
            active = True
            label = p.dual_mode.on_label or lm.get("dual-mode.on")
        else:
            active = False
            label = p.dual_mode.off_label or lm.get("dual-mode.off")
```

Compute and persist the selected display in `_handle_toggle()`:

```python
        enabled = not is_dual_mode_active(
            self.plugin_base.dual_mode_active, display
        )
        if ddcutil.set_dual_mode(display, enabled, bp):
            self.plugin_base.set_dual_mode_active(display, enabled)
```

- [ ] **Step 5: Remove the duplicate assertion**

In `tests/test_monitor_profile.py`, leave exactly one copy of:

```python
        assert p.has_dual_mode is False
```

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_dual_mode_action.py tests/test_dual_mode_state.py tests/test_monitor_profile.py tests/test_ddcutil.py::TestDualMode -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the action integration**

```bash
git add main.py actions/DualMode/DualMode.py tests/test_dual_mode_action.py tests/test_monitor_profile.py
git commit --no-gpg-sign -m "fix: isolate dual mode state by display"
```

### Task 4: Full verification and cache cleanup

**Files:**
- Verify all modified files
- Remove generated `__pycache__` directories

- [ ] **Step 1: Run the complete test and static-check suite**

Run:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
git diff --check origin/main...HEAD
```

Expected: all tests pass, Ruff reports no issues and no formatting changes, Pyright reports zero errors, and `git diff --check` exits successfully.

- [ ] **Step 2: Clear StreamController bytecode caches**

Run:

```bash
find . -type d -name __pycache__ -exec rm -rf {} +
```

Expected: all generated plugin and test bytecode directories are removed without changing tracked files.

- [ ] **Step 3: Confirm final repository state**

Run:

```bash
git status --short
git log -5 --oneline --decorate
```

Expected: only the pre-existing untracked `.omc/` directory remains; the review fixes and their tests are committed on `feat/dual-mode`.
