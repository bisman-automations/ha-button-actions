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
from custom_components.button_actions.controller import device_belongs_to, own_device

MOMENTARY = ["initial_press", "short_release", "long_press", "long_release"]
_ticks = itertools.count()


SHARED_IDENTIFIERS = hasattr(dr.DeviceRegistry, "async_get_device_by_identifier")


def _is_linked(hass: HomeAssistant, own: dr.DeviceEntry, device_id: str) -> bool:
    """Whether the remote's own device is linked to the device.

    Home Assistant 2026.8+ links devices that share identifiers ("Linked
    devices"); older versions show the remote as connected via it.
    """

    if not SHARED_IDENTIFIERS:
        return own.via_device_id == device_id
    device = dr.async_get(hass).async_get(device_id)
    return own.via_device_id is None and device.identifiers <= own.identifiers


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

    # No gesture entities: the hub shows its own button events. The remote's
    # own device holds its triggers and is connected via the hub.
    registry = er.async_get(hass)
    assert er.async_entries_for_config_entry(registry, entry.entry_id) == []
    own = own_device(hass, entry.entry_id)
    assert own is not None and _is_linked(hass, own, device.id)
    assert not device_belongs_to(
        dr.async_get(hass).async_get(device.id), entry.entry_id
    )


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

    # Its gesture entity is removed; the hub shows its own button events.
    assert registry.async_get(old_entity.entity_id) is None
    # The old device stays, so automations using its triggers keep working.
    kept = dr.async_get(hass).async_get(old.id)
    assert kept is not None and _is_linked(hass, kept, device.id)


@pytest.mark.skipif(
    hasattr(dr.DeviceRegistry, "async_get_device_by_identifier"),
    reason="Home Assistant 2026.8+ can't share devices between integrations",
)
async def test_undoes_170_join(hass: HomeAssistant) -> None:
    """1.7.0 added remotes to their device on older Home Assistant; undo it."""
    device, entity_ids = _hub(hass)
    entry = _remote(hass, entity_ids)
    dr.async_get(hass).async_update_device(
        device.id, add_config_entry_id=entry.entry_id
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hub = dr.async_get(hass).async_get(device.id)
    assert hub is not None and not device_belongs_to(hub, entry.entry_id)


async def test_buttons_on_different_devices_keep_own_device(
    hass: HomeAssistant,
) -> None:
    _, first = _hub(hass, count=1, name="Hub A")
    _, second = _hub(hass, count=1, name="Hub B")
    entry = _remote(hass, [first[0], second[0]])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    own = own_device(hass, entry.entry_id)
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

    # Each remote lists its triggers on its own device.
    right_device = own_device(hass, second.entry_id)
    triggers = await device_trigger.async_get_triggers(hass, right_device.id)
    assert {t["entry_id"] for t in triggers} == {second.entry_id}
    # A 1.7.0 trigger picked on the shared device still matches its remote.
    shared = await device_trigger.async_get_triggers(hass, device.id)
    assert {t["entry_id"] for t in shared} == {first.entry_id, second.entry_id}

    right_trigger = next(
        t
        for t in shared
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
    own = own_device(hass, entry.entry_id)
    assert own is not None
    if source_device_missing:
        assert {e.device_id for e in ours} == {own.id}
        assert own.via_device_id is None
    else:
        assert ours == []
        assert _is_linked(hass, own, pico.id)
        assert not device_belongs_to(
            dr.async_get(hass).async_get(pico.id), entry.entry_id
        )


async def test_reconfigure_links_any_device(hass: HomeAssistant) -> None:
    """Reconfigure can link a remote to a device that isn't a Pico."""
    device, entity_ids = _hub(hass, name="Master Bedroom Hub")
    _, other_ids = _hub(hass, name="Spare Hub")
    # Buttons from two devices, so nothing is linked automatically.
    entry = _remote(hass, [entity_ids[0], other_ids[0]])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hub Remote", "device_id": device.id}
    )
    assert result["step_id"] == "reconfigure_events"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["source"] == "event_entity"
    assert entry.data["source_device"] == device.id
    # Linked: the hub shows its own button events, so no gesture entities.
    assert er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) == []

    # Clearing the device unlinks it again.
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hub Remote"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert "source_device" not in entry.data
    # Unlinked again, so its gesture entities come back on its own device.
    ours = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    own = own_device(hass, entry.entry_id)
    assert len(ours) == 2 and {e.device_id for e in ours} == {own.id}


async def test_linked_remote_gesture_entities_removed(hass: HomeAssistant) -> None:
    """Gesture entities of a linked remote, even ones 1.7.2 disabled, are removed."""
    _, entity_ids = _hub(hass)
    entry = _remote(hass, entity_ids)
    registry = er.async_get(hass)
    existing = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry.entry_id}_button_1",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        suggested_object_id="hub_remote_button_1",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 3
    assert registry.async_get(existing.entity_id) is None


async def test_buttons_on_device_connected_via_hub(hass: HomeAssistant) -> None:
    """A Matter bridge puts its buttons on a device connected via the hub."""
    matter = MockConfigEntry(domain="matter")
    matter.add_to_hass(hass)
    devices = dr.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=matter.entry_id,
        identifiers={("matter", "bridge")},
        name="Girl's Bedroom Hub",
    )
    bulb = devices.async_get_or_create(
        config_entry_id=matter.entry_id,
        identifiers={("matter", "bulb")},
        name="Color Bulb",
    )
    buttons = devices.async_get_or_create(
        config_entry_id=matter.entry_id,
        identifiers={("matter", "buttons")},
        name="Girl's Bedroom Hub Buttons",
    )
    for device in (bulb, buttons):
        devices.async_update_device(device.id, via_device_id=hub.id)
    registry = er.async_get(hass)
    for n in (1, 2):
        reg = registry.async_get_or_create(
            "event",
            "matter",
            f"button-{n}",
            config_entry=matter,
            device_id=buttons.id,
            capabilities={"event_types": ["initial_press"]},
            original_name="Button",
        )
        hass.states.async_set(
            reg.entity_id, "unknown", {"event_types": ["initial_press"]}
        )

    result = await _device_flow(hass, hub.id)
    assert result["step_id"] == "device_confirm"
    assert result["description_placeholders"]["count"] == "2"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"supports_double": False, "supports_long": False}
    )
    entry = result["result"]
    assert entry.title == "Girl's Bedroom Hub"
    # Linked to the device the buttons are on.
    assert entry.data["source_device"] == buttons.id
    await hass.async_block_till_done()


@pytest.mark.skipif(not SHARED_IDENTIFIERS, reason="Linked devices need 2026.8+")
async def test_linked_devices_card(hass: HomeAssistant, hass_ws_client) -> None:
    """The hub's page lists the remote under "Linked devices", and back."""
    device, _ = _hub(hass)
    result = await _device_flow(hass, device.id)
    entry = (await hass.config_entries.flow.async_configure(result["flow_id"], {}))[
        "result"
    ]
    await hass.async_block_till_done()
    own = own_device(hass, entry.entry_id)
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "config/device_registry/list_linked_devices", "device_id": device.id}
    )
    response = await client.receive_json()
    assert response["success"], response
    assert response["result"]["linked_devices"] == [own.id]


@pytest.mark.skipif(not SHARED_IDENTIFIERS, reason="Linked devices need 2026.8+")
async def test_second_remote_on_same_device(hass: HomeAssistant) -> None:
    """Only one remote can share a device's identifiers; the next uses via."""
    device, entity_ids = _hub(hass)
    first = _remote(hass, [entity_ids[0]], title="Left")
    second = _remote(hass, [entity_ids[1]], title="Right")
    assert await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    assert second.state is config_entries.ConfigEntryState.LOADED
    owns = [own_device(hass, e.entry_id) for e in (first, second)]
    assert all(
        _is_linked(hass, own, device.id) or own.via_device_id == device.id
        for own in owns
    )
