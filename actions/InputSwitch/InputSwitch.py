"""StreamController action to switch monitor input source."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from ... import ddcutil
from ...action_base import MonitorActionMixin
from ...icons import BG_ACTIVE, BG_INACTIVE, COLOR_ACTIVE, COLOR_INACTIVE, tint_icon

_FALLBACK_CHOICES = [(0x0F, "input.dp"), (0x11, "input.hdmi1"), (0x12, "input.hdmi2")]


class InputSwitch(MonitorActionMixin, ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_polling()
        self.has_configuration = True
        self._prev_state: str | None = None
        self._icon_cache: dict[tuple[int, int, int, int], str] = {}
        self._cached_icon_path: str = os.path.join(
            self.plugin_base.PATH, "assets", "input-switch.png"
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

    def _target_input(self) -> int:
        saved = self.get_settings().get("target_input")
        if saved is not None:
            return int(saved)
        choices = self._input_choices()
        return choices[0][0] if choices else 0x0F

    def _disable_pbp_on_switch(self) -> bool:
        return self.get_settings().get("disable_pbp_on_switch", True)

    def _get_tinted_icon(self, color: tuple[int, int, int, int]) -> str:
        if color not in self._icon_cache:
            tinted = tint_icon(self._cached_icon_path, color)
            self._icon_cache[color] = tinted if tinted else self._cached_icon_path
        return self._icon_cache[color]

    def _is_active(self) -> bool:
        return self.plugin_base.last_input == self._target_input()

    def on_ready(self):
        self.plugin_base.register_action(self)
        self._prev_state = None
        self._update_display()

    def on_tick(self):
        if self._auto_poll_enabled() and self._should_poll():
            self._update_display()
            self._poll_done(success=True)

    def _poll_display(self):
        # InputSwitch doesn't read from the monitor — just refreshes from last_input
        self._update_display()

    def on_remove(self):
        self.plugin_base.unregister_action(self)

    def _update_display(self):
        target = self._target_input()
        label = self._input_name(target)
        active = self._is_active()
        state = f"{label}:{'on' if active else 'off'}"

        if state == self._prev_state:
            return
        self._prev_state = state

        if active:
            self.set_media(media_path=self._get_tinted_icon(COLOR_ACTIVE), size=0.75)
            self.set_background_color(BG_ACTIVE)
        else:
            self.set_media(media_path=self._get_tinted_icon(COLOR_INACTIVE), size=0.75)
            self.set_background_color(BG_INACTIVE)
        self.set_bottom_label(label, font_size=12)

    def event_callback(self, event, data):
        if event == Input.Key.Events.SHORT_UP:
            self._run_threaded(self._handle_switch)

    def _handle_switch(self):
        display = self._display()
        bp = self._bin()
        target = self._target_input()

        ddcutil.switch_input(display, target, bp)
        self.plugin_base.set_last_input(target)

        p = ddcutil.profile_for(display, bp)
        if self._disable_pbp_on_switch() and p.has_pbp:
            pbp = ddcutil.get_pbp(display, bp)
            if pbp and pbp["current"] != p.pbp.off:
                ddcutil.disable_pbp(display, bp)

        self._prev_state = None
        self._update_display()
        self.plugin_base.refresh_all()

    # --- Configuration UI ---

    def get_config_rows(self):
        lm = self.plugin_base.lm
        settings = self.get_settings()

        self._config_choices = self._input_choices()
        self._config_codes = [code for code, _ in self._config_choices]

        self.input_model = Gtk.StringList()
        for _, locale_key in self._config_choices:
            self.input_model.append(lm.get(locale_key))

        self.input_row = Adw.ComboRow(
            title=lm.get("input-switch.target-input.title"),
            model=self.input_model,
        )
        current_input = self._target_input()
        if current_input in self._config_codes:
            self.input_row.set_selected(self._config_codes.index(current_input))
        self.input_row.connect("notify::selected", self._on_input_changed)

        self.display_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.display_row.set_title(lm.get("input-switch.display-number.title"))
        self.display_row.set_subtitle(lm.get("input-switch.display-number.subtitle"))
        self.display_row.set_value(settings.get("display_number", 0))
        self.display_row.connect("changed", self._on_display_changed)

        self.pbp_row = Adw.SwitchRow(
            title=lm.get("input-switch.disable-pbp.title"),
            subtitle=lm.get("input-switch.disable-pbp.subtitle"),
        )
        self.pbp_row.set_active(settings.get("disable_pbp_on_switch", True))
        self.pbp_row.connect("notify::active", self._on_pbp_changed)

        self.auto_poll_row = Adw.SwitchRow(
            title=lm.get("settings.auto-poll.title"),
            subtitle=lm.get("settings.auto-poll.subtitle"),
        )
        self.auto_poll_row.set_active(
            settings.get("auto_poll", self._auto_poll_default)
        )
        self.auto_poll_row.connect("notify::active", self._on_auto_poll_changed)

        return [self.input_row, self.display_row, self.pbp_row, self.auto_poll_row]

    def _on_auto_poll_changed(self, switch, _):
        settings = self.get_settings()
        settings["auto_poll"] = switch.get_active()
        self.set_settings(settings)

    def _on_input_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self._config_codes):
            settings = self.get_settings()
            settings["target_input"] = self._config_codes[idx]
            self.set_settings(settings)
            self._prev_state = None
            self._update_display()

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["display_number"] = int(spin.get_value())
        self.set_settings(settings)

    def _on_pbp_changed(self, switch, _):
        settings = self.get_settings()
        settings["disable_pbp_on_switch"] = switch.get_active()
        self.set_settings(settings)
