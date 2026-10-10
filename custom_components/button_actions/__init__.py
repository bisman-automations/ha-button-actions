"""Button Actions: click, double-click and hold actions for button remotes."""

from __future__ import annotations

import logging
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ACTIONS,
    CONF_ENTITIES,
    CONF_LAYOUT,
    CONF_REPEAT,
    CONF_SLOT,
    DOMAIN,
    LAYOUT_PICO,
    NUMBERED_SLOTS,
    SLOT_TITLES,
    SLOTS,
    SUBENTRY_BUTTON,
    button_title,
    numbered_title,
    slot_number,
)
from .controller import (
    ButtonActionsController,
    async_set_gesture_entities_enabled,
    buttons_from_entry,
    linked_device_id,
)
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
    # Before the update listener is added, so retitling doesn't trigger a reload.
    _async_number_button_titles(hass, entry)
    controller.own_device_id = _async_own_device(hass, entry, controller)
    if controller.linked_device_id is None:
        # No longer linked: bring back gesture entities hidden while it was.
        async_set_gesture_entities_enabled(hass, entry, enabled=True)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_tidy_devices(hass, entry, controller.own_device_id)
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
def _async_number_button_titles(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Title buttons "1 · On button", "2 · Raise button"... in remote order.

    Only titles we set ourselves are changed, so a renamed button keeps its name.
    """
    buttons = {
        sub.data.get(CONF_SLOT): sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_BUTTON and sub.data.get(CONF_SLOT) in SLOTS
    }
    layout = entry.data.get(CONF_LAYOUT, LAYOUT_PICO)
    slots = list(buttons)
    for slot, sub in buttons.items():
        ours = {SLOT_TITLES[slot]} | {
            numbered_title(n, slot) for n in range(1, len(SLOTS) + 1)
        }
        if slot in NUMBERED_SLOTS:
            n = slot_number(slot)
            ours |= {f"Button {n}", f"Button {n:02d}"}
        wanted = button_title(layout, slot, slots)
        if sub.title in ours and sub.title != wanted:
            hass.config_entries.async_update_subentry(entry, sub, title=wanted)


@callback
def _async_own_device(
    hass: HomeAssistant, entry: ConfigEntry, controller: ButtonActionsController
) -> str:
    """Create or update the remote's own device.

    It holds the remote's device triggers. When the remote is linked to a
    Pico or button device, it shows as connected via that device, and the
    gesture entities show on that device instead.
    """
    registry = dr.async_get(hass)
    # No subentry: the device is the whole remote, not one button.
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Button Actions",
        model="Button remote",
    )
    if device.via_device_id != controller.linked_device_id:
        registry.async_update_device(
            device.id, via_device_id=controller.linked_device_id
        )
    return device.id


@callback
def _async_tidy_devices(
    hass: HomeAssistant, entry: ConfigEntry, current_device_id: str | None
) -> None:
    """Detach the remote from every device except its own.

    1.7.0 added remotes to their Pico or button device on Home Assistant
    versions that allowed it; that's undone here.
    """
    if current_device_id is None:
        return
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if device.id == current_device_id:
            continue
        if hasattr(device, "config_entry_id"):
            # Home Assistant 2026.8+: the device is wholly ours.
            registry.async_remove_device(device.id)
        else:
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


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

    if entry.minor_version < 3:
        # 1.7.2: gesture entities of a remote linked to a device are disabled,
        # since the device already shows its own button events.
        if linked_device_id(hass, entry, buttons_from_entry(entry)):
            async_set_gesture_entities_enabled(hass, entry, enabled=False)
        hass.config_entries.async_update_entry(entry, minor_version=3)

    return True
