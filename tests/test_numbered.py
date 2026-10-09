"""Numbered remotes with declared capabilities (1.6.0)."""

from __future__ import annotations

import itertools
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.button_actions import device_trigger
from custom_components.button_actions.const import (
    CONF_ACTIONS,
    CONF_DETECT_ALL,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_HOLD_MS,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    DOMAIN,
    SUBENTRY_BUTTON,
)
from custom_components.button_actions.controller import own_device

LIGHT = [{"action": "light.turn_on", "target": {"entity_id": "light.x"}}]
_ticks = itertools.count()


def _fire(hass: HomeAssistant, entity_id: str, event_type: str) -> None:
    stamp = (dt_util.utcnow() + timedelta(microseconds=next(_ticks))).isoformat()
    hass.states.async_set(
        entity_id,
        stamp,
        {"event_type": event_type, "event_types": ["initial_press", "short_release"]},
    )


async def _settle(hass: HomeAssistant, seconds: float = 0) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)
    if seconds:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await hass.async_block_till_done(wait_background_tasks=True)


def _button(n: int, actions=None):
    slot = f"button_{n}"
    return ConfigSubentryData(
        data={
            CONF_SLOT: slot,
            CONF_ENTITIES: [f"event.hub_{n}"],
            CONF_ACTIONS: actions or {},
            CONF_REPEAT: False,
            CONF_DETECT_ALL: False,
        },
        subentry_type=SUBENTRY_BUTTON,
        title=f"Scene button {n}",
        unique_id=slot,
    )


def _hub(hass: HomeAssistant, count=2, double=True, long=False, actions=None):
    for n in range(1, count + 1):
        hass.states.async_set(
            f"event.hub_{n}", "unknown", {"event_types": ["initial_press"]}
        )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hub Buttons",
        minor_version=2,
        data={
            "source": "event_entity",
            "event_roles": {},
            "layout": "numbered",
            "supports_double": double,
            "supports_long": long,
        },
        options={CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200},
        subentries_data=[
            _button(n, (actions or {}).get(n)) for n in range(1, count + 1)
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_names_titles_and_triggers(hass: HomeAssistant) -> None:
    entry = _hub(hass, double=True, long=False)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)

    titles = sorted(s.title for s in entry.subentries.values())
    assert titles == ["Button 1", "Button 2"]

    registry = er.async_get(hass)
    states = [
        hass.states.get(e.entity_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    ]
    assert sorted(s.name for s in states) == [
        "Hub Buttons Button 1",
        "Hub Buttons Button 2",
    ]
    # No long press on this remote, so it's not offered anywhere.
    assert states[0].attributes["event_types"] == ["short_press", "double_press"]

    device = own_device(hass, entry.entry_id)
    triggers = await device_trigger.async_get_triggers(hass, device.id)
    assert {t["type"] for t in triggers} == {"short_press", "double_press"}


async def test_ten_buttons_pad_numbers(hass: HomeAssistant) -> None:
    entry = _hub(hass, count=10)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    titles = sorted(s.title for s in entry.subentries.values())
    assert titles[:2] == ["Button 01", "Button 02"]
    assert titles[-1] == "Button 10"


async def test_unsupported_long_press_is_a_short_press(hass: HomeAssistant) -> None:
    """Without long press support, holding a button is just a press."""
    calls = async_mock_service(hass, "light", "turn_on")
    gestures = []
    hass.bus.async_listen(
        "button_actions_gesture", callback(lambda e: gestures.append(e.data["gesture"]))
    )
    entry = _hub(
        hass,
        double=False,
        long=False,
        actions={1: {"short_press": LIGHT, "long_press": LIGHT, "double_press": LIGHT}},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)

    _fire(hass, "event.hub_1", "initial_press")
    await _settle(hass, 1.5)
    _fire(hass, "event.hub_1", "short_release")
    await _settle(hass)
    # No double press either: two quick presses are two short presses.
    for _ in range(2):
        _fire(hass, "event.hub_1", "initial_press")
        _fire(hass, "event.hub_1", "short_release")
    await _settle(hass, 1)
    assert gestures == ["short_press", "short_press", "short_press"]
    assert len(calls) == 3


async def test_button_form_follows_capabilities(hass: HomeAssistant) -> None:
    entry = _hub(hass, double=False, long=False, actions={1: {"long_press": LIGHT}})
    sub = next(s for s in entry.subentries.values() if s.unique_id == "button_1")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BUTTON),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": sub.subentry_id,
        },
    )
    assert list(result["data_schema"].schema) == ["entities", "short_press"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entities": ["event.hub_1"], "short_press": LIGHT}
    )
    assert result["reason"] == "reconfigure_successful"
    # The hidden long-press action is kept for if long press is turned back on.
    assert entry.subentries[sub.subentry_id].data[CONF_ACTIONS] == {
        "long_press": LIGHT,
        "short_press": LIGHT,
    }


async def test_add_button_offers_next_numbers(hass: HomeAssistant) -> None:
    entry = _hub(hass, count=2)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BUTTON),
        context={"source": config_entries.SOURCE_USER},
    )
    slot = next(v for k, v in result["data_schema"].schema.items() if k == "slot")
    assert slot.config["options"][:2] == ["button_3", "button_4"]
    assert slot.config["options"][-1] == "button_12"
    assert slot.config["translation_key"] == "numbered_slot"


async def test_reconfigure_capabilities(hass: HomeAssistant) -> None:
    entry = _hub(hass, double=True, long=False)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Hub Buttons", "supports_double": False, "supports_long": True},
    )
    assert result["step_id"] == "reconfigure_events"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"initial_press": "click"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["supports_double"] is False
    assert entry.data["supports_long"] is True
    assert entry.data["layout"] == "numbered"
    assert entry.data["event_roles"] == {"initial_press": "click"}


async def test_duplicate_numbered(hass: HomeAssistant) -> None:
    source = _hub(hass, count=2, double=False, long=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "duplicate"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote": source.entry_id, "name": "Other Hub"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "duplicate_entities"}
    )
    assert result["step_id"] == "duplicate_numbered"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"button_1": ["event.other_1"], "button_2": ["event.other_2"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["result"].data
    assert data["layout"] == "numbered"
    assert data["supports_double"] is False
    assert data["supports_long"] is True
