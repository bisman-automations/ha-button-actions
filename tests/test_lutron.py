"""Core Lutron Caséta Picos as a button source, and remote reconfigure."""

from __future__ import annotations

from datetime import timedelta
import itertools
from unittest.mock import patch

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
    CONF_LUTRON_INPUT,
    CONF_PICO_BUTTONS,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    CONF_SOURCE,
    DOMAIN,
    LUTRON_INPUT_BUS,
    SOURCE_EVENT_ENTITY,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
    slot_label,
)
from custom_components.button_actions.lutron import LutronButton, async_pico_buttons
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

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


def _infos(slots: list[str], **kwargs) -> list[LutronButton]:
    return [LutronButton(slot=slot, name=slot_label(slot), **kwargs) for slot in slots]


@pytest.fixture(autouse=True)
def mock_lutron_buttons():
    with patch(
        "custom_components.button_actions.config_flow.async_lutron_buttons",
        return_value=_infos(PICO_BUTTONS),
    ) as mock:
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
        assert result["step_id"] == "lutron_confirm"
        assert "2026.11" in result["description_placeholders"]["source_note"]
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
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
    hass: HomeAssistant, pico: str, mock_lutron_buttons
) -> None:
    mock_lutron_buttons.return_value = []
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
    hass: HomeAssistant, pico: str, mock_lutron_buttons
) -> None:
    mock_lutron_buttons.return_value = _infos(["on"])
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


# ---------------------------------------------------------------------------
# Home Assistant 2026.11 event entities
# ---------------------------------------------------------------------------

_PRESS_TYPES = ("press_start", "press_end")
_ticks = itertools.count()


def _triggers(device_id: str, slots: list[str]) -> dict:
    return {
        device_id: [
            {"domain": "lutron_caseta", "type": action, "subtype": slot}
            for action in ("press", "release")
            for slot in slots
        ]
    }


def _core_button(hass: HomeAssistant, device_id: str, slot: str, name: str, types):
    """A core lutron_caseta event entity, as Home Assistant 2026.11 creates."""
    return er.async_get(hass).async_get_or_create(
        "event",
        "lutron_caseta",
        f"{device_id}-{slot}",
        suggested_object_id=f"kitchen_{slot}",
        original_name=name,
        device_id=device_id,
        capabilities={"event_types": list(types)},
    )


def _entity_press(hass: HomeAssistant, entity_id: str, event_type: str, types) -> None:
    stamp = (dt_util.utcnow() + timedelta(microseconds=next(_ticks))).isoformat()
    hass.states.async_set(
        entity_id,
        stamp,
        {"event_type": event_type, "event_types": list(types)},
    )


async def test_keypad_buttons_include_names_outside_pico_slots(hass: HomeAssistant):
    """Keypads, shade remotes and Athena use Lutron's own button names."""
    triggers = _triggers("dev", ["Morning", "Away", "on"])
    triggers["dev"].append(
        {"domain": "lutron_caseta", "type": "press", "subtype": "open_all"}
    )
    with patch(
        "custom_components.button_actions.lutron.async_get_device_automations",
        return_value=triggers,
    ):
        from custom_components.button_actions.lutron import async_lutron_buttons

        found = await async_lutron_buttons(hass, "dev")
    assert [button.slot for button in found] == ["on", "Away", "Morning", "open_all"]


async def test_setup_keypad_explains_missing_release(
    hass: HomeAssistant, pico: str, mock_lutron_buttons
) -> None:
    """A keypad event entity has no release, so the bus event keeps the timing."""
    mock_lutron_buttons.return_value = [
        LutronButton(
            slot="Morning",
            name="Morning",
            entity_id="event.hall_morning",
            event_types=("press_start",),
        ),
        LutronButton(
            slot="Away",
            name="Away",
            entity_id="event.hall_away",
            event_types=("press_start",),
        ),
    ]
    with patch("custom_components.button_actions.async_setup_entry", return_value=True):
        result = await _start_lutron_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_id": pico, "name": "Hall Keypad"}
        )
        assert result["step_id"] == "lutron_confirm"
        note = result["description_placeholders"]["source_note"]
        assert "release" in note
        assert "Keypads" in note
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PICO_BUTTONS] == ["Morning", "Away"]
    assert all(
        sub.data[CONF_ENTITIES] == [] for sub in result["result"].subentries.values()
    )


async def test_keypad_cannot_be_added_twice(
    hass: HomeAssistant, pico: str, mock_lutron_buttons
) -> None:
    mock_lutron_buttons.return_value = [
        LutronButton(slot="Morning", name="Morning"),
        LutronButton(slot="Away", name="Away"),
    ]
    with patch("custom_components.button_actions.async_setup_entry", return_value=True):
        result = await _start_lutron_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_id": pico}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await _start_lutron_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": pico}
    )
    assert result["errors"] == {"device_id": "pico_in_use"}


async def test_bus_fallback_without_event_entities(
    hass: HomeAssistant, pico: str
) -> None:
    """2026.8 through 2026.10 have no Lutron event entities, so the bus is used."""
    calls = async_mock_service(hass, "light", "turn_on")
    entry = await _lutron_remote(hass, pico, {"on": {"short_press": LIGHT_ON}})
    assert set(entry.runtime_data._detectors) == set(PICO_BUTTONS)
    _press(hass, pico, "on", "press")
    _press(hass, pico, "on", "release")
    await _settle(hass)
    assert len(calls) == 1


async def test_existing_pico_migrates_when_events_report_release(
    hass: HomeAssistant, pico: str
) -> None:
    """Same entry, slots, actions and unique ids; only the entity id is filled in."""
    on = _core_button(hass, pico, "on", "On", _PRESS_TYPES)
    off = _core_button(hass, pico, "off", "Off", _PRESS_TYPES)
    calls = async_mock_service(hass, "light", "turn_on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Pico",
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_LUTRON,
            "device_id": pico,
            CONF_PICO_BUTTONS: ["on", "off"],
        },
        options=_timing(),
        subentries_data=[
            _button("on", [], {"short_press": LIGHT_ON}),
            _button("off", []),
        ],
    )
    entry_id = entry.entry_id
    entry.add_to_hass(hass)
    with patch(
        "custom_components.button_actions.lutron.async_get_device_automations",
        return_value=_triggers(pico, ["on", "off"]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _settle(hass)

    assert entry.entry_id == entry_id
    assert entry.data[CONF_SOURCE] == SOURCE_LUTRON
    subs = {sub.unique_id: sub for sub in entry.subentries.values()}
    assert set(subs) == {"on", "off"}
    assert subs["on"].data[CONF_ACTIONS] == {"short_press": LIGHT_ON}
    assert subs["on"].data[CONF_ENTITIES] == [on.entity_id]
    assert subs["off"].data[CONF_ENTITIES] == [off.entity_id]

    hass.states.async_set(on.entity_id, "unknown", {"event_types": list(_PRESS_TYPES)})
    await _settle(hass)
    _entity_press(hass, on.entity_id, "press_start", _PRESS_TYPES)
    await _settle(hass)
    _entity_press(hass, on.entity_id, "press_end", _PRESS_TYPES)
    await _settle(hass)
    assert len(calls) == 1

    # The bus event for that button is not listened to as well.
    _press(hass, pico, "on", "press")
    _press(hass, pico, "on", "release")
    await _settle(hass, 1)
    assert len(calls) == 1


async def test_keypad_release_stays_on_the_bus_event(
    hass: HomeAssistant, pico: str
) -> None:
    morning = _core_button(hass, pico, "Morning", "Morning", ["press_start"])
    calls = async_mock_service(hass, "light", "turn_on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hall Keypad",
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_LUTRON,
            "device_id": pico,
            CONF_PICO_BUTTONS: ["Morning"],
        },
        options=_timing(),
        subentries_data=[_button("Morning", [], {"short_press": LIGHT_ON})],
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.button_actions.lutron.async_get_device_automations",
        return_value=_triggers(pico, ["Morning"]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _settle(hass)

    sub = next(iter(entry.subentries.values()))
    assert sub.unique_id == "Morning"
    assert sub.data[CONF_ENTITIES] == []
    assert "Morning" in entry.runtime_data._detectors

    hass.states.async_set(
        morning.entity_id, "unknown", {"event_types": ["press_start"]}
    )
    await _settle(hass)
    _entity_press(hass, morning.entity_id, "press_start", ["press_start"])
    await _settle(hass, 1)
    assert len(calls) == 0

    _press(hass, pico, "Morning", "press")
    _press(hass, pico, "Morning", "release")
    await _settle(hass)
    assert len(calls) == 1


async def test_reconfigure_opts_out_of_event_entities(
    hass: HomeAssistant, pico: str, mock_lutron_buttons
) -> None:
    on = _core_button(hass, pico, "on", "On", _PRESS_TYPES)
    mock_lutron_buttons.return_value = [
        LutronButton(
            slot=slot,
            name=slot_label(slot),
            entity_id=f"event.kitchen_{slot}",
            event_types=_PRESS_TYPES,
        )
        for slot in PICO_BUTTONS
    ]
    calls = async_mock_service(hass, "light", "turn_on")
    with patch(
        "custom_components.button_actions.lutron.async_get_device_automations",
        return_value=_triggers(pico, PICO_BUTTONS),
    ):
        entry = await _lutron_remote(hass, pico, {"on": {"short_press": LIGHT_ON}})
        assert next(
            sub.data[CONF_ENTITIES]
            for sub in entry.subentries.values()
            if sub.unique_id == "on"
        ) == [on.entity_id]

        result = await _reconfigure(hass, entry)
        assert "use_event_entities" in {
            key.schema for key in result["data_schema"].schema
        }
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Kitchen Pico",
                "device_id": pico,
                "use_event_entities": False,
            },
        )
        await _settle(hass)

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_LUTRON_INPUT] == LUTRON_INPUT_BUS
    assert all(sub.data[CONF_ENTITIES] == [] for sub in entry.subentries.values())
    hass.states.async_set(on.entity_id, "unknown", {"event_types": list(_PRESS_TYPES)})
    await _settle(hass)
    _entity_press(hass, on.entity_id, "press_start", _PRESS_TYPES)
    _entity_press(hass, on.entity_id, "press_end", _PRESS_TYPES)
    await _settle(hass, 1)
    assert len(calls) == 0
    _press(hass, pico, "on", "press")
    _press(hass, pico, "on", "release")
    await _settle(hass)
    assert len(calls) == 1
