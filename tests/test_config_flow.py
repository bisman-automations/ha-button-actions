"""Config and options flow tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
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
    DOMAIN,
    SUBENTRY_BUTTON,
)

AUTOMATION = {
    "id": "1712345678901",
    "alias": "Dining Room Remote",
    "description": "",
    "use_blueprint": {
        "path": "gist.githubusercontent.com/lutron_pico_events.yaml",
        "input": {
            "entity_on": ["event.dining_room_remote_on"],
            "entity_raise": ["event.dining_room_remote_raise"],
            "entity_stop": ["event.dining_room_remote_middle"],
            "entity_lower": ["event.dining_room_remote_lower"],
            "entity_off": ["event.dining_room_remote_off"],
            "automation_mode": "queued",
            "short_click_action_stop": [
                {
                    "action": "cover.toggle",
                    "target": {"area_id": "dining_room"},
                    "data": {},
                }
            ],
            "short_click_action_raise": [
                {
                    "action": "light.turn_on",
                    "target": {"area_id": "dining_room"},
                    "data": {"brightness_step_pct": 10},
                }
            ],
            "double_click_action_stop": [
                {
                    "action": "light.turn_on",
                    "data": {"brightness_pct": 100},
                    "target": {"device_id": ["41a6ccbd4bb62c97514db4fcc0461566"]},
                }
            ],
            "long_click_action_stop": [
                {
                    "action": "light.turn_off",
                    "target": {"device_id": ["41a6ccbd4bb62c97514db4fcc0461566"]},
                    "data": {},
                }
            ],
            "short_click_action_lower": [],
        },
    },
}


@pytest.fixture(autouse=True)
def mock_setup_entry():
    with (
        patch(
            "custom_components.button_actions.async_setup_entry", return_value=True
        ) as mock,
        patch("custom_components.button_actions.async_unload_entry", return_value=True),
    ):
        yield mock


async def _write_automation(hass: HomeAssistant, automations: list[dict]) -> str:
    path = Path(hass.config.path("automations.yaml"))
    await hass.async_add_executor_job(
        path.write_text, yaml.safe_dump(automations, sort_keys=False)
    )
    entity_id = "automation.dining_room_remote"
    er.async_get(hass).async_get_or_create(
        "automation",
        "automation",
        automations[0]["id"],
        suggested_object_id="dining_room_remote",
    )
    hass.states.async_set(entity_id, "on", {"friendly_name": "Dining Room Remote"})
    return entity_id


async def test_import_blueprint(hass: HomeAssistant) -> None:
    turn_off = async_mock_service(hass, "automation", "turn_off")
    entity_id = await _write_automation(hass, [AUTOMATION])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_blueprint"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"automation": entity_id, "disable_source": True}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dining Room Remote"
    entry = result["result"]
    subs = {sub.unique_id: sub for sub in entry.subentries.values()}
    assert list(subs) == ["on", "raise", "stop", "lower", "off"]
    assert subs["stop"].title == "Middle button"
    assert subs["stop"].data[CONF_ENTITIES] == ["event.dining_room_remote_middle"]
    stop_actions = subs["stop"].data[CONF_ACTIONS]
    assert set(stop_actions) == {"short_press", "double_press", "long_press"}
    assert stop_actions["short_press"][0]["action"] == "cover.toggle"
    assert subs["lower"].data[CONF_ACTIONS] == {}  # empty blueprint input dropped
    # Blueprint defaults kept so the remote feels the same.
    assert entry.options[CONF_HOLD_MS] == 1000
    assert entry.options[CONF_DOUBLE_MS] == 250
    assert len(turn_off) == 1
    assert turn_off[0].data["entity_id"] in (entity_id, [entity_id])


async def test_import_rejects_non_blueprint(hass: HomeAssistant) -> None:
    plain = {"id": "999", "alias": "x", "triggers": [], "actions": []}
    entity_id = await _write_automation(hass, [plain])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_blueprint"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"automation": entity_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"automation": "not_blueprint"}


async def test_manual_and_duplicate(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Office Remote",
            "on": ["event.office_on"],
            "off": ["event.office_off"],
            "press_event_type": "press",
            "release_event_type": "release",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subs = {s.unique_id: s for s in result["result"].subentries.values()}
    assert {k: v.data[CONF_ENTITIES] for k, v in subs.items()} == {
        "on": ["event.office_on"],
        "off": ["event.office_off"],
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Again",
            "on": ["event.office_on"],
            "press_event_type": "press",
            "release_event_type": "release",
        },
    )
    assert result["errors"] == {"base": "already_configured"}


def _remote(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office Remote",
        version=1,
        minor_version=2,
        data={"press_event_type": "press", "release_event_type": "release"},
        options={CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 400},
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_SLOT: "on",
                    CONF_ENTITIES: ["event.office_on"],
                    CONF_ACTIONS: {},
                    CONF_REPEAT: False,
                },
                subentry_type=SUBENTRY_BUTTON,
                title="On button",
                unique_id="on",
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_flow_is_timing(hass: HomeAssistant) -> None:
    entry = _remote(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"double_ms": 250, "hold_ms": 500, "repeat_ms": 300}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"double_ms": 250, "hold_ms": 500, "repeat_ms": 300}


LONG_ACTION = [
    {
        "action": "fan.increase_speed",
        "target": {"device_id": "db1e6cbab45d3bb1c2f8967a271e7f20"},
    }
]


async def test_add_button(hass: HomeAssistant) -> None:
    entry = _remote(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BUTTON),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["step_id"] == "user"
    # "on" is taken, so the dropdown starts at the next free button.
    schema = result["data_schema"].schema
    slot_selector = next(v for k, v in schema.items() if k == CONF_SLOT)
    assert "on" not in slot_selector.config["options"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_SLOT: "raise", CONF_ENTITIES: ["event.office_on"]}
    )
    assert result["errors"] == {CONF_ENTITIES: "already_configured"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_SLOT: "raise", CONF_ENTITIES: ["event.office_up"]}
    )
    assert result["step_id"] == "actions"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"long_press": LONG_ACTION, "repeat": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    sub = next(s for s in entry.subentries.values() if s.unique_id == "raise")
    assert sub.title == "Raise button"
    assert dict(sub.data) == {
        CONF_SLOT: "raise",
        CONF_ENTITIES: ["event.office_up"],
        CONF_ACTIONS: {"long_press": LONG_ACTION},
        CONF_REPEAT: True,
    }


async def test_reconfigure_button(hass: HomeAssistant) -> None:
    entry = _remote(hass)
    sub = next(iter(entry.subentries.values()))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BUTTON),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": sub.subentry_id,
        },
    )
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_ENTITIES: ["event.office_on"], "short_press": [{"not_an_action": 1}]},
    )
    assert result["errors"] == {"short_press": "invalid_action"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_ENTITIES: ["event.office_on"], "double_press": LONG_ACTION},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[sub.subentry_id].data[CONF_ACTIONS] == {
        "double_press": LONG_ACTION
    }


async def test_all_buttons_added(hass: HomeAssistant) -> None:
    entry = _remote(hass)
    for slot in (
        "raise",
        "stop",
        "lower",
        "off",
        "button_1",
        "button_2",
        "button_3",
        "button_4",
    ):
        hass.config_entries.async_add_subentry(
            entry,
            config_entries.ConfigSubentry(
                data={CONF_SLOT: slot, CONF_ENTITIES: [f"event.x_{slot}"]},
                subentry_type=SUBENTRY_BUTTON,
                title=slot,
                unique_id=slot,
            ),
        )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BUTTON),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "all_buttons_added"
