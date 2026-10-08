"""Event entities that report the gestures detected on each button."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, GESTURES, SLOT_ICONS, button_positions

if TYPE_CHECKING:
    from . import ButtonActionsConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ButtonActionsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one gesture entity per configured button."""
    controller = entry.runtime_data
    positions = button_positions(controller.slots)
    async_add_entities(
        ButtonGestureEvent(entry, slot, positions[slot]) for slot in controller.slots
    )


class ButtonGestureEvent(EventEntity):
    """Fires short_press, double_press, long_press and long_release."""

    _attr_has_entity_name = True
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(
        self, entry: ButtonActionsConfigEntry, slot: str, position: int
    ) -> None:
        self._attr_event_types = list(GESTURES)
        self._entry = entry
        self._slot = slot
        self._attr_unique_id = f"{entry.entry_id}_{slot}"
        self._attr_translation_key = slot
        # Numbered so Home Assistant's alphabetical list matches the remote.
        self._attr_translation_placeholders = {"position": str(position)}
        self._attr_icon = SLOT_ICONS.get(slot)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Button Actions",
            model="Button remote",
        )

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
