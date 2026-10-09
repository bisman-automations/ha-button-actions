"""Device triggers: "<remote>: <button> double pressed" in the automation editor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, GESTURE_EVENT, GESTURES, SLOTS
from .controller import buttons_from_entry, supported_gestures

CONF_SUBTYPE = "subtype"
CONF_ENTRY_ID = "entry_id"

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(GESTURES),
        vol.Required(CONF_SUBTYPE): vol.In(SLOTS),
        # Which remote, when several share one device.
        vol.Optional(CONF_ENTRY_ID): str,
    }
)


def _entries_for_device(hass: HomeAssistant, device_id: str) -> list[ConfigEntry]:
    """Remotes with triggers on this device: the remote's own device.

    Home Assistant 2026.7 and older also ask about the Pico or button device a
    1.7.0 remote joined; more than one remote can share that device.
    """
    return [
        entry
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if device_id
        in (entry.runtime_data.device_id(), entry.runtime_data.linked_device_id)
    ]


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Every supported gesture on every button of the remotes on this device."""
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: gesture,
            CONF_SUBTYPE: button.slot,
            CONF_ENTRY_ID: entry.entry_id,
        }
        for entry in _entries_for_device(hass, device_id)
        for button in buttons_from_entry(entry)
        for gesture in supported_gestures(entry.data)
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the gesture event the controller fires."""
    return await event_trigger.async_attach_trigger(
        hass,
        event_trigger.TRIGGER_SCHEMA(
            {
                event_trigger.CONF_PLATFORM: "event",
                event_trigger.CONF_EVENT_TYPE: GESTURE_EVENT,
                event_trigger.CONF_EVENT_DATA: {
                    # A trigger naming its remote matches that remote whichever
                    # device it was picked on (1.7.0 used the linked device).
                    **(
                        {CONF_ENTRY_ID: config[CONF_ENTRY_ID]}
                        if CONF_ENTRY_ID in config
                        else {CONF_DEVICE_ID: config[CONF_DEVICE_ID]}
                    ),
                    "button": config[CONF_SUBTYPE],
                    "gesture": config[CONF_TYPE],
                },
            }
        ),
        action,
        trigger_info,
        platform_type="device",
    )
