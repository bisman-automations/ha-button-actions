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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, GESTURE_EVENT, GESTURES, SLOTS
from .controller import buttons_from_entry

CONF_SUBTYPE = "subtype"

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(GESTURES),
        vol.Required(CONF_SUBTYPE): vol.In(SLOTS),
    }
)


def _entry_for_device(hass: HomeAssistant, device_id: str) -> ConfigEntry | None:
    if (device := dr.async_get(hass).async_get(device_id)) is None:
        return None
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            return hass.config_entries.async_get_entry(identifier)
    return None


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Every gesture on every button the remote has."""
    if (entry := _entry_for_device(hass, device_id)) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: gesture,
            CONF_SUBTYPE: button.slot,
        }
        for button in buttons_from_entry(entry)
        for gesture in GESTURES
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
                    CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                    "button": config[CONF_SUBTYPE],
                    "gesture": config[CONF_TYPE],
                },
            }
        ),
        action,
        trigger_info,
        platform_type="device",
    )
