"""Read Pico remotes straight from the core Lutron Caséta integration."""

from __future__ import annotations

from homeassistant.components.device_automation import (
    DeviceAutomationType,
    async_get_device_automations,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import LUTRON_DOMAIN, SLOTS


async def async_pico_buttons(hass: HomeAssistant, device_id: str) -> list[str]:
    """Return the buttons a core Lutron Caséta Pico has, in Pico order.

    Core Lutron already lists each Pico's buttons as device triggers, using
    the same names as our slots (on, raise, stop, lower, off, button_1..4).
    Buttons with other names (group keypads) aren't supported yet.
    """
    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, [device_id]
    )
    names = {
        trigger.get("subtype")
        for trigger in triggers.get(device_id, [])
        if trigger.get("domain") == LUTRON_DOMAIN
    }
    return [slot for slot in SLOTS if slot in names]


def is_lutron_device(hass: HomeAssistant, device_id: str | None) -> bool:
    """Whether a device registry entry belongs to core Lutron Caséta."""
    if device_id is None or (device := dr.async_get(hass).async_get(device_id)) is None:
        return False
    return any(domain == LUTRON_DOMAIN for domain, _ in device.identifiers)


def lutron_device_for_entities(
    hass: HomeAssistant, entity_ids: list[str]
) -> str | None:
    """Return the core Lutron device these event entities belong to, if any.

    Used to suggest the right Pico when switching a remote over to core
    Lutron, if the event entities were attached to the Pico's device.
    """
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if entry is not None and is_lutron_device(hass, entry.device_id):
            return entry.device_id
    return None
