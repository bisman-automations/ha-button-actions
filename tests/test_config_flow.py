"""Config and options flow tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.button_actions.const import (
    CONF_ACTIONS,
    CONF_BUTTONS,
    CONF_DOUBLE_MS,
    CONF_HOLD_MS,
    CONF_REPEAT,
    DOMAIN,
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
    assert result["data"][CONF_BUTTONS] == {
        "on": ["event.dining_room_remote_on"],
        "raise": ["event.dining_room_remote_raise"],
        "stop": ["event.dining_room_remote_middle"],
        "lower": ["event.dining_room_remote_lower"],
        "off": ["event.dining_room_remote_off"],
    }
    actions = result["options"][CONF_ACTIONS]
    assert set(actions) == {"stop", "raise"}  # empty lower action dropped
    assert set(actions["stop"]) == {"short_press", "double_press", "long_press"}
    assert actions["stop"]["short_press"][0]["action"] == "cover.toggle"
    # Blueprint defaults kept so the remote feels the same.
    assert result["options"][CONF_HOLD_MS] == 1000
    assert result["options"][CONF_DOUBLE_MS] == 250
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
    assert result["data"][CONF_BUTTONS] == {
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


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office Remote",
        data={
            CONF_BUTTONS: {"on": ["event.office_on"], "raise": ["event.office_up"]},
            "press_event_type": "press",
            "release_event_type": "release",
        },
        options={CONF_ACTIONS: {}, CONF_REPEAT: []},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["on", "raise", "timing", "sources", "save"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "raise"}
    )
    assert result["step_id"] == "raise"
    long_action = [
        {
            "action": "fan.increase_speed",
            "target": {"device_id": "db1e6cbab45d3bb1c2f8967a271e7f20"},
        }
    ]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"long_press": long_action, "repeat": True}
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "raise"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"short_press": [{"not_an_action": 1}]}
    )
    assert result["errors"] == {"short_press": "invalid_action"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"long_press": long_action, "repeat": True}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "timing"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"double_ms": 250, "hold_ms": 500, "repeat_ms": 300}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ACTIONS] == {"raise": {"long_press": long_action}}
    assert entry.options[CONF_REPEAT] == ["raise"]
    assert entry.options[CONF_HOLD_MS] == 500
