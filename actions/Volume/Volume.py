"""StreamController action to cycle monitor volume and toggle mute."""

import logging

from src.backend.DeckManagement.InputIdentifier import Input

from ... import ddcutil
from ...icons import COLOR_INACTIVE, tint_icon
from ..slider_base import SliderAction

log = logging.getLogger(__name__)


class Volume(SliderAction):
    _icon_name = "volume.png"
    _default_step = 25
    _reset_value = None  # hold = mute toggle, not reset
    _locale_prefix = "volume"

    def _get_value(self):
        return ddcutil.get_volume(self._display(), self._bin())

    def _set_value(self, value):
        return ddcutil.set_volume(self._display(), value, self._bin())

    def _poll_display(self):
        try:
            if not self._tinted_icon:
                tinted = tint_icon(self._cached_icon_path, COLOR_INACTIVE)
                self._tinted_icon = tinted if tinted else self._cached_icon_path
                self.set_media(media_path=self._tinted_icon, size=0.75)

            display, bp = self._display(), self._bin()
            mute = ddcutil.get_mute(display, bp)
            if mute and mute["current"] == 1:
                self._set_label(self.plugin_base.lm.get("status.muted"))
            else:
                result = ddcutil.get_volume(display, bp)
                self._set_label(f"{result['current']}%" if result else None)
            self._poll_done(success=True)
        except Exception:
            log.debug("Poll failed for Volume", exc_info=True)
            self._poll_done(success=False)

    def event_callback(self, event, data):
        if event == Input.Key.Events.SHORT_UP:
            self._run_threaded(self._handle_cycle)
        elif event == Input.Key.Events.HOLD_START:
            self._run_threaded(self._handle_mute_toggle)
        elif str(event) == str(Input.Dial.Events.TURN_CW):
            self._run_threaded(self._handle_adjust, self._step())
        elif str(event) == str(Input.Dial.Events.TURN_CCW):
            self._run_threaded(self._handle_adjust, -self._step())
        elif event == Input.Dial.Events.DOWN:
            self._run_threaded(self._handle_mute_toggle)

    def _handle_adjust(self, delta):
        display, bp = self._display(), self._bin()
        mute = ddcutil.get_mute(display, bp)
        if mute and mute["current"] == 1:
            ddcutil.set_mute(display, False, bp)
        result = ddcutil.get_volume(display, bp)
        if result:
            new_val = max(0, min(result["max"] or 100, result["current"] + delta))
        else:
            new_val = max(0, delta)
        ddcutil.set_volume(display, new_val, bp)
        self._set_label(f"{new_val}%")
        self.plugin_base.refresh_all()

    def _handle_cycle(self):
        display, bp, step = self._display(), self._bin(), self._step()
        mute = ddcutil.get_mute(display, bp)
        if mute and mute["current"] == 1:
            ddcutil.set_mute(display, False, bp)
        result = ddcutil.get_volume(display, bp)
        if result:
            new_val = result["current"] + step
            if new_val > (result["max"] or 100):
                new_val = 0
        else:
            new_val = step
        ddcutil.set_volume(display, new_val, bp)
        self._set_label(f"{new_val}%")
        self.plugin_base.refresh_all()

    def _handle_mute_toggle(self):
        display, bp = self._display(), self._bin()
        mute = ddcutil.get_mute(display, bp)
        if mute and mute["current"] == 1:
            ddcutil.set_mute(display, False, bp)
            self._set_label(None)
        else:
            ddcutil.set_mute(display, True, bp)
            self._set_label(self.plugin_base.lm.get("status.muted"))
        self.plugin_base.refresh_all()
