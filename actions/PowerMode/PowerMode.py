"""StreamController action to toggle monitor power mode (on/standby)."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from ... import ddcutil
from ...action_base import MonitorActionMixin
from ...icons import BG_ACTIVE, BG_INACTIVE, COLOR_ACTIVE, COLOR_INACTIVE, tint_icon


class PowerMode(MonitorActionMixin, ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_polling()
        self.has_configuration = True
        self._prev_state: str | None = None
        self._icon_cache: dict[tuple[int, int, int, int], str] = {}
        self._cached_icon_path: str = os.path.join(
            self.plugin_base.PATH, "assets", "power-mode.png"
        )

    def _display(self) -> int:
        d = int(self.get_settings().get("display_number", 0))
        if d == 0:
            d = int(self.plugin_base.get_settings().get("default_display", 1))
        return d

    def _bin(self) -> str:
        return self.plugin_base.get_settings().get("ddcutil_path", "")

    def _get_tinted_icon(self, color: tuple[int, int, int, int]) -> str:
        if color not in self._icon_cache:
            tinted = tint_icon(self._cached_icon_path, color)
            self._icon_cache[color] = tinted if tinted else self._cached_icon_path
        return self._icon_cache[color]

    def on_ready(self):
        self.plugin_base.register_action(self)
        self._prev_state = None
        self._run_threaded(self._poll_display)

    def on_remove(self):
        self.plugin_base.unregister_action(self)

    def on_tick(self):
        if self._auto_poll_enabled() and self._should_poll():
            self._run_threaded(self._poll_display)

    def _poll_display(self):
        try:
            result = ddcutil.get_power(self._display(), self._bin())
            if result and result["current"] == ddcutil.POWER_ON:
                self._set_state("on")
            else:
                self._set_state("off")
            self._poll_done(success=True)
        except Exception:
            self._poll_done(success=False)

    def _set_state(self, state: str) -> None:
        if state == self._prev_state:
            return
        self._prev_state = state

        lm = self.plugin_base.lm
        if state == "on":
            self.set_media(media_path=self._get_tinted_icon(COLOR_ACTIVE), size=0.75)
            self.set_background_color(BG_ACTIVE)
            self.set_bottom_label(lm.get("power.on"), font_size=12)
        else:
            self.set_media(media_path=self._get_tinted_icon(COLOR_INACTIVE), size=0.75)
            self.set_background_color(BG_INACTIVE)
            self.set_bottom_label(lm.get("power.standby"), font_size=12)

    def event_callback(self, event, data):
        if event == Input.Key.Events.SHORT_UP:
            self._run_threaded(self._handle_toggle)

    def _handle_toggle(self):
        display, bp = self._display(), self._bin()
        result = ddcutil.get_power(display, bp)
        if result and result["current"] == ddcutil.POWER_ON:
            ddcutil.set_power(display, ddcutil.POWER_STANDBY, bp)
            self._set_state("off")
        else:
            ddcutil.set_power(display, ddcutil.POWER_ON, bp)
            self._set_state("on")
        self.plugin_base.refresh_all()

    def get_config_rows(self):
        lm = self.plugin_base.lm
        settings = self.get_settings()

        self.display_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.display_row.set_title(lm.get("power.display-number.title"))
        self.display_row.set_subtitle(lm.get("power.display-number.subtitle"))
        self.display_row.set_value(settings.get("display_number", 0))
        self.display_row.connect("changed", self._on_display_changed)

        self.auto_poll_row = Adw.SwitchRow(
            title=lm.get("settings.auto-poll.title"),
            subtitle=lm.get("settings.auto-poll.subtitle"),
        )
        self.auto_poll_row.set_active(
            settings.get("auto_poll", self._auto_poll_default)
        )
        self.auto_poll_row.connect("notify::active", self._on_auto_poll_changed)

        return [self.display_row, self.auto_poll_row]

    def _on_auto_poll_changed(self, switch, _):
        settings = self.get_settings()
        settings["auto_poll"] = switch.get_active()
        self.set_settings(settings)

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["display_number"] = int(spin.get_value())
        self.set_settings(settings)
