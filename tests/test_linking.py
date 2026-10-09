"""Setting up from a device, and remotes shown on their real device (1.7.0)."""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.button_actions import device_trigger
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

MOMENTARY = ["initial_press", "short_release", "long_press", "long_release"]
_ticks = itertools.count()


def _hub(hass: HomeAssistant, event_types=MOMENTARY, count=2, name="Boys Hub"):
    """A Matter-style hub with button event entities, like a SwitchBot Hub 2."""
    matter = MockConfigEntry(domain="matter")
    matter.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=matter.entry_id,
        identifiers={("matter", name)},
        name=name,
        manufacturer="SwitchBot",
    )
    registry = er.async_get(hass)
    entity_ids = []
    for n in range(1, count + 1):
        reg = registry.async_get_or_create(
            "event",
            "matter",
            f"{name}-{n}",
            config_entry=matter,
            device_id=device.id,
            capabilities={"event_types": event_types},
            original_name="Button",
            suggested_object_id=f"{name.lower().replace(' ', '_')}_button_{n}",
        )
        hass.states.async_set(reg.entity_id, "unknown", {"event_types": event_types})
        entity_ids.append(reg.entity_id)
    return device, entity_ids


def _fire(hass: HomeAssistant, entity_id: str, event_type: str) -> None:
    stamp = (dt_util.utcnow() + timedelta(microseconds=next(_ticks))).isoformat()
    hass.states.async_set(
        entity_id, stamp, {"event_type": event_type, "event_types": MOMENTARY}
    )


async def _device_flow(hass: HomeAssistant, device_id: str, **extra):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["menu_options"][0] == "device"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "device"}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": device_id, **extra}
    )


# ---------------------------------------------------------------------------
# Setup from a device
# ---------------------------------------------------------------------------


async def test_setup_from_device(hass: HomeAssistant) -> None:
    device, entity_ids = _hub(hass)
    result = await _device_flow(hass, device.id)
    assert result["step_id"] == "device_confirm"
    assert result["description_placeholders"]["count"] == "2"
    assert "Button 1: Button" in result["description_placeholders"]["buttons"]
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults == {"supports_double": True, "supports_long": True}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.title == "Boys Hub"
    assert entry.data["layout"] == "numbered"
    assert entry.data["source_device"] == device.id
    subs = {s.unique_id: s.data[CONF_ENTITIES] for s in entry.subentries.values()}
    assert subs == {"button_1": [entity_ids[0]], "button_2": [entity_ids[1]]}
    await hass.async_block_till_done()

    # Its gesture entities live on the hub itself; no separate device.
    registry = er.async_get(hass)
    ours = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.device_id for e in ours} == {device.id}
    assert (
        dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
        is None
    )
    assert entry.entry_id in dr.async_get(hass).async_get(device.id).config_entries


async def test_press_only_device_defaults_to_no_long_press(hass: HomeAssistant) -> None:
    device, _ = _hub(hass, event_types=["initial_press"])
    result = await _device_flow(hass, device.id, name="Hub")
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults == {"supports_double": True, "supports_long": False}


async def test_device_without_buttons(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="hue")
    other.add_to_hass(hass)
    lamp = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("hue", "lamp")}, name="Lamp"
    )
    result = await _device_flow(hass, lamp.id)
    assert result["errors"] == {"device_id": "no_buttons_on_device"}


async def test_device_already_used(hass: HomeAssistant) -> None:
    device, _ = _hub(hass)
    result = await _device_flow(hass, device.id)
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    # Button Actions' own gesture entities on the hub aren't counted as buttons,
    # and the hub's real buttons are now in use.
    result = await _device_flow(hass, device.id)
    assert result["errors"] == {"device_id": "already_configured"}


# ---------------------------------------------------------------------------
# Linking existing remotes
# ---------------------------------------------------------------------------


def _remote(hass: HomeAssistant, entity_ids, title="Hub Remote", actions=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        minor_version=2,
        data={
            "source": "event_entity",
            "event_roles": {},
            "layout": "numbered",
        },
        options={CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200},
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_SLOT: f"button_{n}",
                    CONF_ENTITIES: [entity_id],
                    CONF_ACTIONS: actions or {},
                    CONF_REPEAT: False,
                },
                subentry_type=SUBENTRY_BUTTON,
                title=f"Button {n}",
                unique_id=f"button_{n}",
            )
            for n, entity_id in enumerate(entity_ids, start=1)
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_existing_remote_moves_onto_its_device(hass: HomeAssistant) -> None:
    device, entity_ids = _hub(hass)
    entry = _remote(hass, entity_ids)
    # Before 1.7.0 it had a "Button remote" device of its own.
    old = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Hub Remote",
    )
    registry = er.async_get(hass)
    old_entity = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry.entry_id}_button_1",
        config_entry=entry,
        device_id=old.id,
        suggested_object_id="hub_remote_button_1",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    moved = registry.async_get(old_entity.entity_id)
    assert moved is not None  # same entity ID
    assert moved.device_id == device.id
    assert dr.async_get(hass).async_get(old.id) is None


async def test_buttons_on_different_devices_keep_own_device(
    hass: HomeAssistant,
) -> None:
    _, first = _hub(hass, count=1, name="Hub A")
    _, second = _hub(hass, count=1, name="Hub B")
    entry = _remote(hass, [first[0], second[0]])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    own = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert own is not None
    ours = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {e.device_id for e in ours} == {own.id}


async def test_triggers_on_shared_device(hass: HomeAssistant) -> None:
    """Two remotes on one device each get their own triggers."""
    calls = async_mock_service(hass, "test", "automation")
    device, entity_ids = _hub(hass, count=2)
    first = _remote(hass, [entity_ids[0]], title="Left")
    second = _remote(hass, [entity_ids[1]], title="Right")
    # Setting up the integration loads both remotes.
    assert await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    assert second.state is config_entries.ConfigEntryState.LOADED

    triggers = await device_trigger.async_get_triggers(hass, device.id)
    assert {t["entry_id"] for t in triggers} == {first.entry_id, second.entry_id}

    right_trigger = next(
        t
        for t in triggers
        if t["entry_id"] == second.entry_id and t["type"] == "short_press"
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "triggers": [right_trigger],
                    "actions": [{"action": "test.automation"}],
                }
            ]
        },
    )
    # Left remote's Button 1 doesn't fire Right's trigger; Right's does.
    _fire(hass, entity_ids[0], "initial_press")
    _fire(hass, entity_ids[0], "short_release")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == []
    _fire(hass, entity_ids[1], "initial_press")
    _fire(hass, entity_ids[1], "short_release")
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1


@pytest.mark.parametrize("source_device_missing", [False, True])
async def test_pico_remote_on_pico(hass: HomeAssistant, source_device_missing) -> None:
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    pico = dr.async_get(hass).async_get_or_create(
        config_entry_id=lutron.entry_id,
        identifiers={("lutron_caseta", "123")},
        name="Kitchen Pico",
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Pico",
        minor_version=2,
        data={
            "source": "lutron_caseta",
            "device_id": "gone" if source_device_missing else pico.id,
            "pico_buttons": ["on", "off"],
        },
        options={CONF_HOLD_MS: 600, CONF_DOUBLE_MS: 300, CONF_REPEAT_MS: 200},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_SLOT: slot, CONF_ENTITIES: [], CONF_ACTIONS: {}},
                subentry_type=SUBENTRY_BUTTON,
                title=slot,
                unique_id=slot,
            )
            for slot in ("on", "off")
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ours = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    own = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if source_device_missing:
        assert own is not None and {e.device_id for e in ours} == {own.id}
    else:
        assert own is None and {e.device_id for e in ours} == {pico.id}
