"""Work out what each event type from a button device means.

Different integrations report buttons differently:

- Lutron (lutron-caseta-events) and many others: ``press`` then ``release``.
- Core Lutron Caséta on Home Assistant 2026.11: ``press_start`` when the
  button goes down and, on a Pico or shade remote, ``press_end`` when it is
  released. A keypad sends ``press_start`` only.
- Matter momentary switches: ``initial_press``, then ``short_release`` or
  ``long_release`` (``long_press`` fires mid-hold). Some send no release.
- Matter multi-press switches count presses themselves: ``multi_press_1``,
  ``multi_press_2``..., plus ``long_press`` / ``long_release``.
- Zigbee, ESPHome and others often use names like ``single``, ``double``,
  ``hold``.
- The standard button event types of Home Assistant 2026.12 (revised
  2026-11-09): ``press_start`` / ``press_end`` are only the button going down
  and up; ``single_press`` and ``multi_press`` (with ``press_count``) are
  presses the device detected. On 2026.11, ``press_end`` could also be a
  whole press with no ``press_start`` before it (ISY), and ``multi_press_end``
  carried ``multi_press_count``; both still have to work.

Each event type gets a role. Press/release/click feed our own gesture
detection; single/double/hold are gestures the device already detected.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

ROLE_PRESS: Final = "press"  # button went down
ROLE_RELEASE: Final = "release"  # button came up
ROLE_CLICK: Final = "click"  # a full press and release in one event
ROLE_SINGLE: Final = "single"  # device detected a short press
ROLE_DOUBLE: Final = "double"  # device detected a double press
ROLE_HOLD: Final = "hold"  # device detected a hold (release follows)
ROLE_IGNORE: Final = "ignore"

# Event types whose press count is in the event: ``press_count`` from Home
# Assistant 2026.12, ``multi_press_count`` before (deprecated, gone 2027.5).
COUNTED_TYPES: Final = frozenset({"multi_press", "multi_press_end"})
COUNT_ATTRIBUTES: Final = ("press_count", "multi_press_count")

ROLES: Final = (
    ROLE_PRESS,
    ROLE_RELEASE,
    ROLE_CLICK,
    ROLE_SINGLE,
    ROLE_DOUBLE,
    ROLE_HOLD,
    ROLE_IGNORE,
)

_NAMED: Final = {
    "press": ROLE_PRESS,
    "pressed": ROLE_PRESS,
    "down": ROLE_PRESS,
    "initial_press": ROLE_PRESS,
    # Standard button vocabulary (architecture #1502). Core Lutron Caséta
    # uses these two for a physical press and release.
    "press_start": ROLE_PRESS,
    "release": ROLE_RELEASE,
    "released": ROLE_RELEASE,
    "up": ROLE_RELEASE,
    "press_end": ROLE_RELEASE,
    "short_release": ROLE_RELEASE,
    "long_release": ROLE_RELEASE,
    "long_press_end": ROLE_RELEASE,
    "hold_release": ROLE_RELEASE,
    "click": ROLE_CLICK,
    "single": ROLE_SINGLE,
    "single_press": ROLE_SINGLE,
    "short_press": ROLE_SINGLE,
    "short": ROLE_SINGLE,
    "multi_press_1": ROLE_SINGLE,
    # Device-counted presses; the event's count picks single or double
    # (``role_for_count``). ``multi_press_end`` is the 2026.11 name.
    "multi_press": ROLE_DOUBLE,
    "multi_press_end": ROLE_DOUBLE,
    "double": ROLE_DOUBLE,
    "double_press": ROLE_DOUBLE,
    "double_click": ROLE_DOUBLE,
    "multi_press_2": ROLE_DOUBLE,
    "hold": ROLE_HOLD,
    "held": ROLE_HOLD,
    "long": ROLE_HOLD,
    "long_press": ROLE_HOLD,
    "long_press_start": ROLE_HOLD,
}


def suggest_roles(event_types: Iterable[str]) -> dict[str, str]:
    """Best-guess role for every event type a device reports."""
    types = list(dict.fromkeys(event_types))
    roles = {t: _NAMED.get(t, ROLE_IGNORE) for t in types}

    # Matter momentary switch without release support: initial_press is the
    # only thing a short press sends, so it has to count as a whole click.
    if "initial_press" in roles and "short_release" not in roles:
        roles["initial_press"] = ROLE_CLICK

    # A press/release device times holds itself, so a device's own mid-hold
    # event would double up with ours. Matter momentary switches send
    # long_press between initial_press and long_release.
    has_press = ROLE_PRESS in roles.values()
    has_release = ROLE_RELEASE in roles.values()
    if has_press and has_release:
        for t, role in roles.items():
            if role in (ROLE_HOLD, ROLE_SINGLE, ROLE_DOUBLE):
                roles[t] = ROLE_IGNORE
    elif has_press:
        # Press with no release event: each press is a whole click.
        for t, role in roles.items():
            if role == ROLE_PRESS:
                roles[t] = ROLE_CLICK
    elif "press_end" in roles and ROLE_SINGLE not in roles.values():
        # press_end with no press_start: Home Assistant 2026.11 used it for a
        # whole press (ISY), and a device that only reports the button
        # coming up still means one press each time.
        roles["press_end"] = ROLE_CLICK

    return roles


def role_for_count(event_type: str, role: str, attributes: Mapping[str, Any]) -> str:
    """Single or double press from a device-counted event's press count.

    Counts other than one or two aren't a gesture Button Actions has, so
    they're ignored. Without a count the role stays as it is.
    """
    if event_type not in COUNTED_TYPES or role not in (ROLE_SINGLE, ROLE_DOUBLE):
        return role
    for key in COUNT_ATTRIBUTES:
        if (count := attributes.get(key)) is not None:
            break
    else:
        return role
    if count == 1:
        return ROLE_SINGLE
    if count == 2:
        return ROLE_DOUBLE
    return ROLE_IGNORE


def resolve_role(
    event_type: str,
    event_types: Iterable[str] | None,
    overrides: dict[str, str],
    attributes: Mapping[str, Any] | None = None,
) -> str:
    """The role of one event, preferring the user's mapping."""
    if event_type in overrides:
        role = overrides[event_type]
    else:
        role = suggest_roles([*(event_types or []), event_type]).get(
            event_type, ROLE_IGNORE
        )
    return role_for_count(event_type, role, attributes or {})
