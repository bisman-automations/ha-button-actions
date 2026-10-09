"""Core Lutron Caséta Picos as a button source, and remote reconfigure."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
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
from custom_components.button_actions.lutron import async_pico_buttons

PICO_BUTTONS = ["on", "raise", "stop", "lower", "off"]
LIGHT_ON = [{"action": "light.turn_on", "target": {"area_id": "kitchen"}}]


@pytest.fixture
def pico(hass: HomeAssistant) -> str:
    """A Pico registered by core Lutron Caséta."""
    lutron_entry = MockConfigEntry(domain="lutron_caseta")
    lutron_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=lutron_entry.entry_id,
        identifiers={("lutron_caseta", "71234567")},
        name="Kitchen Pico",
    )
    return device.id


@pytest.fixture(autouse=True)
def mock_pico_buttons():
    with (
        patch(
            "custom_components.button_actions.config_flow.async_pico_buttons",
            return_value=PICO_BUTTONS,
        ) as mock,
    ):
        yield mock


def _button(slot: str, entities: list[str], actions: dict | None = None):
    return ConfigSubentryData(
        data={
            CONF_SLOT: slot,
            CONF_ENTITIES: entities,
            CONF_ACTIONS: actions or {},
            CONF_REPEAT: False,
        },
        subentry_type=SUBENTRY_BUTTON,
        title=f"{slot} button",
        unique_id=slot,
    )


def _timing() -> dict:
    return {CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200}


def _press(hass: HomeAssistant, device_id: str, button: str, action: str) -> None:
    hass.bus.async_fire(
        "lutron_caseta_button_event",
        {"device_id": device_id, "button_type": button, "action": action},
    )


async def _settle(hass: HomeAssistant, seconds: float = 0) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)
    if seconds:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await hass.async_block_till_done(wait_background_tasks=True)


# ---------------------------------------------------------------------------
# Button discovery
# ---------------------------------------------------------------------------


async def test_pico_buttons_from_device_triggers(hass: HomeAssistant) -> None:
    triggers = {
        "dev": [
            {"domain": "lutron_caseta", "type": t, "subtype": s}
            for t in ("press", "release")
            for s in ("off", "on", "raise", "group_1_button_1")
        ]
        + [{"domain": "other", "subtype": "lower"}]
    }
    with patch(
        "custom_components.button_actions.lutron.async_get_device_automations",
        return_value=triggers,
    ):
        assert await async_pico_buttons(hass, "dev") == ["on", "raise", "off"]


# ---------------------------------------------------------------------------
# Setup from a Pico
# ---------------------------------------------------------------------------


async def _start_lutron_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert "device" in result["menu_options"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "device"}
    )


async def test_setup_from_pico(hass: HomeAssistant, pico: str) -> None:
    with patch("custom_components.button_actions.async_setup_entry", return_value=True):
        result = await _start_lutron_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_id": pico}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen Pico"
    assert result["data"] == {
        CONF_SOURCE: SOURCE_LUTRON,
        "device_id": pico,
        CONF_PICO_BUTTONS: PICO_BUTTONS,
    }
    subs = [s.unique_id for s in result["result"].subentries.values()]
    assert subs == PICO_BUTTONS


async def test_setup_rejects_non_pico(
    hass: HomeAssistant, pico: str, mock_pico_buttons
) -> None:
    mock_pico_buttons.return_value = []
    result = await _start_lutron_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": pico}
    )
    # Not a Pico, and no event entities either.
    assert result["errors"] == {"device_id": "no_buttons_on_device"}


async def test_setup_rejects_pico_used_by_entities(
    hass: HomeAssistant, pico: str
) -> None:
    """An event-entity remote on the same Pico would double every press."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "event",
        "lutron_caseta_events",
        "on",
        device_id=pico,
        suggested_object_id="kitchen_pico_on",
    )
    MockConfigEntry(
        domain=DOMAIN,
        minor_version=2,
        data={CONF_SOURCE: SOURCE_EVENT_ENTITY},
        subentries_data=[_button("on", ["event.kitchen_pico_on"])],
    ).add_to_hass(hass)

    result = await _start_lutron_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": pico}
    )
    assert result["errors"] == {"device_id": "pico_in_use"}


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


async def _lutron_remote(hass: HomeAssistant, pico: str, actions: dict):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Pico",
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_LUTRON,
            "device_id": pico,
            CONF_PICO_BUTTONS: PICO_BUTTONS,
        },
        options=_timing(),
        subentries_data=[_button(slot, [], actions.get(slot)) for slot in PICO_BUTTONS],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    return entry


async def test_lutron_gestures(hass: HomeAssistant, pico: str) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    await _lutron_remote(
        hass,
        pico,
        {
            "on": {"short_press": LIGHT_ON},
            "stop": {"double_press": LIGHT_ON, "long_press": LIGHT_ON},
        },
    )

    _press(hass, pico, "on", "press")
    _press(hass, pico, "on", "release")
    await _settle(hass)
    assert len(calls) == 1  # no double action on "on": instant

    _press(hass, pico, "stop", "press")
    _press(hass, pico, "stop", "release")
    _press(hass, pico, "stop", "press")
    await _settle(hass)
    assert len(calls) == 2  # double press
    _press(hass, pico, "stop", "release")
    await _settle(hass, 1)

    _press(hass, pico, "stop", "press")
    await _settle(hass, 0.7)
    assert len(calls) == 3  # long press

    # Other Picos and multi_tap events are ignored.
    _press(hass, "some-other-pico", "on", "press")
    _press(hass, "some-other-pico", "on", "release")
    _press(hass, pico, "on", "multi_tap")
    await _settle(hass, 1)
    assert len(calls) == 3


async def test_lutron_add_button_only_offers_pico_buttons(
    hass: HomeAssistant, pico: str
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_LUTRON,
            "device_id": pico,
            CONF_PICO_BUTTONS: ["on", "off"],
        },
        options=_timing(),
        subentries_data=[_button("on", [])],
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BUTTON),
        context={"source": config_entries.SOURCE_USER},
    )
    schema = result["data_schema"].schema
    assert CONF_ENTITIES not in schema
    slot = next(v for k, v in schema.items() if k == CONF_SLOT)
    assert slot.config["options"] == ["off"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_SLOT: "off"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"short_press": LIGHT_ON}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    off = next(s for s in entry.subentries.values() if s.unique_id == "off")
    assert off.data[CONF_ENTITIES] == []
    assert off.data[CONF_ACTIONS] == {"short_press": LIGHT_ON}


# ---------------------------------------------------------------------------
# Reconfigure
# ---------------------------------------------------------------------------


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


def _event_remote(hass: HomeAssistant, pico: str | None = None) -> MockConfigEntry:
    registry = er.async_get(hass)
    for slot in ("on", "off"):
        registry.async_get_or_create(
            "event",
            "lutron_caseta_events",
            slot,
            device_id=pico,
            suggested_object_id=f"kitchen_remote_{slot}",
        )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Remote",
        minor_version=2,
        data={"press_event_type": "press", "release_event_type": "release"},
        options=_timing(),
        subentries_data=[
            _button("on", ["event.kitchen_remote_on"], {"short_press": LIGHT_ON}),
            _button("off", ["event.kitchen_remote_off"]),
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_rename_and_event_types(hass: HomeAssistant) -> None:
    entry = _event_remote(hass)
    hass.states.async_set(
        "event.kitchen_remote_on", "unknown", {"event_types": ["down", "up"]}
    )
    result = await _reconfigure(hass, entry)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Kitchen"}
    )
    # Every event type the buttons report, plus the old press/release names.
    assert result["step_id"] == "reconfigure_events"
    assert list(result["data_schema"].schema) == ["down", "up", "press", "release"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"down": "press", "up": "release", "press": "ignore", "release": "ignore"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Kitchen"
    assert entry.data["event_roles"] == {
        "down": "press",
        "up": "release",
        "press": "ignore",
        "release": "ignore",
    }
    assert "press_event_type" not in entry.data


async def test_switch_event_remote_to_pico(hass: HomeAssistant, pico: str) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    entry = _event_remote(hass, pico)

    result = await _reconfigure(hass, entry)
    # The Pico the event entities belong to is suggested.
    schema = result["data_schema"].schema
    device_key = next(k for k in schema if k == "device_id")
    assert device_key.description["suggested_value"] == pico

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Kitchen Remote",
            "device_id": pico,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    await _settle(hass)

    assert entry.data[CONF_SOURCE] == SOURCE_LUTRON
    assert entry.data["device_id"] == pico
    subs = {s.unique_id: s for s in entry.subentries.values()}
    assert subs["on"].data[CONF_ENTITIES] == []
    assert subs["on"].data[CONF_ACTIONS] == {"short_press": LIGHT_ON}

    _press(hass, pico, "on", "press")
    _press(hass, pico, "on", "release")
    await _settle(hass)
    assert len(calls) == 1


async def test_switch_blocked_when_pico_lacks_buttons(
    hass: HomeAssistant, pico: str, mock_pico_buttons
) -> None:
    mock_pico_buttons.return_value = ["on"]
    entry = _event_remote(hass, pico)
    result = await _reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Kitchen Remote",
            "device_id": pico,
        },
    )
    assert result["errors"] == {"device_id": "buttons_missing"}
    assert result["description_placeholders"]["missing"] == "Off button"
    assert CONF_SOURCE not in entry.data


async def test_reconfigure_pico_remote_rename(hass: HomeAssistant, pico: str) -> None:
    entry = await _lutron_remote(hass, pico, {})
    result = await _reconfigure(hass, entry)
    assert result["step_id"] == "reconfigure_lutron"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Island Pico", "device_id": pico}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Island Pico"
    assert entry.data["device_id"] == pico
