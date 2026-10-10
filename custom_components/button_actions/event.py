"""Event entities that report the gestures detected on each button."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_LAYOUT,
    LAYOUT_NUMBERED,
    NUMBERED_ICON,
    SLOT_ICONS,
    button_positions,
    numbered_label,
)
from .controller import supported_gestures

if TYPE_CHECKING:
    from . import ButtonActionsConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ButtonActionsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one gesture entity per configured button."""
    controller = entry.runtime_data
    if controller.linked_device_id:
        # The linked device already shows its own button events.
        return
    slots = controller.slots
    if entry.data.get(CONF_LAYOUT) == LAYOUT_NUMBERED:
        # "Button 1", "Button 2"...
        names = {
            slot: ("numbered", {"number": numbered_label(slot, slots)}, NUMBERED_ICON)
            for slot in slots
        }
    else:
        # "1 · On", "2 · Raise"... in the order they sit on a Pico.
        positions = button_positions(slots)
        names = {
            slot: (slot, {"position": str(positions[slot])}, SLOT_ICONS.get(slot))
            for slot in slots
        }
    async_add_entities(ButtonGestureEvent(entry, slot, *names[slot]) for slot in slots)


class ButtonGestureEvent(EventEntity):
    """Fires short_press, double_press, long_press and long_release."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(
        self,
        entry: ButtonActionsConfigEntry,
        slot: str,
        translation_key: str,
        placeholders: dict[str, str],
        icon: str | None,
    ) -> None:
        self._attr_event_types = supported_gestures(entry.data)
        self._entry = entry
        self._slot = slot
        self._attr_unique_id = f"{entry.entry_id}_{slot}"
        self._attr_translation_key = translation_key
        # Numbered so Home Assistant's alphabetical list matches the remote.
        self._attr_translation_placeholders = placeholders
        self._attr_icon = icon
        # On the remote's own device. Attached by device_entry rather than
        # device_info, so entities from several button subentries don't each
        # claim the device (Home Assistant 2026.8+ gives a device one subentry).
        controller = entry.runtime_data
        if device_id := controller.device_id():
            self.device_entry = dr.async_get(controller.hass).async_get(device_id)

    async def async_added_to_hass(self) -> None:
        """Start receiving gestures from the controller."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._entry.runtime_data.register_gesture_listener(
                self._slot, self._handle_gesture
            )
        )

    @callback
    def _handle_gesture(self, gesture: str) -> None:
        self._trigger_event(gesture)
        self.async_write_ha_state()
