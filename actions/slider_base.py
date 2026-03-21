"""Base class for slider-style actions (brightness, contrast, volume, etc.)."""

import logging
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from .. import ddcutil
from ..action_base import MonitorActionMixin
from ..icons import COLOR_INACTIVE, tint_icon

log = logging.getLogger(__name__)


class SliderAction(MonitorActionMixin, ActionBase):
    """Base for actions that cycle a numeric VCP value with key/dial support.

    Subclasses must set these class attributes:
        _icon_name: str          — filename in assets/ (e.g. "brightness.png")
        _default_step: int       — default step size for cycling
        _reset_value: int | None — value for hold/dial-press reset (None = no reset)
        _label_suffix: str       — appended to value label (e.g. "%" or "")
        _locale_prefix: str      — prefix for locale keys (e.g. "brightness")

    Subclasses must implement:
        _get_value() -> VcpValue | None
        _set_value(value: int) -> bool
    """

    _icon_name: str = ""
    _default_step: int = 25
    _reset_value: int | None = None
    _label_suffix: str = "%"
    _locale_prefix: str = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_polling()
        self.has_configuration = True
        self._prev_label: str | None = None
        self._tinted_icon: str | None = None
        self._cached_icon_path: str = os.path.join(
            self.plugin_base.PATH, "assets", self._icon_name
        )

    def _display(self) -> int:
        d = int(self.get_settings().get("display_number", 0))
        if d == 0:
            d = int(self.plugin_base.get_settings().get("default_display", 1))
        return d

    def _bin(self) -> str:
        return self.plugin_base.get_settings().get("ddcutil_path", "")

    def _step(self) -> int:
        return int(self.get_settings().get("step_size", self._default_step))

    def _get_value(self) -> ddcutil.VcpValue | None:
        raise NotImplementedError

    def _set_value(self, value: int) -> bool:
        raise NotImplementedError

    def on_ready(self):
        self.plugin_base.register_action(self)
        self.set_media(media_path=self._cached_icon_path, size=0.75)
        self._prev_label = None
        self._run_threaded(self._poll_display)

    def on_tick(self):
        if self._auto_poll_enabled() and self._should_poll():
            self._run_threaded(self._poll_display)

    def _poll_display(self):
        try:
            if not self._tinted_icon:
                tinted = tint_icon(self._cached_icon_path, COLOR_INACTIVE)
                self._tinted_icon = tinted if tinted else self._cached_icon_path
                self.set_media(media_path=self._tinted_icon, size=0.75)

            result = self._get_value()
            if result:
                self._set_label(f"{result['current']}{self._label_suffix}")
            else:
                self._set_label(None)
            self._poll_done(success=result is not None)
        except Exception:
            log.debug("Poll failed for %s", self.__class__.__name__, exc_info=True)
            self._poll_done(success=False)

    def _set_label(self, label: str | None) -> None:
        text = label or self.plugin_base.lm.get("status.unknown")
        if text == self._prev_label:
            return
        self._prev_label = text
        self.set_bottom_label(text, font_size=12)

    def event_callback(self, event, data):
        if event == Input.Key.Events.SHORT_UP:
            self._run_threaded(self._handle_cycle)
        elif event == Input.Key.Events.HOLD_START:
            self._run_threaded(self._handle_reset)
        elif str(event) == str(Input.Dial.Events.TURN_CW):
            self._run_threaded(self._handle_adjust, self._step())
        elif str(event) == str(Input.Dial.Events.TURN_CCW):
            self._run_threaded(self._handle_adjust, -self._step())
        elif event == Input.Dial.Events.DOWN:
            self._run_threaded(self._handle_reset)

    def _handle_adjust(self, delta: int):
        result = self._get_value()
        if result:
            new_val = max(0, min(result["max"] or 100, result["current"] + delta))
        else:
            new_val = max(0, delta)
        self._set_value(new_val)
        self._set_label(f"{new_val}{self._label_suffix}")
        self.plugin_base.refresh_all()

    def _handle_cycle(self):
        step = self._step()
        result = self._get_value()
        if result:
            new_val = result["current"] + step
            if new_val > (result["max"] or 100):
                new_val = 0
        else:
            new_val = step
        self._set_value(new_val)
        self._set_label(f"{new_val}{self._label_suffix}")
        self.plugin_base.refresh_all()

    def _handle_reset(self):
        if self._reset_value is not None:
            self._set_value(self._reset_value)
            self._set_label(f"{self._reset_value}{self._label_suffix}")
            self.plugin_base.refresh_all()

    # --- Configuration UI ---

    def get_config_rows(self):
        lm = self.plugin_base.lm
        settings = self.get_settings()
        prefix = self._locale_prefix

        self.display_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.display_row.set_title(lm.get(f"{prefix}.display-number.title"))
        self.display_row.set_subtitle(lm.get(f"{prefix}.display-number.subtitle"))
        self.display_row.set_value(settings.get("display_number", 0))
        self.display_row.connect("changed", self._on_display_changed)

        self.step_row = Adw.SpinRow.new_with_range(1, 50, 1)
        self.step_row.set_title(lm.get(f"{prefix}.step-size.title"))
        self.step_row.set_subtitle(lm.get(f"{prefix}.step-size.subtitle"))
        self.step_row.set_value(settings.get("step_size", self._default_step))
        self.step_row.connect("changed", self._on_step_changed)

        self.auto_poll_row = Adw.SwitchRow(
            title=lm.get("settings.auto-poll.title"),
            subtitle=lm.get("settings.auto-poll.subtitle"),
        )
        self.auto_poll_row.set_active(
            settings.get("auto_poll", self._auto_poll_default)
        )
        self.auto_poll_row.connect("notify::active", self._on_auto_poll_changed)

        return [self.display_row, self.step_row, self.auto_poll_row]

    def _on_auto_poll_changed(self, switch, _):
        settings = self.get_settings()
        settings["auto_poll"] = switch.get_active()
        self.set_settings(settings)

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["display_number"] = int(spin.get_value())
        self.set_settings(settings)

    def _on_step_changed(self, spin):
        settings = self.get_settings()
        settings["step_size"] = int(spin.get_value())
        self.set_settings(settings)
