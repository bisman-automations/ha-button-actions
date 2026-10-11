"""Button Actions sidebar dashboard tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
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
    async_unregister_panel,
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
    _remote(hass)

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


async def test_panel_unregistration() -> None:
    """Remove the sidebar item when the last remote unloads."""
    hass = SimpleNamespace(
        data={"button_actions_panel_registered": True},
        config=SimpleNamespace(components={"frontend"}),
    )
    with patch("homeassistant.components.frontend.async_remove_panel") as remove:
        await async_unregister_panel(hass)

    remove.assert_called_once_with(hass, "button-actions", warn_if_unknown=False)
    assert hass.data["button_actions_panel_registered"] is False
