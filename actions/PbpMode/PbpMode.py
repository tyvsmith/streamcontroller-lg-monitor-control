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

_FALLBACK_CHOICES = [(0x0F, "input.dp"), (0x11, "input.hdmi1"), (0x12, "input.hdmi2")]


class PbpMode(MonitorActionMixin, ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_polling()
        self.has_configuration = True
        self._prev_state: str | None = None  # "on" | "off" | None
        self._skip_next_poll: bool = False
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

    def _input_choices(self) -> list[tuple[int, str]]:
        """Build input choices from the monitor profile."""
        p = ddcutil.profile_for(self._display(), self._bin())
        if p.inputs.sources:
            return [(code, f"input.{name}") for name, code in p.inputs.sources.items()]
        return _FALLBACK_CHOICES

    def _input_name(self, code: int) -> str:
        """Get display name for an input code from profile sources."""
        p = ddcutil.profile_for(self._display(), self._bin())
        for name, source_code in p.inputs.sources.items():
            if source_code == code:
                return self.plugin_base.lm.get(f"input.{name}")
        return ddcutil.INPUT_NAMES.get(code, "?")

    def _default_input(self, index: int = 0) -> int:
        choices = self._input_choices()
        if index < len(choices):
            return choices[index][0]
        return choices[0][0] if choices else 0x0F

    def _left_input(self) -> int:
        saved = self.get_settings().get("left_input")
        return int(saved) if saved is not None else self._default_input(0)

    def _right_input(self) -> int:
        saved = self.get_settings().get("right_input")
        return int(saved) if saved is not None else self._default_input(1)

    def _return_input(self) -> int:
        saved = self.get_settings().get("return_input")
        return int(saved) if saved is not None else self._default_input(0)

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
        """Read PBP state from monitor and update UI."""
        if self._skip_next_poll:
            self._skip_next_poll = False
            self._poll_done(success=True)
            return
        try:
            display = self._display()
            bp = self._bin()
            p = ddcutil.profile_for(display, bp)
            pbp = ddcutil.get_pbp(display, bp)
            if pbp and pbp["current"] != p.pbp.off:
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

        left_name = self._input_name(self._left_input())
        right_name = self._input_name(self._right_input())
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

        p = ddcutil.profile_for(display, bp)
        pbp = ddcutil.get_pbp(display, bp)
        if pbp and pbp["current"] != p.pbp.off:
            return_input = self._return_input()
            ddcutil.switch_input(display, return_input, bp)
            ddcutil.disable_pbp(display, bp)
            self.plugin_base.set_last_input(return_input)
            self._set_state("off")
        else:
            ddcutil.set_pbp(display, self._left_input(), self._right_input(), bp)
            self.plugin_base.set_last_input(None)
            self._set_state("on")
        self._skip_next_poll = True
        self.plugin_base.refresh_all()

    # --- Configuration UI ---

    def get_config_rows(self):
        lm = self.plugin_base.lm
        settings = self.get_settings()

        self._config_choices = self._input_choices()
        self._config_codes = [code for code, _ in self._config_choices]

        self.left_model = Gtk.StringList()
        for _, locale_key in self._config_choices:
            self.left_model.append(lm.get(locale_key))

        self.left_row = Adw.ComboRow(
            title=lm.get("pbp-mode.left-input.title"),
            model=self.left_model,
        )
        current_left = self._left_input()
        if current_left in self._config_codes:
            self.left_row.set_selected(self._config_codes.index(current_left))
        self.left_row.connect("notify::selected", self._on_left_changed)

        self.right_model = Gtk.StringList()
        for _, locale_key in self._config_choices:
            self.right_model.append(lm.get(locale_key))

        self.right_row = Adw.ComboRow(
            title=lm.get("pbp-mode.right-input.title"),
            model=self.right_model,
        )
        current_right = self._right_input()
        if current_right in self._config_codes:
            self.right_row.set_selected(self._config_codes.index(current_right))
        self.right_row.connect("notify::selected", self._on_right_changed)

        self.return_model = Gtk.StringList()
        for _, locale_key in self._config_choices:
            self.return_model.append(lm.get(locale_key))

        self.return_row = Adw.ComboRow(
            title=lm.get("pbp-mode.return-input.title"),
            subtitle=lm.get("pbp-mode.return-input.subtitle"),
            model=self.return_model,
        )
        current_return = self._return_input()
        if current_return in self._config_codes:
            self.return_row.set_selected(self._config_codes.index(current_return))
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
        if 0 <= idx < len(self._config_codes):
            settings = self.get_settings()
            settings["left_input"] = self._config_codes[idx]
            self.set_settings(settings)
            self._prev_state = None
            self._run_threaded(self._poll_display)

    def _on_right_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self._config_codes):
            settings = self.get_settings()
            settings["right_input"] = self._config_codes[idx]
            self.set_settings(settings)
            self._prev_state = None
            self._run_threaded(self._poll_display)

    def _on_return_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self._config_codes):
            settings = self.get_settings()
            settings["return_input"] = self._config_codes[idx]
            self.set_settings(settings)

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["display_number"] = int(spin.get_value())
        self.set_settings(settings)
