"""Button Actions sidebar dashboard tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.button_actions import async_setup
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
from custom_components.button_actions.panel import (
    _panel_config,
    async_register_panel,
    websocket_get_panel_config,
)


def _remote(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office Remote",
        data={"source": "event_entity", "layout": "numbered"},
        options={CONF_DOUBLE_MS: 280, CONF_HOLD_MS: 650, CONF_REPEAT_MS: 350},
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_SLOT: "button_1",
                    CONF_ENTITIES: ["event.office_remote_button"],
                    CONF_ACTIONS: {
                        "short_press": [
                            {"action": "light.turn_on", "data": {"token": "private"}}
                        ],
                        "long_press": [{"action": "light.turn_off"}],
                    },
                    CONF_REPEAT: True,
                },
                subentry_type=SUBENTRY_BUTTON,
                title="Button 1",
                unique_id="button_1",
            )
        ],
    )
    entry.add_to_hass(hass)
    hass.states.async_set("event.office_remote_button", "unknown")
    return entry


async def test_panel_config_summarizes_remote_without_action_payloads(
    hass: HomeAssistant,
) -> None:
    """The panel lists useful configuration while keeping action bodies private."""
    entry = _remote(hass)

    result = _panel_config(hass)

    assert len(result["remotes"]) == 1
    remote = result["remotes"][0]
    assert remote["title"] == "Office Remote"
    assert remote["state"] == "not_loaded"
    assert remote["timing"] == {
        "double_ms": 280,
        "hold_ms": 650,
        "repeat_ms": 350,
    }
    assert remote["buttons"] == [
        {
            "slot": "button_1",
            "subentry_id": next(iter(entry.subentries)),
            "title": "Button 1",
            "entities": ["event.office_remote_button"],
            "gestures": ["short_press", "long_press"],
            "repeat": True,
            "detect_all": False,
            "available": True,
        }
    ]
    assert "private" not in repr(result)
    assert "actions" not in repr(result)


async def test_panel_config_websocket(hass: HomeAssistant) -> None:
    """The registered dashboard command returns the remote summary to an admin."""
    await async_setup(hass, {})
    entry = _remote(hass)
    handler, _schema = hass.data[websocket_api.DOMAIN]["button_actions/panel/config"]
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True), send_result=Mock()
    )
    handler(hass, connection, {"id": 1, "type": "button_actions/panel/config"})
    await hass.async_block_till_done()

    response = connection.send_result.call_args.args[1]
    remote = response["remotes"][0]
    assert remote["entry_id"] == entry.entry_id
    assert remote["title"] == "Office Remote"
    assert remote["buttons"][0]["gestures"] == ["short_press", "long_press"]


def test_panel_config_websocket_rejects_non_admin(hass: HomeAssistant) -> None:
    """The dashboard command enforces Home Assistant's administrator policy."""
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=False))

    with pytest.raises(Unauthorized):
        websocket_get_panel_config(hass, connection, {"id": 1})


async def test_panel_registration_is_admin_only_and_idempotent() -> None:
    """Register assets once and expose the panel only to administrators."""
    hass = SimpleNamespace(
        data={},
        config=SimpleNamespace(components={"frontend"}),
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        async_add_executor_job=AsyncMock(return_value="1.7.4"),
    )
    with patch(
        "homeassistant.components.panel_custom.async_register_panel",
        new_callable=AsyncMock,
    ) as register:
        await async_register_panel(hass)
        await async_register_panel(hass)

    assert register.await_count == 1
    assert register.await_args.kwargs["require_admin"] is True
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_reloading_a_remote_keeps_the_panel(hass: HomeAssistant) -> None:
    """Editing a remote reloads it; the page the user is on must stay."""
    entry = _remote(hass)
    with patch("homeassistant.components.frontend.async_remove_panel") as remove:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    remove.assert_not_called()


async def test_panel_subscription_reports_changes(
    hass: HomeAssistant, hass_ws_client
) -> None:
    """The dashboard hears about remote edits and sources going unavailable."""
    entry = _remote(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "button_actions/panel/subscribe"})
    assert (await client.receive_json())["success"]

    async def drain() -> int:
        count = 0
        while True:
            try:
                async with asyncio.timeout(0.1):
                    await client.receive_json()
            except TimeoutError:
                return count
            count += 1

    # Renaming reloads the remote; the dashboard hears about it.
    hass.config_entries.async_update_entry(entry, title="Study Remote")
    await hass.async_block_till_done()
    assert await drain() >= 1

    # A press changes the state but not availability: nothing to report.
    hass.states.async_set("event.office_remote_button", "2026-10-16T12:00:00")
    await hass.async_block_till_done()
    assert await drain() == 0

    hass.states.async_set("event.office_remote_button", "unavailable")
    await hass.async_block_till_done()
    assert await drain() == 1


@pytest.mark.parametrize("lutron_state", ["loaded", "not_loaded", "no_pico"])
async def test_pico_remote_availability(hass: HomeAssistant, lutron_state) -> None:
    """A Pico remote is unavailable when its Pico or Lutron Caséta isn't."""
    lutron = MockConfigEntry(
        domain="lutron_caseta",
        state=(
            ConfigEntryState.LOADED
            if lutron_state != "not_loaded"
            else ConfigEntryState.SETUP_RETRY
        ),
    )
    lutron.add_to_hass(hass)
    pico = dr.async_get(hass).async_get_or_create(
        config_entry_id=lutron.entry_id,
        identifiers={("lutron_caseta", "123")},
        name="Kitchen Pico",
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen Pico",
        minor_version=3,
        data={
            "source": "lutron_caseta",
            "device_id": "gone" if lutron_state == "no_pico" else pico.id,
            "pico_buttons": ["on"],
        },
        subentries_data=[
            ConfigSubentryData(
                data={"slot": "on", "entities": [], "actions": {}},
                subentry_type="button",
                title="On button",
                unique_id="on",
            )
        ],
    )
    entry.add_to_hass(hass)
    (remote,) = _panel_config(hass)["remotes"]
    assert remote["buttons"][0]["available"] is (lutron_state == "loaded")
    # Don't let teardown try to unload the real Lutron Caséta integration.
    lutron.mock_state(hass, ConfigEntryState.NOT_LOADED)
