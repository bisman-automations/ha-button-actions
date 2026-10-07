"""Button Actions: click, double-click and hold actions for button remotes."""

from __future__ import annotations

import logging
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ACTIONS,
    CONF_ENTITIES,
    CONF_REPEAT,
    CONF_SLOT,
    SLOT_TITLES,
    SLOTS,
    SUBENTRY_BUTTON,
)
from .controller import ButtonActionsController
from .issues import async_delete_issues, async_track_issues

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.EVENT]

type ButtonActionsConfigEntry = ConfigEntry[ButtonActionsController]

# 1.0.0 kept buttons in entry.data and actions in entry.options.
_LEGACY_BUTTONS = "buttons"


async def async_setup_entry(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> bool:
    """Set up one remote."""
    controller = ButtonActionsController(hass, entry)
    entry.runtime_data = controller
    _async_remove_stale_entities(hass, entry, controller.slots)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()
    async_track_issues(hass, entry, controller)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> bool:
    """Unload one remote."""
    await entry.runtime_data.async_stop()
    async_delete_issues(hass, entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> None:
    """Reload when timing changes or a button is added, edited or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, slots: list[str]
) -> None:
    """Drop gesture entities for buttons that were removed."""
    registry = er.async_get(hass)
    keep = {f"{entry.entry_id}_{slot}" for slot in slots}
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id not in keep:
            registry.async_remove(reg_entry.entity_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older entries."""
    if entry.version > 1:
        # Downgraded from a future version we don't understand.
        return False

    if entry.minor_version < 2:
        # 1.0.0 -> 1.1.0: one button subentry per button.
        buttons: dict[str, list[str]] = entry.data.get(_LEGACY_BUTTONS, {})
        actions: dict[str, dict] = entry.options.get(CONF_ACTIONS, {})
        repeat_slots = set(entry.options.get(CONF_REPEAT, []))
        existing = {sub.unique_id for sub in entry.subentries.values()}

        for slot in SLOTS:
            if not buttons.get(slot) or slot in existing:
                continue
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(
                        {
                            CONF_SLOT: slot,
                            CONF_ENTITIES: list(buttons[slot]),
                            CONF_ACTIONS: dict(actions.get(slot, {})),
                            CONF_REPEAT: slot in repeat_slots,
                        }
                    ),
                    subentry_type=SUBENTRY_BUTTON,
                    title=SLOT_TITLES[slot],
                    unique_id=slot,
                ),
            )

        data = {k: v for k, v in entry.data.items() if k != _LEGACY_BUTTONS}
        options = {
            k: v
            for k, v in entry.options.items()
            if k not in (CONF_ACTIONS, CONF_REPEAT)
        }
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, minor_version=2
        )
        _LOGGER.info("Migrated %s to per-button subentries", entry.title)

    return True
