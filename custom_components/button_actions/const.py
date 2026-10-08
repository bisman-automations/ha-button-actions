"""Constants for Button Actions."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "button_actions"

# ---------------------------------------------------------------------------
# Config entry data
# ---------------------------------------------------------------------------
CONF_BUTTONS: Final = "buttons"
CONF_PRESS_EVENT: Final = "press_event_type"
CONF_RELEASE_EVENT: Final = "release_event_type"

DEFAULT_PRESS_EVENT: Final = "press"
DEFAULT_RELEASE_EVENT: Final = "release"

# Where button presses come from. Entries without a source predate 1.2.0
# and are event-entity remotes.
CONF_SOURCE: Final = "source"
SOURCE_EVENT_ENTITY: Final = "event_entity"
SOURCE_LUTRON: Final = "lutron_caseta"
CONF_PICO_BUTTONS: Final = "pico_buttons"  # slots the Pico physically has

LUTRON_DOMAIN: Final = "lutron_caseta"
LUTRON_BUTTON_EVENT: Final = "lutron_caseta_button_event"
LUTRON_ACTION_PRESS: Final = "press"
LUTRON_ACTION_RELEASE: Final = "release"

# Button slots, in the order they appear on a Lutron Pico.
SLOT_ON: Final = "on"
SLOT_RAISE: Final = "raise"
SLOT_STOP: Final = "stop"
SLOT_LOWER: Final = "lower"
SLOT_OFF: Final = "off"
SLOT_BUTTON_1: Final = "button_1"
SLOT_BUTTON_2: Final = "button_2"
SLOT_BUTTON_3: Final = "button_3"
SLOT_BUTTON_4: Final = "button_4"

SLOTS: Final = (
    SLOT_ON,
    SLOT_RAISE,
    SLOT_STOP,
    SLOT_LOWER,
    SLOT_OFF,
    SLOT_BUTTON_1,
    SLOT_BUTTON_2,
    SLOT_BUTTON_3,
    SLOT_BUTTON_4,
)

SLOT_ICONS: Final = {
    SLOT_ON: "mdi:power-on",
    SLOT_RAISE: "mdi:arrow-up-bold",
    SLOT_STOP: "mdi:circle-medium",
    SLOT_LOWER: "mdi:arrow-down-bold",
    SLOT_OFF: "mdi:power-off",
    SLOT_BUTTON_1: "mdi:numeric-1-circle",
    SLOT_BUTTON_2: "mdi:numeric-2-circle",
    SLOT_BUTTON_3: "mdi:numeric-3-circle",
    SLOT_BUTTON_4: "mdi:numeric-4-circle",
}

# The order buttons sit on a Pico, top to bottom. Off is always the bottom
# button, including on scene Picos, so it comes after the scene buttons.
DISPLAY_ORDER: Final = (
    SLOT_ON,
    SLOT_RAISE,
    SLOT_STOP,
    SLOT_LOWER,
    SLOT_BUTTON_1,
    SLOT_BUTTON_2,
    SLOT_BUTTON_3,
    SLOT_BUTTON_4,
    SLOT_OFF,
)


def button_positions(slots: list[str] | tuple[str, ...]) -> dict[str, int]:
    """Number a remote's buttons 1, 2, 3... in the order they sit on the remote.

    Home Assistant lists entities and subentries alphabetically, so these
    numbers are put at the front of names to keep the remote's order.
    """
    present = set(slots)
    ordered = [slot for slot in DISPLAY_ORDER if slot in present]
    return {slot: index for index, slot in enumerate(ordered, start=1)}


def numbered_title(position: int, slot: str) -> str:
    """Subentry title such as "3 · Middle button"."""
    return f"{position} · {SLOT_TITLES[slot]}"


# Subentry titles. Stored with the subentry, so plain English.
SLOT_TITLES: Final = {
    SLOT_ON: "On button",
    SLOT_RAISE: "Raise button",
    SLOT_STOP: "Middle button",
    SLOT_LOWER: "Lower button",
    SLOT_OFF: "Off button",
    SLOT_BUTTON_1: "Scene button 1",
    SLOT_BUTTON_2: "Scene button 2",
    SLOT_BUTTON_3: "Scene button 3",
    SLOT_BUTTON_4: "Scene button 4",
}

# ---------------------------------------------------------------------------
# Button subentries (one per physical button)
# ---------------------------------------------------------------------------
SUBENTRY_BUTTON: Final = "button"
CONF_SLOT: Final = "slot"
CONF_ENTITIES: Final = "entities"
CONF_ACTIONS: Final = "actions"  # {gesture: [action, ...]}
CONF_REPEAT: Final = "repeat"  # bool: long-press repeats while held
# bool: watch for double and long presses even without an action for them,
# so device triggers and the gesture entity see every gesture.
CONF_DETECT_ALL: Final = "detect_all"

# Fired for every gesture; backs the device triggers.
GESTURE_EVENT: Final = "button_actions_gesture"

# Entry data: the blueprint automation a remote was imported from.
CONF_SOURCE_AUTOMATION: Final = "source_automation"

# ---------------------------------------------------------------------------
# Remote-wide options
# ---------------------------------------------------------------------------
CONF_HOLD_MS: Final = "hold_ms"
CONF_DOUBLE_MS: Final = "double_ms"
CONF_REPEAT_MS: Final = "repeat_ms"

DEFAULT_HOLD_MS: Final = 600
DEFAULT_DOUBLE_MS: Final = 300
DEFAULT_REPEAT_MS: Final = 400

# Safety net: stop hold-repeat if a release event never arrives.
MAX_HOLD_SECONDS: Final = 30

# ---------------------------------------------------------------------------
# Gestures
# ---------------------------------------------------------------------------
GESTURE_SHORT: Final = "short_press"
GESTURE_DOUBLE: Final = "double_press"
GESTURE_LONG: Final = "long_press"
GESTURE_LONG_RELEASE: Final = "long_release"
# Internal tick while a button is held; never shown to users.
GESTURE_HOLD_REPEAT: Final = "hold_repeat"

GESTURES: Final = (GESTURE_SHORT, GESTURE_DOUBLE, GESTURE_LONG, GESTURE_LONG_RELEASE)

# ---------------------------------------------------------------------------
# Import from the "Lutron Pico Universal Actions (Event Entities)" blueprint
# ---------------------------------------------------------------------------
BLUEPRINT_ENTITY_INPUTS: Final = {
    "entity_on": SLOT_ON,
    "entity_raise": SLOT_RAISE,
    "entity_stop": SLOT_STOP,
    "entity_lower": SLOT_LOWER,
    "entity_off": SLOT_OFF,
    "entity_button_1": SLOT_BUTTON_1,
    "entity_button_2": SLOT_BUTTON_2,
    "entity_button_3": SLOT_BUTTON_3,
    "entity_button_4": SLOT_BUTTON_4,
}
BLUEPRINT_GESTURE_PREFIXES: Final = {
    "short_click_action_": GESTURE_SHORT,
    "double_click_action_": GESTURE_DOUBLE,
    "long_click_action_": GESTURE_LONG,
}
# The blueprint's own defaults, used when an imported automation left them unset
# so the remote keeps the timing the user is used to.
BLUEPRINT_DEFAULT_HOLD_MS: Final = 1000
BLUEPRINT_DEFAULT_DOUBLE_MS: Final = 250
