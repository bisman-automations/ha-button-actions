"""Gesture state machine tests with a fake clock."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from custom_components.button_actions.const import (
    GESTURE_DOUBLE,
    GESTURE_HOLD_REPEAT,
    GESTURE_LONG,
    GESTURE_LONG_RELEASE,
    GESTURE_SHORT,
)
from custom_components.button_actions.gesture import GestureDetector, GestureSettings


class FakeClock:
    """Minimal scheduler: timers fire when advance() passes their deadline."""

    def __init__(self) -> None:
        self.now = 0.0
        self._timers: list[tuple[float, int, Callable[[], None]]] = []
        self._next_id = 0

    def schedule(self, delay: float, callback: Callable[[], None]):
        timer_id = self._next_id
        self._next_id += 1
        self._timers.append((self.now + delay, timer_id, callback))

        def cancel() -> None:
            self._timers = [t for t in self._timers if t[1] != timer_id]

        return cancel

    def advance(self, seconds: float) -> None:
        target = self.now + seconds
        while True:
            due = sorted(t for t in self._timers if t[0] <= target)
            if not due:
                break
            when, timer_id, callback = due[0]
            self._timers = [t for t in self._timers if t[1] != timer_id]
            self.now = when
            callback()
        self.now = target


def make(
    *, double: bool = True, hold: bool = True, repeat: bool = False
) -> tuple[GestureDetector, FakeClock, list[str]]:
    clock = FakeClock()
    emitted: list[str] = []
    detector = GestureDetector(
        clock.schedule,
        emitted.append,
        GestureSettings(
            hold_ms=600,
            double_ms=300,
            repeat_ms=200,
            detect_double=double,
            detect_hold=hold,
            repeat=repeat,
        ),
    )
    return detector, clock, emitted


def test_short_press_waits_for_double_window() -> None:
    d, clock, out = make()
    d.press()
    clock.advance(0.1)
    d.release()
    assert out == []
    clock.advance(0.31)
    assert out == [GESTURE_SHORT]


def test_short_press_is_instant_without_double_action() -> None:
    d, clock, out = make(double=False)
    d.press()
    clock.advance(0.1)
    d.release()
    assert out == [GESTURE_SHORT]


def test_double_press() -> None:
    d, clock, out = make()
    d.press()
    d.release()
    clock.advance(0.1)
    d.press()
    assert out == [GESTURE_DOUBLE]
    d.release()
    clock.advance(1)
    assert out == [GESTURE_DOUBLE]


def test_long_press_and_release() -> None:
    d, clock, out = make()
    d.press()
    clock.advance(0.7)
    assert out == [GESTURE_LONG]
    d.release()
    assert out == [GESTURE_LONG, GESTURE_LONG_RELEASE]


def test_long_press_counts_as_short_without_hold_action() -> None:
    d, clock, out = make(double=False, hold=False)
    d.press()
    clock.advance(2)
    d.release()
    assert out == [GESTURE_SHORT]


def test_repeat_while_held() -> None:
    d, clock, out = make(repeat=True)
    d.press()
    clock.advance(0.6 + 0.2 * 3 + 0.05)
    assert out == [GESTURE_LONG] + [GESTURE_HOLD_REPEAT] * 3
    d.release()
    clock.advance(1)
    assert out[-1] == GESTURE_LONG_RELEASE
    assert out.count(GESTURE_HOLD_REPEAT) == 3


def test_repeat_stops_if_release_is_lost() -> None:
    d, clock, out = make(repeat=True)
    d.press()
    clock.advance(120)
    # 30 s cap / 0.2 s interval = 150 ticks at most
    assert out.count(GESTURE_HOLD_REPEAT) <= 150


@pytest.mark.parametrize("held", [True, False])
def test_missed_release_does_not_wedge_button(held: bool) -> None:
    d, clock, out = make()
    d.press()
    if held:
        clock.advance(1)  # becomes a long press
    else:
        d.release()
        d.press()  # double, then release lost
    out.clear()
    # Release never arrives; next physical click must still work.
    d.press()
    d.release()
    clock.advance(1)
    assert out == [GESTURE_SHORT]


def test_reset_drops_pending_short() -> None:
    d, clock, out = make()
    d.press()
    d.release()
    d.reset()
    clock.advance(1)
    assert out == []


def test_stray_release_ignored() -> None:
    d, clock, out = make()
    d.release()
    clock.advance(1)
    assert out == []


def test_button_positions() -> None:
    from custom_components.button_actions.const import button_positions

    assert button_positions(["off", "lower", "on", "stop", "raise"]) == {
        "on": 1,
        "raise": 2,
        "stop": 3,
        "lower": 4,
        "off": 5,
    }
    # Scene Pico: Off is the bottom button, after the scene buttons.
    assert button_positions(["off", "button_3", "button_1", "button_2"]) == {
        "button_1": 1,
        "button_2": 2,
        "button_3": 3,
        "off": 4,
    }
    assert button_positions(["off", "on"]) == {"on": 1, "off": 2}
