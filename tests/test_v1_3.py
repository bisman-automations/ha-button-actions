"""Device triggers, Repairs, and the smarter blueprint import (1.3.0)."""

from __future__ import annotations

import itertools
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.button_actions import device_trigger, repairs
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
    CONF_SOURCE_AUTOMATION,
    DOMAIN,
    SOURCE_EVENT_ENTITY,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
)

ON = "event.office_remote_on"
OFF = "event.office_remote_off"
LIGHT_ON = [{"action": "light.turn_on", "target": {"area_id": "office"}}]
_ticks = itertools.count()


def _fire(hass: HomeAssistant, entity_id: str, event_type: str) -> None:
    stamp = (dt_util.utcnow() + timedelta(microseconds=next(_ticks))).isoformat()
    hass.states.async_set(entity_id, stamp, {"event_type": event_type})


async def _settle(hass: HomeAssistant, seconds: float = 0) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)
    if seconds:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await hass.async_block_till_done(wait_background_tasks=True)


def _button(slot, entities, actions=None, detect_all=False):
    return ConfigSubentryData(
        data={
            CONF_SLOT: slot,
            CONF_ENTITIES: entities,
            CONF_ACTIONS: actions or {},
            CONF_REPEAT: False,
            CONF_DETECT_ALL: detect_all,
        },
        subentry_type=SUBENTRY_BUTTON,
        title=f"{slot} button",
        unique_id=slot,
    )


def _timing():
    return {CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200}


async def _event_remote(hass: HomeAssistant, buttons, data=None):
    for entity_id in (ON, OFF):
        er.async_get(hass).async_get_or_create(
            "event", "test", entity_id, suggested_object_id=entity_id.split(".")[1]
        )
        hass.states.async_set(entity_id, "unknown")
        _fire(hass, entity_id, "release")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office Remote",
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_EVENT_ENTITY,
            "press_event_type": "press",
            "release_event_type": "release",
            **(data or {}),
        },
        options=_timing(),
        subentries_data=buttons,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    return entry


def _device_id(hass: HomeAssistant, entry) -> str:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    return device.id


# ---------------------------------------------------------------------------
# Device triggers
# ---------------------------------------------------------------------------


async def test_device_triggers_listed(hass: HomeAssistant) -> None:
    entry = await _event_remote(hass, [_button("on", [ON]), _button("off", [OFF])])
    device_id = _device_id(hass, entry)
    triggers = await device_trigger.async_get_triggers(hass, device_id)
    assert {(t["subtype"], t["type"]) for t in triggers} == {
        (slot, gesture)
        for slot in ("on", "off")
        for gesture in ("short_press", "double_press", "long_press", "long_release")
    }
    assert all(t["domain"] == DOMAIN and t["device_id"] == device_id for t in triggers)


async def test_device_trigger_fires_automation(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "automation")
    entry = await _event_remote(hass, [_button("on", [ON], {"short_press": LIGHT_ON})])
    async_mock_service(hass, "light", "turn_on")
    device_id = _device_id(hass, entry)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "triggers": [
                        {
                            "trigger": "device",
                            "domain": DOMAIN,
                            "device_id": device_id,
                            "type": "short_press",
                            "subtype": "on",
                        }
                    ],
                    "actions": [{"action": "test.automation"}],
                }
            ]
        },
    )
    _fire(hass, ON, "press")
    _fire(hass, ON, "release")
    await _settle(hass)
    assert len(calls) == 1


async def test_detect_all_reports_double_without_action(hass: HomeAssistant) -> None:
    """With detect_all, a double press is seen even with no double action."""
    events = []
    hass.bus.async_listen("button_actions_gesture", events.append)
    await _event_remote(
        hass,
        [
            _button("on", [ON], {"short_press": LIGHT_ON}, detect_all=True),
            _button("off", [OFF], {"short_press": LIGHT_ON}),
        ],
    )
    async_mock_service(hass, "light", "turn_on")

    for entity_id in (ON, OFF):
        _fire(hass, entity_id, "press")
        _fire(hass, entity_id, "release")
        _fire(hass, entity_id, "press")
        _fire(hass, entity_id, "release")
    await _settle(hass, 1)

    seen = [(e.data["button"], e.data["gesture"]) for e in events]
    assert ("on", "double_press") in seen
    # Without detect_all, two quick presses are two short presses.
    assert seen.count(("off", "short_press")) == 2


# ---------------------------------------------------------------------------
# Repairs
# ---------------------------------------------------------------------------


async def test_automation_enabled_issue_and_fix(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "automation.office_remote", "on", {"friendly_name": "Office Remote"}
    )
    entry = await _event_remote(
        hass,
        [_button("on", [ON])],
        data={CONF_SOURCE_AUTOMATION: "automation.office_remote"},
    )
    issue_id = f"automation_enabled_{entry.entry_id}"
    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.is_fixable

    turn_off = async_mock_service(hass, "automation", "turn_off")
    flow = await repairs.async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["step_id"] == "confirm"
    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert turn_off[0].data["entity_id"] in (
        "automation.office_remote",
        ["automation.office_remote"],
    )

    # Once it's off, the issue clears by itself.
    hass.states.async_set(
        "automation.office_remote", "off", {"friendly_name": "Office Remote"}
    )
    await _settle(hass)
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_missing_entities_issue(hass: HomeAssistant) -> None:
    entry = await _event_remote(
        hass, [_button("on", [ON]), _button("off", ["event.gone"])]
    )
    issue_id = f"source_missing_{entry.entry_id}"
    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entities"] == "event.gone"

    # The entity comes back (re-paired), and the issue clears.
    er.async_get(hass).async_get_or_create(
        "event", "test", "gone", suggested_object_id="gone"
    )
    await _settle(hass)
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    # Unloading the remote drops its issues.
    hass.states.async_remove("event.gone")
    er.async_get(hass).async_remove("event.gone")
    await _settle(hass)
    assert issues.async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_missing_pico_issue(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office Pico",
        minor_version=2,
        data={
            CONF_SOURCE: SOURCE_LUTRON,
            "device_id": "no-such-device",
            CONF_PICO_BUTTONS: ["on"],
        },
        options=_timing(),
        subentries_data=[_button("on", [])],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"source_missing_{entry.entry_id}"
    )
    assert issue is not None and issue.translation_key == "pico_missing"


# ---------------------------------------------------------------------------
# Smarter import
# ---------------------------------------------------------------------------


def _blueprint(automation_id: str, prefix: str) -> dict:
    return {
        "id": automation_id,
        "alias": f"{prefix.title()} Remote",
        "use_blueprint": {
            "path": "gist.githubusercontent.com/lutron_pico_events.yaml",
            "input": {
                "entity_on": [f"event.{prefix}_remote_on"],
                "entity_off": [f"event.{prefix}_remote_off"],
                "short_click_action_on": LIGHT_ON,
            },
        },
    }


@pytest.fixture
def no_setup():
    with (
        patch("custom_components.button_actions.async_setup_entry", return_value=True),
        patch("custom_components.button_actions.async_unload_entry", return_value=True),
    ):
        yield


async def _write_automations(hass: HomeAssistant, automations: list[dict], pico=None):
    path = Path(hass.config.path("automations.yaml"))
    await hass.async_add_executor_job(
        path.write_text, yaml.safe_dump(automations, sort_keys=False)
    )
    registry = er.async_get(hass)
    for item in automations:
        prefix = item["alias"].split()[0].lower()
        registry.async_get_or_create(
            "automation",
            "automation",
            item["id"],
            suggested_object_id=f"{prefix}_remote",
        )
        hass.states.async_set(
            f"automation.{prefix}_remote", "on", {"friendly_name": item["alias"]}
        )
        for slot in ("on", "off"):
            registry.async_get_or_create(
                "event",
                "lutron_caseta_events",
                f"{prefix}_{slot}",
                device_id=pico,
                suggested_object_id=f"{prefix}_remote_{slot}",
            )


@pytest.fixture
def pico(hass: HomeAssistant) -> str:
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    return (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=lutron.entry_id,
            identifiers={("lutron_caseta", "7001")},
            name="Kitchen Pico",
        )
        .id
    )


async def test_import_offers_pico(hass: HomeAssistant, pico: str, no_setup) -> None:
    async_mock_service(hass, "automation", "turn_off")
    await _write_automations(hass, [_blueprint("101", "kitchen")], pico=pico)
    with patch(
        "custom_components.button_actions.config_flow.async_pico_buttons",
        return_value=["on", "raise", "stop", "lower", "off"],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_blueprint"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"automation": "automation.kitchen_remote"}
        )
        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "import_choice"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_pico"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data[CONF_SOURCE] == SOURCE_LUTRON
    assert entry.data["device_id"] == pico
    assert entry.data[CONF_SOURCE_AUTOMATION] == "automation.kitchen_remote"
    subs = {s.unique_id: s for s in entry.subentries.values()}
    assert subs["on"].data[CONF_ENTITIES] == []
    assert subs["on"].data[CONF_ACTIONS] == {"short_press": LIGHT_ON}


async def test_import_without_pico_goes_straight_through(
    hass: HomeAssistant, no_setup
) -> None:
    async_mock_service(hass, "automation", "turn_off")
    await _write_automations(hass, [_blueprint("102", "den")])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_blueprint"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"automation": "automation.den_remote"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data[CONF_SOURCE] == SOURCE_EVENT_ENTITY
    assert result["result"].data[CONF_SOURCE_AUTOMATION] == "automation.den_remote"


async def test_import_all(hass: HomeAssistant, no_setup) -> None:
    turn_off = async_mock_service(hass, "automation", "turn_off")
    await _write_automations(
        hass,
        [
            _blueprint("201", "den"),
            _blueprint("202", "attic"),
            _blueprint("203", "porch"),
        ],
    )
    # One is already imported, so it isn't offered again.
    MockConfigEntry(
        domain=DOMAIN,
        minor_version=2,
        data={CONF_SOURCE_AUTOMATION: "automation.porch_remote"},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_all"}
    )
    assert result["step_id"] == "import_all"
    options = next(
        v for k, v in result["data_schema"].schema.items() if k == "automations"
    ).config["options"]
    assert {o["value"] for o in options} == {
        "automation.den_remote",
        "automation.attic_remote",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"automations": ["automation.den_remote", "automation.attic_remote"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await _settle(hass)

    titles = sorted(
        e.title
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.title != "Mock Title"
    )
    assert titles == ["Attic Remote", "Den Remote"]
    turned_off = turn_off[0].data["entity_id"]
    assert set(turned_off) == {"automation.den_remote", "automation.attic_remote"}


async def test_import_all_nothing_left(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_all"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_blueprint_automations"
