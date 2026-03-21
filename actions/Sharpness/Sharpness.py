"""StreamController action to cycle monitor sharpness."""

from ... import ddcutil
from ..slider_base import SliderAction


class Sharpness(SliderAction):
    _icon_name = "sharpness.png"
    _default_step = 10
    _reset_value = 50
    _locale_prefix = "sharpness"

    def _get_value(self):
        return ddcutil.get_sharpness(self._display(), self._bin())

    def _set_value(self, value):
        return ddcutil.set_sharpness(self._display(), value, self._bin())
