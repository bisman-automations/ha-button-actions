"""Wire source event entities to gesture detectors and action sequences."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.script import (
    SCRIPT_MODE_PARALLEL,
    Script,
    async_validate_actions_config,
)

from .const import (
    CONF_ACTIONS,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_HOLD_MS,
    CONF_PRESS_EVENT,
    CONF_RELEASE_EVENT,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    DEFAULT_DOUBLE_MS,
    DEFAULT_HOLD_MS,
    DEFAULT_PRESS_EVENT,
    DEFAULT_RELEASE_EVENT,
    DEFAULT_REPEAT_MS,
    DOMAIN,
    GESTURE_DOUBLE,
    GESTURE_HOLD_REPEAT,
    GESTURE_LONG,
    GESTURE_LONG_RELEASE,
    GESTURES,
    SLOTS,
    SUBENTRY_BUTTON,
)
from .gesture import GestureDetector, GestureSettings

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

_IGNORED_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


@dataclass(frozen=True, slots=True)
class ButtonConfig:
    """One physical button, read from a button subentry."""

    slot: str
    entities: list[str]
    actions: dict[str, list[dict[str, Any]]]
    repeat: bool


def buttons_from_entry(entry: ConfigEntry) -> list[ButtonConfig]:
    """Return the entry's buttons in Pico order."""
    buttons = [
        ButtonConfig(
            slot=sub.data[CONF_SLOT],
            entities=list(sub.data.get(CONF_ENTITIES, [])),
            actions=dict(sub.data.get(CONF_ACTIONS, {})),
            repeat=bool(sub.data.get(CONF_REPEAT, False)),
        )
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_BUTTON and sub.data.get(CONF_SLOT) in SLOTS
    ]
    return sorted(buttons, key=lambda b: SLOTS.index(b.slot))


def settings_for_button(
    options: dict[str, Any], button: ButtonConfig
) -> GestureSettings:
    """Build detector settings from what the user configured for a button."""
    has_long = bool(button.actions.get(GESTURE_LONG))
    return GestureSettings(
        hold_ms=int(options.get(CONF_HOLD_MS, DEFAULT_HOLD_MS)),
        double_ms=int(options.get(CONF_DOUBLE_MS, DEFAULT_DOUBLE_MS)),
        repeat_ms=int(options.get(CONF_REPEAT_MS, DEFAULT_REPEAT_MS)),
        detect_double=bool(button.actions.get(GESTURE_DOUBLE)),
        detect_hold=has_long or bool(button.actions.get(GESTURE_LONG_RELEASE)),
        repeat=button.repeat and has_long,
    )


async def async_validate_sequence(
    hass: HomeAssistant, actions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate an action list the same way scripts and automations do.

    Raises vol.Invalid or HomeAssistantError on bad config.
    """
    return await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(actions))


class ButtonActionsController:
    """Runtime for one remote (one config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._press = entry.data.get(CONF_PRESS_EVENT, DEFAULT_PRESS_EVENT)
        self._release = entry.data.get(CONF_RELEASE_EVENT, DEFAULT_RELEASE_EVENT)
        self.buttons = buttons_from_entry(entry)
        # entity_id -> (slot, detector)
        self._detectors: dict[str, tuple[str, GestureDetector]] = {}
        # (slot, gesture) -> compiled script
        self._scripts: dict[tuple[str, str], Script] = {}
        # slot -> listener that mirrors gestures onto that slot's event entity
        self._gesture_listeners: dict[str, Callable[[str], None]] = {}
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def slots(self) -> list[str]:
        """Configured button slots, in Pico order."""
        return [button.slot for button in self.buttons]

    @callback
    def register_gesture_listener(
        self, slot: str, listener: Callable[[str], None]
    ) -> CALLBACK_TYPE:
        """Let the event entity for a slot see every gesture."""
        self._gesture_listeners[slot] = listener

        @callback
        def _remove() -> None:
            self._gesture_listeners.pop(slot, None)

        return _remove

    async def async_start(self) -> None:
        """Compile actions, create detectors and start listening."""
        for button in self.buttons:
            for gesture in GESTURES:
                if actions := button.actions.get(gesture):
                    await self._async_compile(button.slot, gesture, actions)

            settings = settings_for_button(self.entry.options, button)
            for entity_id in button.entities:
                self._detectors[entity_id] = (
                    button.slot,
                    GestureDetector(
                        self._schedule, self._make_emitter(button.slot), settings
                    ),
                )

        if self._detectors:
            self._unsub = async_track_state_change_event(
                self.hass, list(self._detectors), self._handle_state_change
            )

    async def async_stop(self) -> None:
        """Stop listening, drop pending timers and stop running actions."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        for _slot, detector in self._detectors.values():
            detector.reset()
        self._detectors.clear()
        for script in self._scripts.values():
            await script.async_stop()
        self._scripts.clear()

    # -- internals ------------------------------------------------------------

    async def _async_compile(
        self, slot: str, gesture: str, actions: list[dict[str, Any]]
    ) -> None:
        try:
            sequence = await async_validate_sequence(self.hass, actions)
        except (vol.Invalid, HomeAssistantError) as err:
            _LOGGER.error(
                "%s: invalid %s action for the %s button, skipping: %s",
                self.entry.title,
                gesture,
                slot,
                err,
            )
            return
        name = f"{self.entry.title} {slot} {gesture}"
        self._scripts[(slot, gesture)] = Script(
            self.hass,
            sequence,
            name,
            DOMAIN,
            running_description=name,
            logger=_LOGGER,
            script_mode=SCRIPT_MODE_PARALLEL,
            max_runs=10,
            max_exceeded="silent",
        )

    def _schedule(self, delay: float, action: Callable[[], None]) -> CALLBACK_TYPE:
        @callback
        def _fire(_now: Any) -> None:
            action()

        return async_call_later(self.hass, delay, _fire)

    def _make_emitter(self, slot: str) -> Callable[[str], None]:
        @callback
        def _emit(gesture: str) -> None:
            self._on_gesture(slot, gesture)

        return _emit

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        if (found := self._detectors.get(entity_id)) is None:
            return
        _slot, detector = found

        if new_state is None or new_state.state in _IGNORED_STATES:
            detector.reset()
            return
        # Coming back from unavailable or a restart restores the last event;
        # that is not a new button press.
        if old_state is None or old_state.state in _IGNORED_STATES:
            return
        # An event entity's state is the time of the last event, so an
        # unchanged state means nothing new happened.
        if new_state.state == old_state.state:
            return

        event_type = new_state.attributes.get("event_type")
        if event_type == self._press:
            detector.press()
        elif event_type == self._release:
            detector.release()

    @callback
    def _on_gesture(self, slot: str, gesture: str) -> None:
        _LOGGER.debug("%s: %s %s", self.entry.title, slot, gesture)
        if gesture == GESTURE_HOLD_REPEAT:
            # Repeat ticks re-run the long-press action.
            script = self._scripts.get((slot, GESTURE_LONG))
        else:
            if (listener := self._gesture_listeners.get(slot)) is not None:
                listener(gesture)
            script = self._scripts.get((slot, gesture))
        if script is None:
            return

        variables = {
            "remote": self.entry.title,
            "button": slot,
            "gesture": gesture,
        }
        self.entry.async_create_background_task(
            self.hass,
            script.async_run(variables, Context()),
            f"{DOMAIN} {self.entry.title} {slot} {gesture}",
        )
