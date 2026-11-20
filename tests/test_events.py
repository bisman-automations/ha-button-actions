"""Event roles for different kinds of button devices (1.5.0)."""

from __future__ import annotations

from datetime import timedelta
import itertools

import pytest
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
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    CONF_SOURCE,
    DOMAIN,
    SOURCE_EVENT_ENTITY,
    SUBENTRY_BUTTON,
)
from custom_components.button_actions.events import resolve_role, suggest_roles
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util


@pytest.mark.parametrize(
    ("event_types", "expected"),
    [
        # Lutron (lutron-caseta-events)
        (["press", "release"], {"press": "press", "release": "release"}),
        # Core Lutron Caséta event entities (Home Assistant 2026.11): a Pico
        # reports both edges, a keypad reports the press only.
        (
            ["press_start", "press_end"],
            {"press_start": "press", "press_end": "release"},
        ),
        (["press_start"], {"press_start": "click"}),
        # Matter momentary switch with release and long press
        (
            ["initial_press", "short_release", "long_press", "long_release"],
            {
                "initial_press": "press",
                "short_release": "release",
                "long_press": "ignore",
                "long_release": "release",
            },
        ),
        # Matter momentary switch with press only
        (["initial_press"], {"initial_press": "click"}),
        # Matter momentary switch with long press but no short release
        (
            ["initial_press", "long_press", "long_release"],
            {"initial_press": "click", "long_press": "hold", "long_release": "release"},
        ),
        # Matter multi-press switch: the device counts presses itself
        (
            [
                "multi_press_1",
                "multi_press_2",
                "multi_press_3",
                "long_press",
                "long_release",
            ],
            {
                "multi_press_1": "single",
                "multi_press_2": "double",
                "multi_press_3": "ignore",
                "long_press": "hold",
                "long_release": "release",
            },
        ),
        # Zigbee-style names
        (
            ["single", "double", "hold", "release"],
            {
                "single": "single",
                "double": "double",
                "hold": "hold",
                "release": "release",
            },
        ),
        # A latching switch isn't a button
        (["switch_latched"], {"switch_latched": "ignore"}),
        # Press with no release: each press is a click
        (["press"], {"press": "click"}),
        # Home Assistant 2026.12 standard types: device-counted presses
        (
            ["single_press", "multi_press"],
            {"single_press": "single", "multi_press": "double"},
        ),
        # With both edges reported, our own detection wins
        (
            ["single_press", "multi_press", "press_start", "press_end"],
            {
                "single_press": "ignore",
                "multi_press": "ignore",
                "press_start": "press",
                "press_end": "release",
            },
        ),
        # Release only (or a whole press reported as press_end, 2026.11 ISY)
        (["press_end"], {"press_end": "click"}),
        (
            ["single_press", "press_end"],
            {"single_press": "single", "press_end": "release"},
        ),
    ],
)
def test_suggest_roles(event_types, expected) -> None:
    assert suggest_roles(event_types) == expected


def test_overrides_win() -> None:
    assert resolve_role("up", ["down", "up"], {"up": "release"}) == "release"
    assert resolve_role("up", ["down", "up"], {}) == "release"
    assert resolve_role("weird", ["weird"], {}) == "ignore"


@pytest.mark.parametrize(
    ("event_type", "attributes", "expected"),
    [
        ("multi_press", {"press_count": 1}, "single"),
        ("multi_press", {"press_count": 2}, "double"),
        ("multi_press", {"press_count": 3}, "ignore"),
        ("multi_press", {}, "double"),
        # Home Assistant 2026.11 name and count attribute
        ("multi_press_end", {"multi_press_count": 1}, "single"),
        ("multi_press_end", {"multi_press_count": 2}, "double"),
        # Other types ignore a count
        ("single_press", {"press_count": 2}, "single"),
    ],
)
def test_counted_presses(event_type, attributes, expected) -> None:
    types = ["single_press", event_type]
    assert resolve_role(event_type, types, {}, attributes) == expected


def test_counted_override_still_uses_count() -> None:
    assert (
        resolve_role(
            "multi_press",
            ["multi_press"],
            {"multi_press": "single"},
            {"press_count": 2},
        )
        == "double"
    )
    assert (
        resolve_role(
            "multi_press", ["multi_press"], {"multi_press": "hold"}, {"press_count": 2}
        )
        == "hold"
    )


# ---------------------------------------------------------------------------
# End to end with Matter-style buttons
# ---------------------------------------------------------------------------

ON, OFF = "event.hub_button_1", "event.hub_button_2"
LIGHT = [{"action": "light.turn_on", "target": {"entity_id": "light.x"}}]
_ticks = itertools.count()


def _fire(hass: HomeAssistant, entity_id: str, event_type: str, types, **extra) -> None:
    stamp = (dt_util.utcnow() + timedelta(microseconds=next(_ticks))).isoformat()
    hass.states.async_set(
        entity_id, stamp, {"event_type": event_type, "event_types": types, **extra}
    )


async def _settle(hass: HomeAssistant, seconds: float = 0) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)
    if seconds:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await hass.async_block_till_done(wait_background_tasks=True)


def _button(slot, entity, repeat=False):
    return ConfigSubentryData(
        data={
            CONF_SLOT: slot,
            CONF_ENTITIES: [entity],
            CONF_ACTIONS: {
                "short_press": LIGHT,
                "double_press": LIGHT,
                "long_press": LIGHT,
                "long_release": LIGHT,
            },
            CONF_REPEAT: repeat,
        },
        subentry_type=SUBENTRY_BUTTON,
        title=slot,
        unique_id=slot,
    )


async def _hub(hass: HomeAssistant, types, repeat=False):
    hass.data["light_calls"] = async_mock_service(hass, "light", "turn_on")
    events = []
    hass.bus.async_listen(
        "button_actions_gesture", callback(lambda event: events.append(event))
    )
    for entity_id in (ON, OFF):
        hass.states.async_set(entity_id, "unknown", {"event_types": types})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hub Buttons",
        minor_version=2,
        data={CONF_SOURCE: SOURCE_EVENT_ENTITY, "event_roles": {}},
        options={CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200},
        subentries_data=[_button("on", ON, repeat), _button("off", OFF)],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    return events


def _seen(events):
    return [(e.data["button"], e.data["gesture"]) for e in events]


MOMENTARY = ["initial_press", "short_release", "long_press", "long_release"]
MULTI = ["multi_press_1", "multi_press_2", "long_press", "long_release"]


async def test_matter_momentary(hass: HomeAssistant) -> None:
    events = await _hub(hass, MOMENTARY)
    # short, double
    for _ in range(2):
        _fire(hass, ON, "initial_press", MOMENTARY)
        _fire(hass, ON, "short_release", MOMENTARY)
        await _settle(hass, 0.5)
    _fire(hass, OFF, "initial_press", MOMENTARY)
    _fire(hass, OFF, "short_release", MOMENTARY)
    _fire(hass, OFF, "initial_press", MOMENTARY)
    _fire(hass, OFF, "short_release", MOMENTARY)
    await _settle(hass, 0.5)
    # hold: our own timer decides; the device's long_press is ignored
    _fire(hass, ON, "initial_press", MOMENTARY)
    await _settle(hass, 0.7)
    _fire(hass, ON, "long_press", MOMENTARY)
    _fire(hass, ON, "long_release", MOMENTARY)
    await _settle(hass, 0.5)
    assert _seen(events) == [
        ("on", "short_press"),
        ("on", "short_press"),
        ("off", "double_press"),
        ("on", "long_press"),
        ("on", "long_release"),
    ]


async def test_matter_press_only(hass: HomeAssistant) -> None:
    events = await _hub(hass, ["initial_press"])
    _fire(hass, ON, "initial_press", ["initial_press"])
    await _settle(hass, 0.5)
    _fire(hass, ON, "initial_press", ["initial_press"])
    _fire(hass, ON, "initial_press", ["initial_press"])
    await _settle(hass, 0.5)
    assert _seen(events) == [("on", "short_press"), ("on", "double_press")]


async def test_matter_multi_press_with_repeat(hass: HomeAssistant) -> None:
    events = await _hub(hass, MULTI, repeat=True)
    calls = hass.data["light_calls"]
    _fire(hass, ON, "multi_press_1", MULTI)
    _fire(hass, ON, "multi_press_2", MULTI)
    await _settle(hass)
    _fire(hass, ON, "long_press", MULTI)
    await _settle(hass, 0.21)
    await _settle(hass, 0.21)
    _fire(hass, ON, "long_release", MULTI)
    await _settle(hass, 1)
    assert _seen(events) == [
        ("on", "short_press"),
        ("on", "double_press"),
        ("on", "long_press"),
        ("on", "long_release"),
    ]
    # long press + 2 repeats, then the release action; plus short and double
    assert len(calls) == 6


STANDARD = ["single_press", "multi_press", "long_press_start", "long_press_end"]


async def test_standard_counted_presses(hass: HomeAssistant) -> None:
    """Home Assistant 2026.12's single_press and multi_press with press_count."""
    events = await _hub(hass, STANDARD)
    _fire(hass, ON, "single_press", STANDARD)
    await _settle(hass, 0.5)
    _fire(hass, ON, "multi_press", STANDARD, press_count=2)
    await _settle(hass, 0.5)
    _fire(hass, OFF, "multi_press", STANDARD, press_count=1)
    await _settle(hass, 0.5)
    _fire(hass, OFF, "multi_press", STANDARD, press_count=5)
    await _settle(hass, 0.5)
    assert _seen(events) == [
        ("on", "short_press"),
        ("on", "double_press"),
        ("off", "short_press"),
    ]
