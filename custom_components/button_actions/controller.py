"""Wire source event entities to gesture detectors and action sequences."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_DEVICE_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.script import (
    SCRIPT_MODE_PARALLEL,
    Script,
    async_validate_actions_config,
)

from .const import (
    CONF_ACTIONS,
    CONF_DETECT_ALL,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_EVENT_ROLES,
    CONF_HOLD_MS,
    CONF_PRESS_EVENT,
    CONF_RELEASE_EVENT,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    CONF_SOURCE,
    CONF_SUPPORTS_DOUBLE,
    CONF_SUPPORTS_LONG,
    DEFAULT_DOUBLE_MS,
    DEFAULT_HOLD_MS,
    DEFAULT_PRESS_EVENT,
    DEFAULT_RELEASE_EVENT,
    DEFAULT_REPEAT_MS,
    DOMAIN,
    GESTURE_DOUBLE,
    GESTURE_EVENT,
    GESTURE_HOLD_REPEAT,
    GESTURE_LONG,
    GESTURE_LONG_RELEASE,
    GESTURE_SHORT,
    GESTURES,
    LUTRON_ACTION_PRESS,
    LUTRON_ACTION_RELEASE,
    LUTRON_BUTTON_EVENT,
    SLOTS,
    SOURCE_EVENT_ENTITY,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
)
from .events import (
    ROLE_CLICK,
    ROLE_DOUBLE,
    ROLE_HOLD,
    ROLE_PRESS,
    ROLE_RELEASE,
    ROLE_SINGLE,
    resolve_role,
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
    detect_all: bool = False


def buttons_from_entry(entry: ConfigEntry) -> list[ButtonConfig]:
    """Return the entry's buttons in Pico order."""
    buttons = [
        ButtonConfig(
            slot=sub.data[CONF_SLOT],
            entities=list(sub.data.get(CONF_ENTITIES, [])),
            actions=dict(sub.data.get(CONF_ACTIONS, {})),
            repeat=bool(sub.data.get(CONF_REPEAT, False)),
            detect_all=bool(sub.data.get(CONF_DETECT_ALL, False)),
        )
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_BUTTON and sub.data.get(CONF_SLOT) in SLOTS
    ]
    return sorted(buttons, key=lambda b: SLOTS.index(b.slot))


def event_role_overrides(data: Mapping[str, Any]) -> dict[str, str]:
    """The user's event-type roles, including the pre-1.5 press/release names."""
    overrides: dict[str, str] = {}
    if CONF_EVENT_ROLES not in data:
        # Before 1.5.0 a remote named one press and one release event type.
        overrides[data.get(CONF_PRESS_EVENT, DEFAULT_PRESS_EVENT)] = ROLE_PRESS
        overrides[data.get(CONF_RELEASE_EVENT, DEFAULT_RELEASE_EVENT)] = ROLE_RELEASE
    overrides.update(data.get(CONF_EVENT_ROLES) or {})
    return overrides


def _dispatch(detector: GestureDetector, role: str) -> None:
    if role == ROLE_PRESS:
        detector.press()
    elif role == ROLE_RELEASE:
        detector.release()
    elif role == ROLE_CLICK:
        detector.click()
    elif role == ROLE_SINGLE:
        detector.detected(GESTURE_SHORT)
    elif role == ROLE_DOUBLE:
        detector.detected(GESTURE_DOUBLE)
    elif role == ROLE_HOLD:
        detector.hold()


def remote_capabilities(data: Mapping[str, Any]) -> tuple[bool, bool]:
    """(supports double press, supports long press). Missing means yes."""
    return (
        bool(data.get(CONF_SUPPORTS_DOUBLE, True)),
        bool(data.get(CONF_SUPPORTS_LONG, True)),
    )


def supported_gestures(data: Mapping[str, Any]) -> list[str]:
    """The gestures this remote can produce, in display order."""
    double, long = remote_capabilities(data)
    return [
        gesture
        for gesture in GESTURES
        if (gesture != GESTURE_DOUBLE or double)
        and (gesture not in (GESTURE_LONG, GESTURE_LONG_RELEASE) or long)
    ]


def settings_for_button(
    options: dict[str, Any],
    button: ButtonConfig,
    supports_double: bool = True,
    supports_long: bool = True,
) -> GestureSettings:
    """Build detector settings from what the user configured for a button."""
    has_long = bool(button.actions.get(GESTURE_LONG))
    return GestureSettings(
        hold_ms=int(options.get(CONF_HOLD_MS, DEFAULT_HOLD_MS)),
        double_ms=int(options.get(CONF_DOUBLE_MS, DEFAULT_DOUBLE_MS)),
        repeat_ms=int(options.get(CONF_REPEAT_MS, DEFAULT_REPEAT_MS)),
        detect_double=supports_double
        and (button.detect_all or bool(button.actions.get(GESTURE_DOUBLE))),
        detect_hold=supports_long
        and (
            button.detect_all
            or has_long
            or bool(button.actions.get(GESTURE_LONG_RELEASE))
        ),
        repeat=supports_long and button.repeat and has_long,
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
        self.event_roles = event_role_overrides(entry.data)
        self.source = entry.data.get(CONF_SOURCE, SOURCE_EVENT_ENTITY)
        self._device_id: str | None = entry.data.get(CONF_DEVICE_ID)
        self.buttons = buttons_from_entry(entry)
        # Event-entity remotes: entity_id -> (slot, detector)
        # Lutron remotes: slot -> (slot, detector)
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

            settings = settings_for_button(
                self.entry.options, button, *remote_capabilities(self.entry.data)
            )
            keys = [button.slot] if self.source == SOURCE_LUTRON else button.entities
            for key in keys:
                self._detectors[key] = (
                    button.slot,
                    GestureDetector(
                        self._schedule, self._make_emitter(button.slot), settings
                    ),
                )

        if not self._detectors:
            return
        if self.source == SOURCE_LUTRON:
            device_id = self._device_id

            @callback
            def _is_this_pico(data: Mapping[str, Any]) -> bool:
                return data.get(CONF_DEVICE_ID) == device_id

            self._unsub = self.hass.bus.async_listen(
                LUTRON_BUTTON_EVENT, self._handle_lutron_event, _is_this_pico
            )
        else:
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

    @callback
    def diagnostics(self) -> dict[str, Any]:
        """Live state for download diagnostics."""
        return {
            "source": self.source,
            "event_role_overrides": self.event_roles,
            "listening": self._unsub is not None,
            "detectors": {
                key: {"button": slot, "state": detector.state}
                for key, (slot, detector) in self._detectors.items()
            },
            "compiled_actions": sorted(
                f"{slot}.{gesture}" for slot, gesture in self._scripts
            ),
            "running_actions": sorted(
                f"{slot}.{gesture}"
                for (slot, gesture), script in self._scripts.items()
                if script.is_running
            ),
        }

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
        _LOGGER.debug(
            "%s: %s %s -> %s (%s)",
            self.entry.title,
            entity_id,
            old_state.state if old_state else None,
            new_state.state if new_state else None,
            new_state.attributes.get("event_type") if new_state else None,
        )

        if new_state is None or new_state.state in _IGNORED_STATES:
            detector.reset()
            return
        # An entity being added (startup) or coming back from unavailable
        # restores its last event; that is not a new button press. From
        # "unknown", though, it is: that's a button that has never been
        # pressed, so this is its first real event.
        if old_state is None or old_state.state == STATE_UNAVAILABLE:
            return
        # An event entity's state is the time of the last event, so an
        # unchanged state means nothing new happened.
        if new_state.state == old_state.state:
            return

        event_type = new_state.attributes.get("event_type")
        if event_type is None:
            return
        role = resolve_role(
            event_type, new_state.attributes.get("event_types"), self.event_roles
        )
        _dispatch(detector, role)

    @callback
    def _fire_gesture_event(self, slot: str, gesture: str) -> None:
        """Back the device triggers ("On button double pressed")."""
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.entry.entry_id)}
        )
        self.hass.bus.async_fire(
            GESTURE_EVENT,
            {
                CONF_DEVICE_ID: device.id if device else None,
                "remote": self.entry.title,
                "button": slot,
                "gesture": gesture,
            },
        )

    @callback
    def _handle_lutron_event(self, event: Event) -> None:
        """Core Lutron fires one event per press and per release."""
        if (found := self._detectors.get(event.data.get("button_type"))) is None:
            return
        _slot, detector = found
        action = event.data.get("action")
        if action == LUTRON_ACTION_PRESS:
            detector.press()
        elif action == LUTRON_ACTION_RELEASE:
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
            self._fire_gesture_event(slot, gesture)
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
