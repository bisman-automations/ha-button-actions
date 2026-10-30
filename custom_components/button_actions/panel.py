"""Admin-only sidebar dashboard for Button Actions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import CONF_DEVICE_ID, STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)

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
    LUTRON_DOMAIN,
    SOURCE_EVENT_ENTITY,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
)
from .controller import buttons_from_entry

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "button-actions"
STATIC_URL = "/button_actions_static"
PANEL_COMPONENT = "button-actions-panel"
FRONTEND_DIR = Path(__file__).parent / "frontend"
_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"
_API_REGISTERED = f"{DOMAIN}_panel_api_registered"


def _version() -> str:
    """Read the integration version used to bust the browser cache."""
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    return manifest["version"]


def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Register the read-only dashboard command once per Home Assistant run."""
    if hass.data.get(_API_REGISTERED):
        return
    websocket_api.async_register_command(hass, websocket_get_panel_config)
    websocket_api.async_register_command(hass, websocket_subscribe_panel)
    hass.data[_API_REGISTERED] = True


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panel/config"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_get_panel_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return a safe summary of configured remotes for administrators."""
    connection.send_result(msg["id"], _panel_config(hass))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panel/subscribe"})
@websocket_api.require_admin
@callback
def websocket_subscribe_panel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tell the dashboard when what it shows may have changed.

    That's a remote being added, edited, reloaded or removed, or a button's
    source entity becoming available or unavailable. The message carries no
    data; the dashboard fetches the summary again.
    """
    unsub_states: CALLBACK_TYPE | None = None

    @callback
    def notify() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {}))

    @callback
    def source_changed(event: Event[EventStateChangedData]) -> None:
        if _unavailable(event.data["old_state"]) != _unavailable(
            event.data["new_state"]
        ):
            notify()

    @callback
    def track_sources() -> None:
        nonlocal unsub_states
        if unsub_states is not None:
            unsub_states()
            unsub_states = None
        entity_ids = {
            entity_id
            for entry in hass.config_entries.async_entries(DOMAIN)
            for button in buttons_from_entry(entry)
            for entity_id in button.entities
        }
        if entity_ids:
            unsub_states = async_track_state_change_event(
                hass, entity_ids, source_changed
            )

    @callback
    def entry_changed(change: ConfigEntryChange, entry: ConfigEntry) -> None:
        # Lutron Caséta loading or failing changes whether Pico remotes work.
        if entry.domain in (DOMAIN, LUTRON_DOMAIN):
            track_sources()
            notify()

    unsub_entries = async_dispatcher_connect(
        hass, SIGNAL_CONFIG_ENTRY_CHANGED, entry_changed
    )
    track_sources()

    @callback
    def unsubscribe() -> None:
        unsub_entries()
        if unsub_states is not None:
            unsub_states()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])


def _unavailable(state: State | None) -> bool:
    return state is None or state.state == STATE_UNAVAILABLE


def _lutron_source_available(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether a Pico remote's Pico exists and Lutron Caséta is running."""
    device = dr.async_get(hass).async_get(entry.data.get(CONF_DEVICE_ID) or "")
    if device is None:
        return False
    entry_ids = {device.config_entry_id}
    return any(
        (lutron := hass.config_entries.async_get_entry(entry_id)) is not None
        and lutron.domain == LUTRON_DOMAIN
        and lutron.state is ConfigEntryState.LOADED
        for entry_id in entry_ids
        if entry_id
    )


def _panel_config(hass: HomeAssistant) -> dict[str, list[dict[str, Any]]]:
    """Build the dashboard model without exposing configured action payloads."""
    remotes = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        subentries = {
            sub.data.get(CONF_SLOT): sub
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_BUTTON
        }
        # Pico remotes have no event entities; their source is the Pico.
        source_available = (
            _lutron_source_available(hass, entry)
            if entry.data.get(CONF_SOURCE) == SOURCE_LUTRON
            else True
        )
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
                    "subentry_id": subentry.subentry_id,
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
                    else source_available,
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
    """Register the admin-only sidebar panel and its static frontend asset.

    Called once from async_setup; the panel stays for the whole run, and shows
    an empty state when no remotes are left.
    """
    if hass.data.get(_PANEL_REGISTERED):
        return
    if "frontend" not in hass.config.components or hass.http is None:
        _LOGGER.debug("Frontend not loaded; skipping the Button Actions panel")
        return

    from homeassistant.components import panel_custom

    version = await hass.async_add_executor_job(_version)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    # Mark it registered before awaiting the panel, so a second call can't
    # register the static path twice.
    hass.data[_PANEL_REGISTERED] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="Button Actions",
        sidebar_icon="mdi:gesture-tap-button",
        # The version busts the browser cache after an update.
        module_url=f"{STATIC_URL}/button-actions-panel.js?v={version}",
        require_admin=True,
        config={},
    )
