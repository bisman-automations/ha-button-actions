"""Duplicate a remote, and download diagnostics (1.4.0)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.button_actions.config_flow import replace_text
from custom_components.button_actions.const import (
    CONF_ACTIONS,
    CONF_DETECT_ALL,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_HOLD_MS,
    CONF_PICO_BUTTONS,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    CONF_SOURCE,
    DOMAIN,
    SOURCE_EVENT_ENTITY,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
)
from custom_components.button_actions.diagnostics import (
    async_get_config_entry_diagnostics,
)

BOYS_ON = [
    {
        "action": "light.turn_on",
        "target": {"area_id": "boys_bedroom", "entity_id": "light.boys_bedroom_lamp"},
        "data": {"brightness_pct": 100},
    }
]
BOYS_STOP = [{"action": "cover.toggle", "target": {"area_id": "boys_bedroom"}}]


def _button(slot, entities, actions, repeat=False, detect_all=False):
    return ConfigSubentryData(
        data={
            CONF_SLOT: slot,
            CONF_ENTITIES: entities,
            CONF_ACTIONS: actions,
            CONF_REPEAT: repeat,
            CONF_DETECT_ALL: detect_all,
        },
        subentry_type=SUBENTRY_BUTTON,
        title=f"{slot} button",
        unique_id=slot,
    )


@pytest.fixture
def boys_remote(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boy's Bedroom Remote",
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_EVENT_ENTITY,
            "press_event_type": "press",
            "release_event_type": "release",
        },
        options={CONF_HOLD_MS: 1000, CONF_DOUBLE_MS: 250, CONF_REPEAT_MS: 400},
        subentries_data=[
            _button("on", ["event.boys_on"], {"short_press": BOYS_ON}, detect_all=True),
            _button("stop", ["event.boys_middle"], {"short_press": BOYS_STOP}, True),
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def no_setup():
    with (
        patch("custom_components.button_actions.async_setup_entry", return_value=True),
        patch("custom_components.button_actions.async_unload_entry", return_value=True),
    ):
        yield


def test_replace_text() -> None:
    assert replace_text(BOYS_ON, "boys_bedroom", "girls_bedroom") == [
        {
            "action": "light.turn_on",
            "target": {
                "area_id": "girls_bedroom",
                "entity_id": "light.girls_bedroom_lamp",
            },
            "data": {"brightness_pct": 100},
        }
    ]
    # Keys and non-strings are left alone.
    assert replace_text({"boys_bedroom": 1, "n": 2}, "boys", "girls") == {
        "boys_bedroom": 1,
        "n": 2,
    }


async def _start_duplicate(hass: HomeAssistant, source_id: str, find="", replace=""):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "duplicate"}
    )
    assert result["step_id"] == "duplicate"
    user_input = {"remote": source_id, "name": "Girl's Bedroom Remote"}
    if find:
        user_input |= {"find": find, "replace": replace}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "duplicate_source"
    return result


async def test_duplicate_to_event_entities(
    hass: HomeAssistant, boys_remote, no_setup
) -> None:
    result = await _start_duplicate(
        hass, boys_remote.entry_id, "boys_bedroom", "girls_bedroom"
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "duplicate_entities"}
    )
    # Only the buttons the original has are asked for.
    assert set(result["data_schema"].schema) == {"on", "stop"}

    # Reusing the original's entities is refused.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"on": ["event.boys_on"], "stop": ["event.girls_middle"]}
    )
    assert result["errors"] == {"base": "already_configured"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"on": ["event.girls_on"], "stop": ["event.girls_middle"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    copy = result["result"]
    assert copy.title == "Girl's Bedroom Remote"
    assert copy.data[CONF_SOURCE] == SOURCE_EVENT_ENTITY
    assert dict(copy.options) == dict(boys_remote.options)

    subs = {s.unique_id: s for s in copy.subentries.values()}
    on = subs["on"].data
    assert on[CONF_ENTITIES] == ["event.girls_on"]
    assert on[CONF_ACTIONS]["short_press"][0]["target"] == {
        "area_id": "girls_bedroom",
        "entity_id": "light.girls_bedroom_lamp",
    }
    assert on[CONF_DETECT_ALL] is True
    assert subs["stop"].data[CONF_REPEAT] is True

    # The original is untouched.
    original = {s.unique_id: s for s in boys_remote.subentries.values()}
    assert original["on"].data[CONF_ACTIONS] == {"short_press": BOYS_ON}


async def test_duplicate_to_pico(hass: HomeAssistant, boys_remote, no_setup) -> None:
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    pico = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=lutron.entry_id,
            identifiers={("lutron_caseta", "9001")},
            name="Girls Pico",
        )
        .id
    )
    result = await _start_duplicate(hass, boys_remote.entry_id)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "duplicate_pico"}
    )

    with patch(
        "custom_components.button_actions.config_flow.async_pico_buttons",
        return_value=["on", "off"],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_id": pico}
        )
    assert result["errors"] == {"device_id": "buttons_missing"}
    assert result["description_placeholders"]["missing"] == "Middle button"

    with patch(
        "custom_components.button_actions.config_flow.async_pico_buttons",
        return_value=["on", "raise", "stop", "lower", "off"],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_id": pico}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    copy = result["result"]
    assert copy.data == {
        CONF_SOURCE: SOURCE_LUTRON,
        "device_id": pico,
        CONF_PICO_BUTTONS: ["on", "raise", "stop", "lower", "off"],
    }
    assert all(s.data[CONF_ENTITIES] == [] for s in copy.subentries.values())


async def test_duplicate_with_no_remotes(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "duplicate"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_remotes"


async def test_diagnostics(hass: HomeAssistant, boys_remote) -> None:
    hass.states.async_set("event.boys_on", "unknown")
    hass.states.async_set("event.boys_middle", "unknown")
    assert await hass.config_entries.async_setup(boys_remote.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, boys_remote)
    assert diag["remote"]["title"] == "Boy's Bedroom Remote"
    assert diag["remote"]["options"][CONF_HOLD_MS] == 1000
    on = next(b for b in diag["buttons"] if b["button"] == "on")
    # detect_all turns on double and hold detection with no action for them.
    assert on["detection"] == {"double": True, "hold": True, "repeat": False}
    assert on["entity_states"]["event.boys_on"]["state"] == "unknown"
    runtime = diag["runtime"]
    assert runtime["source"] == SOURCE_EVENT_ENTITY
    assert runtime["listening"] is True
    assert runtime["detectors"]["event.boys_on"] == {"button": "on", "state": "idle"}
    assert runtime["compiled_actions"] == ["on.short_press", "stop.short_press"]
    assert diag["issues"] == []
