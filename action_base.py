"""Shared base for all monitor control actions — thread guard and backoff."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


class MonitorActionMixin:
    """Mixin providing thread-safe polling with backoff for monitor actions."""

    _max_backoff: float = 300.0
    _auto_poll_default: bool = False

    def _init_polling(self) -> None:
        self._last_check: float = 0.0
        self._poll_in_flight: bool = False
        self._consecutive_failures: int = 0
        self._poll_lock: threading.Lock = threading.Lock()

    def _auto_poll_enabled(self) -> bool:
        return self.get_settings().get("auto_poll", self._auto_poll_default)  # type: ignore[attr-defined]

    def _poll_interval(self) -> float:
        return self.plugin_base.get_poll_interval()  # type: ignore[attr-defined]

    def _effective_interval(self) -> float:
        interval = self._poll_interval()
        if self._consecutive_failures < 3:
            return interval
        return min(
            interval * (2 ** (self._consecutive_failures - 2)),
            self._max_backoff,
        )

    def _should_poll(self) -> bool:
        now = time.monotonic()
        with self._poll_lock:
            if now - self._last_check < self._effective_interval():
                return False
            if self._poll_in_flight:
                return False
            self._poll_in_flight = True
            self._last_check = now
        return True

    def _poll_done(self, success: bool = True) -> None:
        with self._poll_lock:
            self._poll_in_flight = False
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

    def _run_threaded(self, target: Callable[..., Any], *args: Any) -> None:
        threading.Thread(target=target, args=args, daemon=True).start()
