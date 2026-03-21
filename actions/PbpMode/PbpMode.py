"""StreamController action to toggle PBP (Picture-by-Picture) mode on LG monitors."""

import logging
import os

import gi

log = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from ... import ddcutil
from ...action_base import MonitorActionMixin
from ...icons import BG_ACTIVE, BG_INACTIVE, COLOR_ACTIVE, COLOR_INACTIVE, tint_icon

_INPUT_CHOICES = [
    (ddcutil.LG_INPUT_DP, "input.dp"),
    (ddcutil.LG_INPUT_USBC, "input.usbc"),
    (ddcutil.LG_INPUT_HDMI1, "input.hdmi1"),
    (ddcutil.LG_INPUT_HDMI2, "input.hdmi2"),
]

_INPUT_CODES = [code for code, _ in _INPUT_CHOICES]


class PbpMode(MonitorActionMixin, ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_polling()
        self.has_configuration = True
        self._prev_state: str | None = None  # "on" | "off" | None
        self._icon_cache: dict[tuple[int, int, int, int], str] = {}
        self._cached_icon_path: str = os.path.join(
            self.plugin_base.PATH, "assets", "pbp-mode.png"
        )

    def _display(self) -> int:
        d = int(self.get_settings().get("display_number", 0))
        if d == 0:
            d = int(self.plugin_base.get_settings().get("default_display", 1))
        return d

    def _bin(self) -> str:
        return self.plugin_base.get_settings().get("ddcutil_path", "")

    def _left_input(self) -> int:
        return int(self.get_settings().get("left_input", ddcutil.LG_INPUT_DP))

    def _right_input(self) -> int:
        return int(self.get_settings().get("right_input", ddcutil.LG_INPUT_USBC))

    def _return_input(self) -> int:
        return int(self.get_settings().get("return_input", ddcutil.LG_INPUT_DP))

    def _get_tinted_icon(self, color: tuple[int, int, int, int]) -> str:
        if color not in self._icon_cache:
            tinted = tint_icon(self._cached_icon_path, color)
            self._icon_cache[color] = tinted if tinted else self._cached_icon_path
        return self._icon_cache[color]

    def on_ready(self):
        self.plugin_base.register_action(self)
        self._prev_state = None
        self._run_threaded(self._poll_display)

    def on_tick(self):
        if self._auto_poll_enabled() and self._should_poll():
            self._run_threaded(self._poll_display)

    def _poll_display(self):
        """Read PBP state from monitor and update UI."""
        try:
            display = self._display()
            bp = self._bin()
            pbp = ddcutil.get_pbp(display, bp)
            if pbp and pbp["current"] != ddcutil.PBP_NONE:
                self._set_state("on")
            else:
                self._set_state("off")
            self._poll_done(success=True)
        except Exception:
            log.debug("Poll failed for PbpMode", exc_info=True)
            self._poll_done(success=False)

    def _set_state(self, state: str) -> None:
        """Update UI to reflect the given state without reading from monitor."""
        if state == self._prev_state:
            return
        self._prev_state = state

        left_name = ddcutil.INPUT_NAMES.get(self._left_input(), "?")
        right_name = ddcutil.INPUT_NAMES.get(self._right_input(), "?")
        label = f"{left_name} | {right_name}"

        if state == "on":
            self.set_media(media_path=self._get_tinted_icon(COLOR_ACTIVE), size=0.75)
            self.set_background_color(BG_ACTIVE)
        else:
            self.set_media(media_path=self._get_tinted_icon(COLOR_INACTIVE), size=0.75)
            self.set_background_color(BG_INACTIVE)
        self.set_bottom_label(label, font_size=10)

    def event_callback(self, event, data):
        if event == Input.Key.Events.SHORT_UP:
            self._run_threaded(self._handle_toggle)

    def _handle_toggle(self):
        display = self._display()
        bp = self._bin()

        pbp = ddcutil.get_pbp(display, bp)
        if pbp and pbp["current"] != ddcutil.PBP_NONE:
            return_input = self._return_input()
            ddcutil.switch_input(display, return_input, bp)
            ddcutil.disable_pbp(display, bp)
            self.plugin_base.last_input = return_input
            self._set_state("off")
        else:
            ddcutil.set_pbp(display, self._left_input(), self._right_input(), bp)
            self.plugin_base.last_input = None
            self._set_state("on")
        self.plugin_base.refresh_all()

    # --- Configuration UI ---

    def get_config_rows(self):
        lm = self.plugin_base.lm
        settings = self.get_settings()

        self.left_model = Gtk.StringList()
        for _, locale_key in _INPUT_CHOICES:
            self.left_model.append(lm.get(locale_key))

        self.left_row = Adw.ComboRow(
            title=lm.get("pbp-mode.left-input.title"),
            model=self.left_model,
        )
        current_left = int(settings.get("left_input", ddcutil.LG_INPUT_DP))
        if current_left in _INPUT_CODES:
            self.left_row.set_selected(_INPUT_CODES.index(current_left))
        self.left_row.connect("notify::selected", self._on_left_changed)

        self.right_model = Gtk.StringList()
        for _, locale_key in _INPUT_CHOICES:
            self.right_model.append(lm.get(locale_key))

        self.right_row = Adw.ComboRow(
            title=lm.get("pbp-mode.right-input.title"),
            model=self.right_model,
        )
        current_right = int(settings.get("right_input", ddcutil.LG_INPUT_USBC))
        if current_right in _INPUT_CODES:
            self.right_row.set_selected(_INPUT_CODES.index(current_right))
        self.right_row.connect("notify::selected", self._on_right_changed)

        self.return_model = Gtk.StringList()
        for _, locale_key in _INPUT_CHOICES:
            self.return_model.append(lm.get(locale_key))

        self.return_row = Adw.ComboRow(
            title=lm.get("pbp-mode.return-input.title"),
            subtitle=lm.get("pbp-mode.return-input.subtitle"),
            model=self.return_model,
        )
        current_return = int(settings.get("return_input", ddcutil.LG_INPUT_DP))
        if current_return in _INPUT_CODES:
            self.return_row.set_selected(_INPUT_CODES.index(current_return))
        self.return_row.connect("notify::selected", self._on_return_changed)

        self.display_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.display_row.set_title(lm.get("pbp-mode.display-number.title"))
        self.display_row.set_subtitle(lm.get("pbp-mode.display-number.subtitle"))
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

        return [
            self.left_row,
            self.right_row,
            self.return_row,
            self.display_row,
            self.auto_poll_row,
        ]

    def _on_auto_poll_changed(self, switch, _):
        settings = self.get_settings()
        settings["auto_poll"] = switch.get_active()
        self.set_settings(settings)

    def _on_left_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(_INPUT_CODES):
            settings = self.get_settings()
            settings["left_input"] = _INPUT_CODES[idx]
            self.set_settings(settings)
            self._prev_state = None
            self._run_threaded(self._poll_display)

    def _on_right_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(_INPUT_CODES):
            settings = self.get_settings()
            settings["right_input"] = _INPUT_CODES[idx]
            self.set_settings(settings)
            self._prev_state = None
            self._run_threaded(self._poll_display)

    def _on_return_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(_INPUT_CODES):
            settings = self.get_settings()
            settings["return_input"] = _INPUT_CODES[idx]
            self.set_settings(settings)

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["display_number"] = int(spin.get_value())
        self.set_settings(settings)
