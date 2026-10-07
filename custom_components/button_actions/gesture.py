"""Turn raw press/release events into click gestures.

This module has no Home Assistant imports so it can be unit tested with a
fake clock. The caller supplies a ``schedule(delay_seconds, callback)``
function that returns a cancel function (``async_call_later`` in HA).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from .const import (
    GESTURE_DOUBLE,
    GESTURE_HOLD_REPEAT,
    GESTURE_LONG,
    GESTURE_LONG_RELEASE,
    GESTURE_SHORT,
    MAX_HOLD_SECONDS,
)

Cancel = Callable[[], None]
Schedule = Callable[[float, Callable[[], None]], Cancel]


@dataclass(frozen=True, slots=True)
class GestureSettings:
    """Timing and which gestures are worth waiting for."""

    hold_ms: int
    double_ms: int
    repeat_ms: int
    # Only wait for a second press if a double-press action is configured,
    # so plain short presses fire immediately on release.
    detect_double: bool
    # Only start the hold timer if a long-press action is configured;
    # otherwise a long press simply counts as a short press.
    detect_hold: bool
    # Emit hold_repeat ticks every repeat_ms while held.
    repeat: bool


class _State(Enum):
    IDLE = auto()
    DOWN = auto()  # first press down, waiting for release or hold timeout
    WAIT_SECOND = auto()  # released, waiting to see if a second press comes
    SECOND_DOWN = auto()  # second press down, double already emitted
    HELD = auto()  # hold timeout passed, long_press emitted


class GestureDetector:
    """Per-button state machine."""

    def __init__(
        self,
        schedule: Schedule,
        on_gesture: Callable[[str], None],
        settings: GestureSettings,
    ) -> None:
        self._schedule = schedule
        self._emit = on_gesture
        self._settings = settings
        self._state = _State.IDLE
        self._cancel: Cancel | None = None
        self._repeats = 0

    @property
    def state(self) -> str:
        """Current state name, for diagnostics."""
        return self._state.name.lower()

    # -- inputs ---------------------------------------------------------------

    def press(self) -> None:
        """Handle a button press."""
        state = self._state
        if state is _State.WAIT_SECOND:
            self._cancel_timer()
            self._state = _State.SECOND_DOWN
            self._emit(GESTURE_DOUBLE)
            return
        if state is _State.DOWN:
            # Duplicate press without a release in between; ignore.
            return
        if state in (_State.HELD, _State.SECOND_DOWN):
            # We missed a release. Treat this as a fresh press so the
            # button never gets stuck.
            self._cancel_timer()
            self._state = _State.IDLE
        self._start_press()

    def release(self) -> None:
        """Handle a button release."""
        state = self._state
        if state is _State.DOWN:
            self._cancel_timer()
            if self._settings.detect_double:
                self._state = _State.WAIT_SECOND
                self._set_timer(self._settings.double_ms, self._on_double_timeout)
            else:
                self._state = _State.IDLE
                self._emit(GESTURE_SHORT)
        elif state is _State.HELD:
            self._cancel_timer()
            self._state = _State.IDLE
            self._emit(GESTURE_LONG_RELEASE)
        elif state is _State.SECOND_DOWN:
            self._state = _State.IDLE
        # Stray release in IDLE or WAIT_SECOND: ignore.

    def reset(self) -> None:
        """Drop any in-progress gesture (source went unavailable, unload)."""
        self._cancel_timer()
        self._state = _State.IDLE

    # -- internals ------------------------------------------------------------

    def _start_press(self) -> None:
        self._state = _State.DOWN
        if self._settings.detect_hold:
            self._set_timer(self._settings.hold_ms, self._on_hold)

    def _on_hold(self) -> None:
        self._cancel = None
        if self._state is not _State.DOWN:
            return
        self._state = _State.HELD
        self._emit(GESTURE_LONG)
        if self._settings.repeat:
            self._repeats = 0
            self._set_timer(self._settings.repeat_ms, self._on_repeat)

    def _on_repeat(self) -> None:
        self._cancel = None
        if self._state is not _State.HELD:
            return
        self._repeats += 1
        if self._repeats * self._settings.repeat_ms > MAX_HOLD_SECONDS * 1000:
            # Release probably got lost; stop ramping.
            return
        self._emit(GESTURE_HOLD_REPEAT)
        self._set_timer(self._settings.repeat_ms, self._on_repeat)

    def _on_double_timeout(self) -> None:
        self._cancel = None
        if self._state is not _State.WAIT_SECOND:
            return
        self._state = _State.IDLE
        self._emit(GESTURE_SHORT)

    def _set_timer(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self._cancel_timer()
        self._cancel = self._schedule(delay_ms / 1000, callback)

    def _cancel_timer(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None
