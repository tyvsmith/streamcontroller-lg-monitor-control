"""StreamController action to cycle monitor contrast."""

from ... import ddcutil
from ..slider_base import SliderAction


class Contrast(SliderAction):
    _icon_name = "contrast.png"
    _default_step = 25
    _reset_value = 70
    _locale_prefix = "contrast"

    def _get_value(self):
        return ddcutil.get_contrast(self._display(), self._bin())

    def _set_value(self, value):
        return ddcutil.set_contrast(self._display(), value, self._bin())
