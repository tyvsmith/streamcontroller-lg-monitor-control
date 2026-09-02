"""StreamController action to toggle Dual Mode (native vs high-refresh resolution)."""

import logging
import os

import gi

log = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from ... import ddcutil
from ...action_base import MonitorActionMixin
from ...icons import BG_ACTIVE, BG_INACTIVE, COLOR_ACTIVE, COLOR_INACTIVE, tint_icon


class DualMode(MonitorActionMixin, ActionBase):
    """Toggle Dual Mode on monitors that support it.

    The monitor does not report Dual Mode state over DDC/CI (reading the VCP
    code returns 0 in both modes), so the last state written is tracked in
    plugin settings — the same fire-and-forget approach InputSwitch uses.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_polling()
        self.has_configuration = True
        self._prev_state: str | None = None
        self._icon_cache: dict[tuple[int, int, int, int], str] = {}
        self._cached_icon_path: str = os.path.join(
            self.plugin_base.PATH, "assets", "dual-mode.png"
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

    def _poll_display(self):
        # Dual Mode state can't be read from the monitor — refresh from tracked state
        try:
            self._update_display()
            self._poll_done(success=True)
        except Exception:
            log.debug("Refresh failed for DualMode", exc_info=True)
            self._poll_done(success=False)

    def _update_display(self):
        lm = self.plugin_base.lm
        p = ddcutil.profile_for(self._display(), self._bin())

        if not p.has_dual_mode:
            active = False
            label = lm.get("status.unknown")
        elif self.plugin_base.dual_mode_active:
            active = True
            label = p.dual_mode.on_label or lm.get("dual-mode.on")
        else:
            active = False
            label = p.dual_mode.off_label or lm.get("dual-mode.off")

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
        self.set_bottom_label(label, font_size=10)

    def event_callback(self, event, data):
        if event == Input.Key.Events.SHORT_UP:
            self._run_threaded(self._handle_toggle)

    def _handle_toggle(self):
        display, bp = self._display(), self._bin()
        p = ddcutil.profile_for(display, bp)
        if not p.has_dual_mode:
            log.warning("Dual Mode not available for display %d (%s)", display, p.name)
            return

        enabled = not self.plugin_base.dual_mode_active
        if ddcutil.set_dual_mode(display, enabled, bp):
            self.plugin_base.set_dual_mode_active(enabled)
        else:
            log.warning("Dual Mode write failed for display %d", display)

        self._prev_state = None
        self._update_display()
        self.plugin_base.refresh_all()

    # --- Configuration UI ---

    def get_config_rows(self):
        lm = self.plugin_base.lm
        settings = self.get_settings()

        self.display_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.display_row.set_title(lm.get("dual-mode.display-number.title"))
        self.display_row.set_subtitle(lm.get("dual-mode.display-number.subtitle"))
        self.display_row.set_value(settings.get("display_number", 0))
        self.display_row.connect("changed", self._on_display_changed)

        return [self.display_row]

    def _on_display_changed(self, spin):
        settings = self.get_settings()
        settings["display_number"] = int(spin.get_value())
        self.set_settings(settings)
        self._prev_state = None
        self._run_threaded(self._poll_display)
