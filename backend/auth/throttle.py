from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(slots=True)
class _FailureState:
    failures: int
    last_failure: float


class FailureThrottle:
    """Bounded in-memory increasing-delay throttle with automatic recovery."""

    def __init__(
        self,
        *,
        max_entries: int = 512,
        reset_after_seconds: float = 300.0,
        free_failures: int = 2,
        base_delay_seconds: float = 0.25,
        max_delay_seconds: float = 2.0,
    ):
        self.max_entries = max(1, int(max_entries))
        self.reset_after_seconds = max(1.0, float(reset_after_seconds))
        self.free_failures = max(0, int(free_failures))
        self.base_delay_seconds = max(0.0, float(base_delay_seconds))
        self.max_delay_seconds = max(self.base_delay_seconds, float(max_delay_seconds))
        self._entries: OrderedDict[str, _FailureState] = OrderedDict()

    def delay_for(self, key: str) -> float:
        now = time.monotonic()
        state = self._fresh_state(str(key or "unknown"), now)
        if state is None or state.failures <= self.free_failures:
            return 0.0
        exponent = state.failures - self.free_failures - 1
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** exponent))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        normalized = str(key or "unknown")
        state = self._fresh_state(normalized, now)
        failures = 1 if state is None else state.failures + 1
        self._entries[normalized] = _FailureState(failures=failures, last_failure=now)
        self._entries.move_to_end(normalized)
        self._prune(now)

    def record_success(self, key: str) -> None:
        self._entries.pop(str(key or "unknown"), None)

    def clear(self) -> None:
        self._entries.clear()

    def _fresh_state(self, key: str, now: float) -> _FailureState | None:
        state = self._entries.get(key)
        if state is None:
            return None
        if state.last_failure + self.reset_after_seconds <= now:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return state

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, state in self._entries.items()
            if state.last_failure + self.reset_after_seconds <= now
        ]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    @property
    def size(self) -> int:
        self._prune(time.monotonic())
        return len(self._entries)


password_failure_throttle = FailureThrottle()
