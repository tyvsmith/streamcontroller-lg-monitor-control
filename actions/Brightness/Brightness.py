"""StreamController action to cycle monitor brightness."""

from ... import ddcutil
from ..slider_base import SliderAction


class Brightness(SliderAction):
    _icon_name = "brightness.png"
    _default_step = 25
    _reset_value = 100
    _locale_prefix = "brightness"

    def _get_value(self):
        return ddcutil.get_brightness(self._display(), self._bin())

    def _set_value(self, value):
        return ddcutil.set_brightness(self._display(), value, self._bin())
