"""Button Actions: click, double-click and hold actions for button remotes."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import ButtonActionsController

PLATFORMS: list[Platform] = [Platform.EVENT]

type ButtonActionsConfigEntry = ConfigEntry[ButtonActionsController]


async def async_setup_entry(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> bool:
    """Set up one remote."""
    controller = ButtonActionsController(hass, entry)
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> bool:
    """Unload one remote."""
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> None:
    """Reload so new actions and timing take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
