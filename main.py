"""StreamController plugin for LG monitor controls — input switching, PBP, brightness, and volume."""

import json
import logging
import os
import queue
import threading

import gi

log = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

try:
    from src.Signals.Signals import AppQuit
    import globals as gl

    _HAS_SIGNALS = True
except ImportError:
    _HAS_SIGNALS = False

from .actions.BlackStabilizer.BlackStabilizer import BlackStabilizer
from .actions.Brightness.Brightness import Brightness
from .actions.Contrast.Contrast import Contrast
from .actions.InputSwitch.InputSwitch import InputSwitch
from .actions.PbpMode.PbpMode import PbpMode
from .actions.PowerMode.PowerMode import PowerMode
from .actions.Sharpness.Sharpness import Sharpness
from .actions.Volume.Volume import Volume
from . import ddcutil as _ddcutil_mod


def _load_manifest() -> dict:
    """Load manifest.json from the plugin directory."""
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


_MANIFEST = _load_manifest()

_KEY_ONLY = {
    Input.Key: ActionInputSupport.SUPPORTED,
    Input.Dial: ActionInputSupport.UNSUPPORTED,
    Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
}

_KEY_AND_DIAL = {
    Input.Key: ActionInputSupport.SUPPORTED,
    Input.Dial: ActionInputSupport.SUPPORTED,
    Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
}


class LgMonitorControls(PluginBase):
    def __init__(self):
        super().__init__()
        _ddcutil_mod.reset()
        self._ddcutil_available: bool = _ddcutil_mod.is_available()
        if not self._ddcutil_available:
            log.warning("ddcutil binary not found — monitor controls will not work")

        self.lm = self.locale_manager
        self.lm.set_to_os_default()
        self.lm.set_fallback_language("en_US")

        self.last_input: int | None = self.get_settings().get("last_input")
        self._active_actions: list = []
        self._refresh_lock = threading.Lock()
        self._work_queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        self.input_switch_holder = ActionHolder(
            plugin_base=self,
            action_base=InputSwitch,
            action_id_suffix="InputSwitch",
            action_name=self.lm.get("actions.input-switch.name"),
            action_support=_KEY_ONLY,
        )
        self.add_action_holder(self.input_switch_holder)

        self.pbp_mode_holder = ActionHolder(
            plugin_base=self,
            action_base=PbpMode,
            action_id_suffix="PbpMode",
            action_name=self.lm.get("actions.pbp-mode.name"),
            action_support=_KEY_ONLY,
        )
        self.add_action_holder(self.pbp_mode_holder)

        self.brightness_holder = ActionHolder(
            plugin_base=self,
            action_base=Brightness,
            action_id_suffix="Brightness",
            action_name=self.lm.get("actions.brightness.name"),
            action_support=_KEY_AND_DIAL,
        )
        self.add_action_holder(self.brightness_holder)

        self.volume_holder = ActionHolder(
            plugin_base=self,
            action_base=Volume,
            action_id_suffix="Volume",
            action_name=self.lm.get("actions.volume.name"),
            action_support=_KEY_AND_DIAL,
        )
        self.add_action_holder(self.volume_holder)

        self.contrast_holder = ActionHolder(
            plugin_base=self,
            action_base=Contrast,
            action_id_suffix="Contrast",
            action_name=self.lm.get("actions.contrast.name"),
            action_support=_KEY_AND_DIAL,
        )
        self.add_action_holder(self.contrast_holder)

        self.sharpness_holder = ActionHolder(
            plugin_base=self,
            action_base=Sharpness,
            action_id_suffix="Sharpness",
            action_name=self.lm.get("actions.sharpness.name"),
            action_support=_KEY_AND_DIAL,
        )
        self.add_action_holder(self.sharpness_holder)

        self.black_stabilizer_holder = ActionHolder(
            plugin_base=self,
            action_base=BlackStabilizer,
            action_id_suffix="BlackStabilizer",
            action_name=self.lm.get("actions.black-stabilizer.name"),
            action_support=_KEY_AND_DIAL,
        )
        self.add_action_holder(self.black_stabilizer_holder)

        self.power_mode_holder = ActionHolder(
            plugin_base=self,
            action_base=PowerMode,
            action_id_suffix="PowerMode",
            action_name=self.lm.get("actions.power-mode.name"),
            action_support=_KEY_ONLY,
        )
        self.add_action_holder(self.power_mode_holder)

        self.register(
            plugin_name=self.lm.get("plugin.name"),
            github_repo=_MANIFEST["github"],
            plugin_version=_MANIFEST["version"],
            app_version=_MANIFEST["app-version"],
        )

        if _HAS_SIGNALS:
            try:
                gl.signal_manager.connect_signal(AppQuit, self._on_app_quit)
            except Exception:
                log.debug("Could not register AppQuit handler", exc_info=True)

    def set_last_input(self, input_code: int | None) -> None:
        self.last_input = input_code
        settings = self.get_settings()
        settings["last_input"] = input_code
        self.set_settings(settings)

    # --- Worker queue ---

    def _worker_loop(self) -> None:
        """Single worker thread that drains the work queue."""
        while not self._stop.is_set():
            try:
                fn, args = self._work_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._stop.is_set():
                break
            try:
                fn(*args)
            except Exception:
                log.debug("Worker task failed: %s", fn.__name__, exc_info=True)

    def enqueue(self, fn, *args) -> None:
        """Submit work to the shared worker thread."""
        if not self._stop.is_set():
            self._work_queue.put((fn, args))

    def _on_app_quit(self, *args) -> None:
        """Clean shutdown: stop worker, kill in-flight subprocess."""
        from . import ddcutil

        self._stop.set()
        ddcutil.shutdown()
        # Drain remaining items
        while not self._work_queue.empty():
            try:
                self._work_queue.get_nowait()
            except queue.Empty:
                break
        self._worker.join(timeout=2.0)

    # --- Action registry for cross-action refresh ---

    def register_action(self, action) -> None:
        with self._refresh_lock:
            if action not in self._active_actions:
                self._active_actions.append(action)

    def unregister_action(self, action) -> None:
        with self._refresh_lock:
            try:
                self._active_actions.remove(action)
            except ValueError:
                pass

    def refresh_all(self) -> None:
        """Enqueue a refresh of all active actions."""
        self.enqueue(self._do_refresh_all)

    def _do_refresh_all(self) -> None:
        with self._refresh_lock:
            actions = list(self._active_actions)
        for action in actions:
            try:
                action._poll_display()
            except Exception:
                log.debug("Refresh failed for %s", type(action).__name__, exc_info=True)

    # --- Plugin-level settings UI ---

    def get_settings_area(self):
        group = Adw.PreferencesGroup(
            title=self.lm.get("plugin.name"),
            description=self.lm.get("settings.description"),
        )

        if not self._ddcutil_available:
            warning_row = Adw.ActionRow(
                title=self.lm.get("warning.ddcutil-missing.title"),
                subtitle=self.lm.get("warning.ddcutil-missing.description"),
                icon_name="dialog-warning-symbolic",
            )
            warning_row.add_css_class("error")
            group.add(warning_row)

        self._display_row = Adw.SpinRow.new_with_range(1, 10, 1)
        self._display_row.set_title(self.lm.get("settings.display-number.title"))

        self._ddcutil_path_row = Adw.EntryRow(
            title=self.lm.get("settings.ddcutil-path.title"),
        )

        settings = self.get_settings()
        self._display_row.set_value(settings.get("default_display", 1))
        self._ddcutil_path_row.set_text(settings.get("ddcutil_path", ""))

        self._display_row.connect("changed", self._on_display_changed)
        self._ddcutil_path_row.connect("notify::text", self._on_path_changed)

        self._poll_interval_row = Adw.SpinRow.new_with_range(5, 300, 5)
        self._poll_interval_row.set_title(self.lm.get("settings.poll-interval.title"))
        self._poll_interval_row.set_subtitle(
            self.lm.get("settings.poll-interval.subtitle")
        )
        self._poll_interval_row.set_value(settings.get("poll_interval", 30))
        self._poll_interval_row.connect("changed", self._on_poll_interval_changed)

        group.add(self._display_row)
        group.add(self._ddcutil_path_row)
        group.add(self._poll_interval_row)

        return group

    def get_poll_interval(self) -> float:
        return float(self.get_settings().get("poll_interval", 30))

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["default_display"] = int(spin.get_value())
        self.set_settings(settings)

    def _on_path_changed(self, entry, _):
        settings = self.get_settings()
        settings["ddcutil_path"] = entry.get_text()
        self.set_settings(settings)

    def _on_poll_interval_changed(self, spin):
        settings = self.get_settings()
        settings["poll_interval"] = int(spin.get_value())
        self.set_settings(settings)
