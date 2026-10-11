"""Admin-only sidebar dashboard for Button Actions."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DETECT_ALL,
    CONF_DOUBLE_MS,
    CONF_HOLD_MS,
    CONF_LAYOUT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    CONF_SOURCE,
    CONF_SUPPORTS_DOUBLE,
    CONF_SUPPORTS_LONG,
    DEFAULT_DOUBLE_MS,
    DEFAULT_HOLD_MS,
    DEFAULT_REPEAT_MS,
    DISPLAY_ORDER,
    DOMAIN,
    GESTURES,
    LAYOUT_PICO,
    SOURCE_EVENT_ENTITY,
    SUBENTRY_BUTTON,
)
from .controller import buttons_from_entry

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "button-actions"
STATIC_URL = "/button_actions_static"
PANEL_COMPONENT = "button-actions-panel"
FRONTEND_DIR = Path(__file__).parent / "frontend"
_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"
_STATIC_REGISTERED = f"{DOMAIN}_panel_static_registered"
_PANEL_VERSION = f"{DOMAIN}_panel_version"
_API_REGISTERED = f"{DOMAIN}_panel_api_registered"
_PANEL_LOCK = f"{DOMAIN}_panel_lock"


def _version() -> str:
    """Read the integration version used to bust the browser cache."""
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    return manifest["version"]


def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Register the read-only dashboard command once per Home Assistant run."""
    if hass.data.get(_API_REGISTERED):
        return
    websocket_api.async_register_command(hass, websocket_get_panel_config)
    hass.data[_API_REGISTERED] = True


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panel/config"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_get_panel_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return a safe summary of configured remotes for administrators."""
    connection.send_result(msg["id"], _panel_config(hass))


def _panel_config(hass: HomeAssistant) -> dict[str, list[dict[str, Any]]]:
    """Build the dashboard model without exposing configured action payloads."""
    remotes = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        subentries = {
            sub.data.get(CONF_SLOT): sub
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_BUTTON
        }
        buttons = []
        ordered_buttons = sorted(
            buttons_from_entry(entry),
            key=lambda button: DISPLAY_ORDER.index(button.slot),
        )
        for button in ordered_buttons:
            subentry = subentries.get(button.slot)
            if subentry is None:
                continue
            buttons.append(
                {
                    "slot": button.slot,
                    "title": subentry.title,
                    "entities": button.entities,
                    "gestures": [
                        gesture for gesture in GESTURES if button.actions.get(gesture)
                    ],
                    "repeat": button.repeat,
                    "detect_all": bool(subentry.data.get(CONF_DETECT_ALL, False)),
                    "available": all(
                        (state := hass.states.get(entity_id)) is not None
                        and state.state != "unavailable"
                        for entity_id in button.entities
                    )
                    if button.entities
                    else True,
                }
            )
        remotes.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "state": entry.state.value,
                "source": entry.data.get(CONF_SOURCE, SOURCE_EVENT_ENTITY),
                "layout": entry.data.get(CONF_LAYOUT, LAYOUT_PICO),
                "supports_double": bool(entry.data.get(CONF_SUPPORTS_DOUBLE, True)),
                "supports_long": bool(entry.data.get(CONF_SUPPORTS_LONG, True)),
                "timing": {
                    CONF_DOUBLE_MS: entry.options.get(
                        CONF_DOUBLE_MS, DEFAULT_DOUBLE_MS
                    ),
                    CONF_HOLD_MS: entry.options.get(CONF_HOLD_MS, DEFAULT_HOLD_MS),
                    CONF_REPEAT_MS: entry.options.get(
                        CONF_REPEAT_MS, DEFAULT_REPEAT_MS
                    ),
                },
                "buttons": buttons,
            }
        )
    return {"remotes": remotes}


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the admin-only sidebar panel and its static frontend asset."""
    async with hass.data.setdefault(_PANEL_LOCK, asyncio.Lock()):
        if hass.data.get(_PANEL_REGISTERED):
            return
        if "frontend" not in hass.config.components or hass.http is None:
            _LOGGER.debug("Frontend not loaded; skipping the Button Actions panel")
            return

        from homeassistant.components import panel_custom

        if not hass.data.get(_STATIC_REGISTERED):
            version = await hass.async_add_executor_job(_version)
            await hass.http.async_register_static_paths(
                [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
            )
            hass.data[_PANEL_VERSION] = version
            hass.data[_STATIC_REGISTERED] = True

        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_COMPONENT,
            sidebar_title="Button Actions",
            sidebar_icon="mdi:gesture-tap-button",
            module_url=(
                f"{STATIC_URL}/button-actions-panel.js?v={hass.data[_PANEL_VERSION]}"
            ),
            require_admin=True,
            config={},
        )
        hass.data[_PANEL_REGISTERED] = True


async def async_unregister_panel(
    hass: HomeAssistant, *, excluding_entry_id: str | None = None
) -> None:
    """Remove the panel when the last Button Actions remote is unloaded."""
    async with hass.data.setdefault(_PANEL_LOCK, asyncio.Lock()):
        if not hass.data.get(_PANEL_REGISTERED):
            return
        if excluding_entry_id is not None and any(
            entry.entry_id != excluding_entry_id
            and entry.state
            in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
            for entry in hass.config_entries.async_entries(DOMAIN)
        ):
            return
        if "frontend" in hass.config.components:
            from homeassistant.components import frontend

            frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        hass.data[_PANEL_REGISTERED] = False
