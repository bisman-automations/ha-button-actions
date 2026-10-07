"""End-to-end: source event entity -> gesture -> action."""

from __future__ import annotations

import itertools
from datetime import timedelta

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.button_actions.const import (
    CONF_ACTIONS,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_HOLD_MS,
    CONF_PRESS_EVENT,
    CONF_RELEASE_EVENT,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    DOMAIN,
    SUBENTRY_BUTTON,
)

ON = "event.kitchen_remote_on"
RAISE = "event.kitchen_remote_raise"
_ticks = itertools.count()


def _fire(hass: HomeAssistant, entity_id: str, event_type: str) -> None:
    """Mimic an event entity: new timestamp state + event_type attribute."""
    stamp = (dt_util.utcnow() + timedelta(microseconds=next(_ticks))).isoformat()
    hass.states.async_set(entity_id, stamp, {"event_type": event_type})


async def _advance(hass: HomeAssistant, seconds: float) -> None:
    # Let queued state changes reach the detector before moving the clock.
    await hass.async_block_till_done(wait_background_tasks=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


def _button(slot: str, entities: list[str], actions: dict, repeat: bool = False):
    return ConfigSubentryData(
        data={
            CONF_SLOT: slot,
            CONF_ENTITIES: entities,
            CONF_ACTIONS: actions,
            CONF_REPEAT: repeat,
        },
        subentry_type=SUBENTRY_BUTTON,
        title=f"{slot} button",
        unique_id=slot,
    )


async def _setup(hass: HomeAssistant, actions: dict, repeat: list[str] | None = None):
    for entity_id in (ON, RAISE):
        hass.states.async_set(entity_id, "unknown")
        _fire(hass, entity_id, "release")  # a prior, restored event
    repeat = repeat or []
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Remote",
        version=1,
        minor_version=2,
        data={CONF_PRESS_EVENT: "press", CONF_RELEASE_EVENT: "release"},
        options={CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200},
        subentries_data=[
            _button("on", [ON], actions.get("on", {}), "on" in repeat),
            _button("raise", [RAISE], actions.get("raise", {}), "raise" in repeat),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


def _light_on(data: dict) -> list[dict]:
    return [{"action": "light.turn_on", "target": {"area_id": "kitchen"}, "data": data}]


async def test_short_double_long(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    await _setup(
        hass,
        {
            "on": {
                "short_press": _light_on({"brightness_pct": 100}),
                "double_press": _light_on({"brightness_pct": 50}),
                "long_press": _light_on({"transition": 60}),
            }
        },
    )

    _fire(hass, ON, "press")
    _fire(hass, ON, "release")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == []  # waiting for a possible second press
    await _advance(hass, 0.4)
    assert [c.data for c in calls] == [{"area_id": ["kitchen"], "brightness_pct": 100}]

    calls.clear()
    _fire(hass, ON, "press")
    _fire(hass, ON, "release")
    _fire(hass, ON, "press")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c.data["brightness_pct"] for c in calls] == [50]
    _fire(hass, ON, "release")
    await _advance(hass, 1)
    assert len(calls) == 1

    calls.clear()
    _fire(hass, ON, "press")
    await _advance(hass, 0.7)
    assert [c.data["transition"] for c in calls] == [60]


async def test_hold_repeat_and_release(hass: HomeAssistant) -> None:
    on_calls = async_mock_service(hass, "light", "turn_on")
    stop_calls = async_mock_service(hass, "cover", "stop_cover")
    await _setup(
        hass,
        {
            "raise": {
                "short_press": _light_on({"brightness_step_pct": 10}),
                "long_press": _light_on({"brightness_step_pct": 5}),
                "long_release": [
                    {"action": "cover.stop_cover", "target": {"entity_id": "cover.x"}}
                ],
            }
        },
        repeat=["raise"],
    )

    # No double action on raise: short press fires immediately on release.
    _fire(hass, RAISE, "press")
    _fire(hass, RAISE, "release")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c.data["brightness_step_pct"] for c in on_calls] == [10]

    on_calls.clear()
    _fire(hass, RAISE, "press")
    await _advance(hass, 0.65)
    for _ in range(3):
        await _advance(hass, 0.21)
    assert [c.data["brightness_step_pct"] for c in on_calls] == [5, 5, 5, 5]
    _fire(hass, RAISE, "release")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(stop_calls) == 1
    await _advance(hass, 1)
    assert len(on_calls) == 4


async def test_restore_and_unavailable_are_not_presses(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    await _setup(hass, {"raise": {"short_press": _light_on({})}})

    hass.states.async_set(RAISE, "unavailable")
    _fire(hass, RAISE, "press")  # restored state after coming back
    await hass.async_block_till_done(wait_background_tasks=True)
    _fire(hass, RAISE, "release")
    await _advance(hass, 1)
    assert calls == []


async def test_gesture_event_entity(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    await _setup(hass, {"on": {"short_press": _light_on({})}})
    gesture_entity = "event.kitchen_remote_on_top"
    assert hass.states.get(gesture_entity) is not None

    _fire(hass, ON, "press")
    _fire(hass, ON, "release")
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(gesture_entity)
    assert state.attributes["event_type"] == "short_press"


async def test_unload(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    entry = await _setup(hass, {"raise": {"short_press": _light_on({})}})
    assert await hass.config_entries.async_unload(entry.entry_id)
    _fire(hass, RAISE, "press")
    _fire(hass, RAISE, "release")
    await _advance(hass, 1)
    assert calls == []


async def test_removing_button_removes_its_entity(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    entry = await _setup(hass, {"raise": {"short_press": _light_on({})}})
    assert hass.states.get("event.kitchen_remote_raise_up") is not None

    raise_sub = next(s for s in entry.subentries.values() if s.unique_id == "raise")
    hass.config_entries.async_remove_subentry(entry, raise_sub.subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert er.async_get(hass).async_get("event.kitchen_remote_raise_up") is None
    _fire(hass, RAISE, "press")
    _fire(hass, RAISE, "release")
    await _advance(hass, 1)
    assert calls == []


async def test_migrate_from_1_0(hass: HomeAssistant) -> None:
    """1.0.0 kept buttons in data and actions in options."""
    calls = async_mock_service(hass, "light", "turn_on")
    for entity_id in (ON, RAISE):
        hass.states.async_set(entity_id, "unknown")
        _fire(hass, entity_id, "release")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Remote",
        version=1,
        minor_version=1,
        data={
            "buttons": {"on": [ON], "raise": [RAISE]},
            CONF_PRESS_EVENT: "press",
            CONF_RELEASE_EVENT: "release",
        },
        options={
            CONF_HOLD_MS: 600,
            CONF_DOUBLE_MS: 300,
            CONF_REPEAT_MS: 200,
            CONF_ACTIONS: {"raise": {"long_press": _light_on({"x": 1})}},
            CONF_REPEAT: ["raise"],
        },
    )
    entry.add_to_hass(hass)
    # A gesture entity created by 1.0.0 keeps its entity ID.
    er.async_get(hass).async_get_or_create(
        "event",
        DOMAIN,
        f"{entry.entry_id}_raise",
        config_entry=entry,
        suggested_object_id="kitchen_remote_raise_up",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.minor_version == 2
    assert "buttons" not in entry.data
    assert set(entry.options) == {CONF_HOLD_MS, CONF_DOUBLE_MS, CONF_REPEAT_MS}
    subs = {s.unique_id: s for s in entry.subentries.values()}
    assert set(subs) == {"on", "raise"}
    assert subs["raise"].title == "Raise button"
    assert subs["raise"].data[CONF_REPEAT] is True
    assert subs["raise"].data[CONF_ACTIONS] == {"long_press": _light_on({"x": 1})}
    assert subs["on"].data[CONF_ACTIONS] == {}
    assert hass.states.get("event.kitchen_remote_raise_up") is not None

    # And it still works.
    _fire(hass, RAISE, "press")
    await _advance(hass, 0.65)
    assert len(calls) == 1
