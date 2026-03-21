"""StreamController action to cycle monitor black stabilizer."""

from ... import ddcutil
from ..slider_base import SliderAction


class BlackStabilizer(SliderAction):
    _icon_name = "black-stabilizer.png"
    _default_step = 10
    _reset_value = 50
    _label_suffix = ""
    _locale_prefix = "black-stabilizer"

    def _get_value(self):
        return ddcutil.get_black_stabilizer(self._display(), self._bin())

    def _set_value(self, value):
        return ddcutil.set_black_stabilizer(self._display(), value, self._bin())
