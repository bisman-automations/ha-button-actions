"""Read keypads, Picos and shade remotes from the core Lutron Caséta integration.

Home Assistant 2026.11 (core PR 184266) creates an event entity for every
keypad button and Pico button. A Pico or shade remote reports ``press_start``
when the button goes down and ``press_end`` when it is released. A keypad
(Palladiom, seeTouch, Sunnata, Homeowner, and the keypads on RA2 Select,
RadioRA 3, HomeWorks QSX and Athena) reports ``press_start`` only: Lutron
does not reliably say when a keypad button comes up, so core ignores the
release. Athena processors themselves were added in core PR 182609 and use
this same integration, so their buttons show up here too.

The bus event ``lutron_caseta_button_event`` still fires, with ``press`` and
``release``, on every Home Assistant this integration supports. Button Actions
uses the event entities when they carry both edges, because that is the same
press and release the gesture timing needs. It keeps the bus event when they
don't, when a button has no entity, and on Home Assistant older than 2026.11
(the minimum in hacs.json is 2026.8, which has no such entities).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.device_automation import (
    DeviceAutomationType,
    async_get_device_automations,
)
from homeassistant.components.device_automation.exceptions import DeviceNotFound
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_ENTITIES,
    CONF_LUTRON_INPUT,
    CONF_SLOT,
    CONF_SOURCE,
    LUTRON_DOMAIN,
    LUTRON_INPUT_BUS,
    SLOTS,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
    slot_label,
    slot_sort_key,
)
from .events import ROLE_PRESS, ROLE_RELEASE, suggest_roles

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LutronButton:
    """One physical button on a Lutron keypad, Pico or shade remote."""

    slot: str
    name: str
    entity_id: str | None = None
    event_types: tuple[str, ...] = ()

    @property
    def reports_release(self) -> bool:
        """Whether this button's event entity has a press and a release.

        A press on its own is collapsed to a click, which cannot time a hold
        or a double press. Those buttons stay on the bus event.
        """
        if self.entity_id is None:
            return False
        roles = set(suggest_roles(self.event_types).values())
        return ROLE_PRESS in roles and ROLE_RELEASE in roles


def _names_match(slot: str, entity_name: str) -> bool:
    """Whether a core event entity is this button.

    Pico entities are the trigger subtype with underscores turned into spaces
    and title case ("button_1" is "Button 1", "on" is "On"). Keypad entities
    use the Lutron button name, which is also the trigger subtype.
    """
    if entity_name == slot or entity_name.casefold() == slot.casefold():
        return True
    return entity_name.casefold() == slot.replace("_", " ").casefold()


def _event_types(hass: HomeAssistant, reg: er.RegistryEntry) -> tuple[str, ...]:
    """Event types from the registry, or from the state if it has them."""
    types = list((reg.capabilities or {}).get("event_types") or [])
    if not types and (state := hass.states.get(reg.entity_id)) is not None:
        types = list(state.attributes.get("event_types") or [])
    return tuple(dict.fromkeys(str(item) for item in types))


def entity_reports_press_and_release(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether this event entity can time a hold: it reports press and release."""
    reg = er.async_get(hass).async_get(entity_id)
    if reg is None or reg.disabled_by is not None or reg.domain != "event":
        return False
    roles = set(suggest_roles(_event_types(hass, reg)).values())
    return ROLE_PRESS in roles and ROLE_RELEASE in roles


async def async_lutron_buttons(
    hass: HomeAssistant, device_id: str
) -> list[LutronButton]:
    """Every button core Lutron Caséta exposes on this device, in remote order.

    Device triggers supply the button names, which is what the bus event puts
    in ``button_type``. On Home Assistant 2026.11 and newer, each button may
    also have an event entity from the ``lutron_caseta`` platform. Disabled
    entities and entities whose name matches more than one button are left
    unmatched, so the bus event stays the source for those buttons.
    """
    try:
        triggers = await async_get_device_automations(
            hass, DeviceAutomationType.TRIGGER, [device_id]
        )
    except DeviceNotFound:
        # The Pico was removed, or it never had a device registry entry.
        # The repair for a missing device handles that; discovery just has
        # nothing to match.
        return []
    slots: list[str] = []
    for trigger in triggers.get(device_id, []):
        subtype = trigger.get("subtype")
        if (
            trigger.get("domain") == LUTRON_DOMAIN
            and isinstance(subtype, str)
            and subtype
            and subtype not in slots
        ):
            slots.append(subtype)
    slots.sort(key=slot_sort_key)

    registry = er.async_get(hass)
    candidates: list[tuple[er.RegistryEntry, str, tuple[str, ...]]] = []
    for reg in er.async_entries_for_device(registry, device_id):
        if (
            reg.domain != "event"
            or reg.platform != LUTRON_DOMAIN
            or reg.disabled_by is not None
        ):
            continue
        name = reg.original_name or ""
        if name:
            candidates.append((reg, name, _event_types(hass, reg)))

    buttons: list[LutronButton] = []
    for slot in slots:
        matches = [
            (reg, types) for reg, name, types in candidates if _names_match(slot, name)
        ]
        entity_id = None
        event_types: tuple[str, ...] = ()
        # One entity per button. Two matches would be a guess, so neither is used.
        if len(matches) == 1:
            entity_id = matches[0][0].entity_id
            event_types = matches[0][1]
        buttons.append(
            LutronButton(
                slot=slot,
                name=slot_label(slot),
                entity_id=entity_id,
                event_types=event_types,
            )
        )
    return buttons


async def async_pico_buttons(hass: HomeAssistant, device_id: str) -> list[str]:
    """Return the Pico-shaped buttons on a device, in Pico order.

    Blueprint import only knows On, Raise, Middle, Lower, Off and the scene
    buttons. Keypad names and shade-remote groups are not those slots; use
    ``async_lutron_buttons`` for the full set.
    """
    buttons = await async_lutron_buttons(hass, device_id)
    return [button.slot for button in buttons if button.slot in SLOTS]


def lutron_source_note(buttons: list[LutronButton]) -> str:
    """Why presses will be read from event entities or from the bus event."""
    if not buttons:
        return ""
    reporting = [button for button in buttons if button.reports_release]
    if len(reporting) == len(buttons):
        return (
            "These buttons report a press and a release through Lutron's event "
            "entities (Home Assistant 2026.11 and newer). Button Actions uses "
            "those, so a short press, a double press and a hold are timed from "
            "the same press and release."
        )
    if reporting:
        return (
            "Buttons that report a press and a release through an event entity "
            "use that entity. Any button with no entity, or no release, is read "
            "from Lutron's button event, so holds and double presses can still "
            "be timed."
        )
    if any(button.entity_id for button in buttons):
        return (
            "These buttons' event entities only report a press, not a release. "
            "Keypads work this way, including on Athena, RadioRA 3 and "
            "HomeWorks: Lutron does not reliably say when the button comes up. "
            "Long press, double press and hold-to-repeat need that release, so "
            "presses are read from Lutron's button event instead, which still "
            "includes it."
        )
    return (
        "Presses are read from Lutron's button event. Home Assistant older "
        "than 2026.11 does not create an event entity for each button, and "
        "this still works."
    )


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
    Lutron, and to refuse a second remote on a keypad or Pico that already
    has one.
    """
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if entry is not None and is_lutron_device(hass, entry.device_id):
            return entry.device_id
    return None


async def async_sync_lutron_event_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Attach core event entities when that changes nothing the user configured.

    The config entry, its buttons, slot keys, actions and unique ids stay.
    Only the entity id stored on a button is filled in, and only when that
    button's core event entity reports both a press and a release. A keypad
    button has no release, so it stays on the bus event. ``lutron_input`` set
    to ``bus`` keeps the bus event even when event entities exist (the
    Reconfigure choice).
    """
    if entry.data.get(CONF_SOURCE) != SOURCE_LUTRON:
        return
    if entry.data.get(CONF_LUTRON_INPUT) == LUTRON_INPUT_BUS:
        # Reconfigure asked to keep the bus event. Drop stored entity ids so
        # the controller does not listen to them as well.
        for sub in list(entry.subentries.values()):
            if sub.subentry_type == SUBENTRY_BUTTON and sub.data.get(CONF_ENTITIES):
                hass.config_entries.async_update_subentry(
                    entry, sub, data={**sub.data, CONF_ENTITIES: []}
                )
        return
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return
    discovered = {
        button.slot: button for button in await async_lutron_buttons(hass, device_id)
    }
    if not discovered:
        return
    for sub in list(entry.subentries.values()):
        if sub.subentry_type != SUBENTRY_BUTTON:
            continue
        slot = sub.data.get(CONF_SLOT)
        button = discovered.get(slot)
        if button is None:
            continue
        wanted = (
            [button.entity_id] if button.reports_release and button.entity_id else []
        )
        current = list(sub.data.get(CONF_ENTITIES) or [])
        if current == wanted:
            continue
        _LOGGER.debug(
            "%s: %s reads presses from %s",
            entry.title,
            slot,
            wanted[0] if wanted else "Lutron's button event",
        )
        hass.config_entries.async_update_subentry(
            entry, sub, data={**sub.data, CONF_ENTITIES: wanted}
        )
