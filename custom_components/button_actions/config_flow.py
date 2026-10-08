"""Config, options and button subentry flows for Button Actions."""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.util.yaml import load_yaml

from .const import (
    BLUEPRINT_DEFAULT_DOUBLE_MS,
    BLUEPRINT_DEFAULT_HOLD_MS,
    BLUEPRINT_ENTITY_INPUTS,
    BLUEPRINT_GESTURE_PREFIXES,
    CONF_ACTIONS,
    CONF_BUTTON_COUNT,
    CONF_DETECT_ALL,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_EVENT_ROLES,
    CONF_HOLD_MS,
    CONF_LAYOUT,
    CONF_PICO_BUTTONS,
    CONF_PRESS_EVENT,
    CONF_RELEASE_EVENT,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    CONF_SOURCE,
    CONF_SOURCE_AUTOMATION,
    CONF_SUPPORTS_DOUBLE,
    CONF_SUPPORTS_LONG,
    DEFAULT_DOUBLE_MS,
    DEFAULT_HOLD_MS,
    DEFAULT_PRESS_EVENT,
    DEFAULT_RELEASE_EVENT,
    DEFAULT_REPEAT_MS,
    DOMAIN,
    GESTURES,
    LAYOUT_NUMBERED,
    LAYOUT_PICO,
    LUTRON_DOMAIN,
    MAX_BUTTONS,
    NUMBERED_SLOTS,
    PICO_SLOTS,
    SLOT_TITLES,
    SLOTS,
    SOURCE_EVENT_ENTITY,
    SOURCE_LUTRON,
    SUBENTRY_BUTTON,
    button_title,
)
from .controller import (
    async_validate_sequence,
    event_role_overrides,
    remote_capabilities,
    supported_gestures,
)
from .events import ROLE_PRESS, ROLE_RELEASE, ROLES, resolve_role
from .lutron import async_pico_buttons, lutron_device_for_entities

_LOGGER = logging.getLogger(__name__)

CONF_AUTOMATION = "automation"
CONF_DISABLE_SOURCE = "disable_source"
CONF_AUTOMATIONS = "automations"
CONF_USE_PICO = "use_pico"
CONF_REMOTE = "remote"
CONF_FIND = "find"
CONF_REPLACE = "replace"

_EVENT_ENTITIES = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="event", multiple=True)
)
_PICO_DEVICE = selector.DeviceSelector(
    selector.DeviceSelectorConfig(integration=LUTRON_DOMAIN)
)


def _is_lutron(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_SOURCE, SOURCE_EVENT_ENTITY) == SOURCE_LUTRON


def _pico_conflict(
    hass: HomeAssistant,
    device_id: str | None,
    exclude_entry_id: str | None = None,
) -> str | None:
    """Return an error key if a Pico already drives another remote.

    Catches both another core-Lutron remote on the same Pico, and an
    event-entity remote whose entities belong to that Pico; either way
    every press would run twice.
    """
    if device_id is None:
        return None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        if _is_lutron(entry):
            if entry.data.get(CONF_DEVICE_ID) == device_id:
                return "pico_in_use"
            continue
        for sub in entry.subentries.values():
            entities = sub.data.get(CONF_ENTITIES, [])
            if lutron_device_for_entities(hass, entities) == device_id:
                return "pico_in_use"
    return None


def _device_name(hass: HomeAssistant, device_id: str) -> str | None:
    if (device := dr.async_get(hass).async_get(device_id)) is None:
        return None
    return device.name_by_user or device.name


def _ms_selector(minimum: int, maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=10,
            unit_of_measurement="ms",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _as_list(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _timing_schema(options: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_DOUBLE_MS,
                default=options.get(CONF_DOUBLE_MS, DEFAULT_DOUBLE_MS),
            ): _ms_selector(100, 1000),
            vol.Required(
                CONF_HOLD_MS,
                default=options.get(CONF_HOLD_MS, DEFAULT_HOLD_MS),
            ): _ms_selector(300, 4000),
            vol.Required(
                CONF_REPEAT_MS,
                default=options.get(CONF_REPEAT_MS, DEFAULT_REPEAT_MS),
            ): _ms_selector(100, 2000),
        }
    )


def _actions_schema(data: Mapping[str, Any]) -> dict[vol.Marker, Any]:
    """Action fields for the gestures this remote supports."""
    supports_double, supports_long = remote_capabilities(data)
    fields: dict[vol.Marker, Any] = {
        vol.Optional(gesture): selector.ActionSelector()
        for gesture in supported_gestures(data)
    }
    if supports_long:
        fields[vol.Optional(CONF_REPEAT)] = selector.BooleanSelector()
    if supports_double or supports_long:
        fields[vol.Optional(CONF_DETECT_ALL)] = selector.BooleanSelector()
    return fields


def _keep_hidden_actions(
    data: Mapping[str, Any],
    existing: Mapping[str, list[Any]],
    actions: dict[str, list[Any]],
) -> dict[str, list[Any]]:
    """Keep actions for gestures the form hid, in case they're turned back on."""
    shown = set(supported_gestures(data))
    return {
        **{g: a for g, a in existing.items() if g not in shown and a},
        **actions,
    }


def _layout_slots(entry: ConfigEntry) -> tuple[str, ...]:
    """The buttons a remote can have."""
    if _is_lutron(entry):
        return tuple(entry.data.get(CONF_PICO_BUTTONS, []))
    if entry.data.get(CONF_LAYOUT) == LAYOUT_NUMBERED:
        return NUMBERED_SLOTS
    return PICO_SLOTS


async def _async_actions_from_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[dict[str, list[Any]], dict[str, str]]:
    """Collect and validate the gesture actions from a form."""
    actions: dict[str, list[Any]] = {}
    errors: dict[str, str] = {}
    for gesture in GESTURES:
        if not (sequence := _as_list(user_input.get(gesture))):
            continue
        try:
            await async_validate_sequence(hass, sequence)
        except (vol.Invalid, HomeAssistantError):
            errors[gesture] = "invalid_action"
        actions[gesture] = sequence
    return actions, errors


def _button_data(
    slot: str,
    entities: list[str],
    actions: dict[str, list[Any]],
    repeat: bool,
    detect_all: bool = False,
) -> dict[str, Any]:
    return {
        CONF_SLOT: slot,
        CONF_ENTITIES: entities,
        CONF_ACTIONS: actions,
        CONF_REPEAT: repeat,
        CONF_DETECT_ALL: detect_all,
    }


def _button_subentry(
    slot: str,
    entities: list[str],
    actions: dict[str, list[Any]],
    repeat: bool,
    detect_all: bool = False,
) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=_button_data(slot, entities, actions, repeat, detect_all),
        subentry_type=SUBENTRY_BUTTON,
        title=SLOT_TITLES[slot],
        unique_id=slot,
    )


def _entities_in_use(
    hass: HomeAssistant, exclude_subentry_id: str | None = None
) -> set[str]:
    """Event entities already feeding a button on any remote."""
    in_use: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        for sub in entry.subentries.values():
            if (
                sub.subentry_type == SUBENTRY_BUTTON
                and sub.subentry_id != exclude_subentry_id
            ):
                in_use.update(sub.data.get(CONF_ENTITIES, []))
    return in_use


# ---------------------------------------------------------------------------
# Blueprint import
# ---------------------------------------------------------------------------


class NotABlueprintRemote(HomeAssistantError):
    """The automation does not use a compatible Pico blueprint."""


async def _async_blueprint_inputs(
    hass: HomeAssistant, automation_entity_id: str
) -> dict[str, Any]:
    """Return the blueprint inputs of a UI-created blueprint automation."""
    registry_entry = er.async_get(hass).async_get(automation_entity_id)
    automation_id = registry_entry.unique_id if registry_entry else None

    config: dict[str, Any] | None = None
    if automation_id is not None:
        path = hass.config.path("automations.yaml")
        try:
            automations = await hass.async_add_executor_job(load_yaml, path)
        except (HomeAssistantError, FileNotFoundError):
            automations = None
        if isinstance(automations, list):
            config = next(
                (
                    item
                    for item in automations
                    if isinstance(item, dict) and str(item.get("id")) == automation_id
                ),
                None,
            )

    if config is None:
        # Fall back to the loaded automation entity (covers YAML packages).
        from homeassistant.components.automation import DATA_COMPONENT

        if (component := hass.data.get(DATA_COMPONENT)) is not None and (
            entity := component.get_entity(automation_entity_id)
        ) is not None:
            config = getattr(entity, "_blueprint_inputs", None)

    inputs = (config or {}).get("use_blueprint", {}).get("input")
    if not isinstance(inputs, dict):
        raise NotABlueprintRemote
    return inputs


def parse_blueprint_inputs(
    inputs: dict[str, Any],
) -> tuple[list[ConfigSubentryData], dict[str, Any]]:
    """Convert blueprint inputs to (button subentries, entry options)."""
    entities: dict[str, list[str]] = {}
    for key, slot in BLUEPRINT_ENTITY_INPUTS.items():
        if found := _as_list(inputs.get(key)):
            entities[slot] = found

    actions: dict[str, dict[str, list[Any]]] = {}
    for key, value in inputs.items():
        for prefix, gesture in BLUEPRINT_GESTURE_PREFIXES.items():
            if not key.startswith(prefix):
                continue
            slot = key.removeprefix(prefix)
            if slot in SLOTS and (sequence := _as_list(value)):
                actions.setdefault(slot, {})[gesture] = copy.deepcopy(sequence)

    subentries = [
        _button_subentry(slot, entities[slot], actions.get(slot, {}), False)
        for slot in SLOTS
        if slot in entities
    ]
    options = {
        CONF_HOLD_MS: int(inputs.get("delay_hold", BLUEPRINT_DEFAULT_HOLD_MS)),
        CONF_DOUBLE_MS: int(inputs.get("delay_click", BLUEPRINT_DEFAULT_DOUBLE_MS)),
        CONF_REPEAT_MS: DEFAULT_REPEAT_MS,
    }
    return subentries, options


def _common_lutron_device(hass: HomeAssistant, entities: list[str]) -> str | None:
    """The Lutron Pico every one of these entities belongs to, if there is one."""
    devices = {lutron_device_for_entities(hass, [entity]) for entity in entities}
    if len(devices) == 1 and None not in devices:
        return devices.pop()
    return None


@dataclass(slots=True)
class PreparedImport:
    """A blueprint automation converted into a remote, ready to create."""

    automation: str
    title: str
    subentries: list[ConfigSubentryData]
    options: dict[str, Any]
    # Set when every button maps onto one core Lutron Pico.
    pico: str | None = None
    pico_buttons: list[str] | None = None

    def entry_args(self, use_pico: bool) -> dict[str, Any]:
        """Arguments for async_create_entry."""
        if use_pico and self.pico:
            return {
                "title": self.title,
                "data": {
                    CONF_SOURCE: SOURCE_LUTRON,
                    CONF_DEVICE_ID: self.pico,
                    CONF_PICO_BUTTONS: self.pico_buttons,
                    CONF_SOURCE_AUTOMATION: self.automation,
                },
                "options": self.options,
                "subentries": [
                    ConfigSubentryData(
                        data={**sub["data"], CONF_ENTITIES: []},
                        subentry_type=sub["subentry_type"],
                        title=sub["title"],
                        unique_id=sub["unique_id"],
                    )
                    for sub in self.subentries
                ],
            }
        return {
            "title": self.title,
            "data": {
                CONF_SOURCE: SOURCE_EVENT_ENTITY,
                CONF_EVENT_ROLES: {
                    DEFAULT_PRESS_EVENT: ROLE_PRESS,
                    DEFAULT_RELEASE_EVENT: ROLE_RELEASE,
                },
                CONF_SOURCE_AUTOMATION: self.automation,
            },
            "options": self.options,
            "subentries": self.subentries,
        }


async def async_prepare_import(hass: HomeAssistant, automation: str) -> PreparedImport:
    """Read a blueprint automation and work out how it can be imported."""
    inputs = await _async_blueprint_inputs(hass, automation)
    subentries, options = parse_blueprint_inputs(inputs)
    state = hass.states.get(automation)
    prepared = PreparedImport(
        automation=automation,
        title=state.name if state else automation,
        subentries=subentries,
        options=options,
    )
    entities = [e for sub in subentries for e in sub["data"][CONF_ENTITIES]]
    if pico := _common_lutron_device(hass, entities):
        buttons = await async_pico_buttons(hass, pico)
        if all(sub["data"][CONF_SLOT] in buttons for sub in subentries):
            prepared.pico = pico
            prepared.pico_buttons = buttons
    return prepared


async def _async_find_blueprint_remotes(hass: HomeAssistant) -> dict[str, str]:
    """Pico blueprint automations not imported yet, as {entity_id: name}."""
    path = hass.config.path("automations.yaml")
    try:
        automations = await hass.async_add_executor_job(load_yaml, path)
    except (HomeAssistantError, FileNotFoundError):
        return {}
    if not isinstance(automations, list):
        return {}

    registry = er.async_get(hass)
    in_use = _entities_in_use(hass)
    imported = {
        entry.data.get(CONF_SOURCE_AUTOMATION)
        for entry in hass.config_entries.async_entries(DOMAIN)
    }
    found: dict[str, str] = {}
    for item in automations:
        if not isinstance(item, dict) or "id" not in item:
            continue
        inputs = (item.get("use_blueprint") or {}).get("input")
        if not isinstance(inputs, dict) or not any(
            key in inputs for key in BLUEPRINT_ENTITY_INPUTS
        ):
            continue
        entity_id = registry.async_get_entity_id(
            "automation", "automation", str(item["id"])
        )
        if entity_id is None or entity_id in imported:
            continue
        entities = [
            entity
            for key in BLUEPRINT_ENTITY_INPUTS
            for entity in _as_list(inputs.get(key))
        ]
        if set(entities) & in_use or _pico_conflict(
            hass, lutron_device_for_entities(hass, entities)
        ):
            continue
        found[entity_id] = str(item.get("alias") or entity_id)
    return found


async def _async_turn_off(hass: HomeAssistant, automations: list[str]) -> None:
    await hass.services.async_call(
        "automation",
        "turn_off",
        {"entity_id": automations, "stop_actions": False},
        blocking=True,
    )


def replace_text(value: Any, find: str, replace: str) -> Any:
    """Replace text in every string inside an action list."""
    if isinstance(value, str):
        return value.replace(find, replace)
    if isinstance(value, list):
        return [replace_text(item, find, replace) for item in value]
    if isinstance(value, dict):
        return {key: replace_text(item, find, replace) for key, item in value.items()}
    return value


@dataclass(slots=True)
class RemoteCopy:
    """A remote being duplicated: everything except where presses come from."""

    title: str
    options: dict[str, Any]
    event_roles: dict[str, str]
    # Layout and capabilities, copied as they are.
    shape: dict[str, Any]
    # One dict per button: slot, actions, repeat, detect_all.
    buttons: list[dict[str, Any]]

    def subentries(self, entities: dict[str, list[str]]) -> list[ConfigSubentryData]:
        """Button subentries, fed by the given entities (empty for a Pico)."""
        return [
            _button_subentry(
                button[CONF_SLOT],
                entities.get(button[CONF_SLOT], []),
                button[CONF_ACTIONS],
                button[CONF_REPEAT],
                button[CONF_DETECT_ALL],
            )
            for button in self.buttons
        ]


def copy_remote(
    entry: ConfigEntry, title: str, find: str = "", replace: str = ""
) -> RemoteCopy:
    """Copy a remote's buttons, actions and timing, replacing text in actions."""
    buttons = []
    for sub in sorted(
        (s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_BUTTON),
        key=lambda s: SLOTS.index(s.data[CONF_SLOT]),
    ):
        actions = copy.deepcopy(dict(sub.data.get(CONF_ACTIONS, {})))
        if find:
            actions = replace_text(actions, find, replace)
        buttons.append(
            {
                CONF_SLOT: sub.data[CONF_SLOT],
                CONF_ACTIONS: actions,
                CONF_REPEAT: bool(sub.data.get(CONF_REPEAT, False)),
                CONF_DETECT_ALL: bool(sub.data.get(CONF_DETECT_ALL, False)),
            }
        )
    return RemoteCopy(
        title=title,
        options=dict(entry.options),
        event_roles=event_role_overrides(entry.data),
        shape={
            key: entry.data[key]
            for key in (CONF_LAYOUT, CONF_SUPPORTS_DOUBLE, CONF_SUPPORTS_LONG)
            if key in entry.data
        },
        buttons=buttons,
    )


# ---------------------------------------------------------------------------
# Config flow (one entry per remote)
# ---------------------------------------------------------------------------


class ButtonActionsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a remote."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize."""
        self._pending: PreparedImport | None = None
        self._disable_source = True
        self._copy: RemoteCopy | None = None
        self._reconfigure_title: str | None = None
        self._reconfigure_caps: dict[str, bool] = {}
        self._manual: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ButtonActionsOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Each button is a subentry under its remote."""
        return {SUBENTRY_BUTTON: ButtonSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between importing an automation or starting fresh."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[
                "lutron",
                "import_blueprint",
                "import_all",
                "duplicate",
                "manual",
            ],
        )

    async def async_step_lutron(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use a Pico from the core Lutron Caséta integration directly."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            if error := _pico_conflict(self.hass, device_id):
                errors[CONF_DEVICE_ID] = error
            elif not (buttons := await async_pico_buttons(self.hass, device_id)):
                errors[CONF_DEVICE_ID] = "not_a_pico"
            else:
                title = (
                    user_input.get(CONF_NAME)
                    or _device_name(self.hass, device_id)
                    or "Pico remote"
                )
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_SOURCE: SOURCE_LUTRON,
                        CONF_DEVICE_ID: device_id,
                        CONF_PICO_BUTTONS: buttons,
                    },
                    options={
                        CONF_HOLD_MS: DEFAULT_HOLD_MS,
                        CONF_DOUBLE_MS: DEFAULT_DOUBLE_MS,
                        CONF_REPEAT_MS: DEFAULT_REPEAT_MS,
                    },
                    subentries=[
                        _button_subentry(slot, [], {}, False) for slot in buttons
                    ],
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): _PICO_DEVICE,
                vol.Optional(CONF_NAME): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="lutron",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename a remote, change its event types, or move it to a Pico."""
        entry = self._get_reconfigure_entry()
        lutron = _is_lutron(entry)
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"missing": ""}

        if user_input is not None:
            title = user_input[CONF_NAME]
            device_id = user_input.get(CONF_DEVICE_ID)
            if device_id and (
                not lutron or device_id != entry.data.get(CONF_DEVICE_ID)
            ):
                # Moving to core Lutron, or swapping in a replacement Pico.
                buttons = await async_pico_buttons(self.hass, device_id)
                used = [
                    sub.data[CONF_SLOT]
                    for sub in entry.subentries.values()
                    if sub.subentry_type == SUBENTRY_BUTTON
                ]
                missing = [slot for slot in used if slot not in buttons]
                if error := _pico_conflict(self.hass, device_id, entry.entry_id):
                    errors[CONF_DEVICE_ID] = error
                elif not buttons:
                    errors[CONF_DEVICE_ID] = "not_a_pico"
                elif missing:
                    errors[CONF_DEVICE_ID] = "buttons_missing"
                    placeholders["missing"] = ", ".join(
                        SLOT_TITLES[slot] for slot in missing
                    )
                else:
                    for sub in list(entry.subentries.values()):
                        if sub.subentry_type == SUBENTRY_BUTTON and sub.data.get(
                            CONF_ENTITIES
                        ):
                            self.hass.config_entries.async_update_subentry(
                                entry, sub, data={**sub.data, CONF_ENTITIES: []}
                            )
                    return self.async_update_reload_and_abort(
                        entry,
                        title=title,
                        data={
                            CONF_SOURCE: SOURCE_LUTRON,
                            CONF_DEVICE_ID: device_id,
                            CONF_PICO_BUTTONS: buttons,
                        },
                    )
            elif lutron:
                return self.async_update_reload_and_abort(entry, title=title)
            else:
                self._reconfigure_title = title
                self._reconfigure_caps = {
                    CONF_SUPPORTS_DOUBLE: user_input.get(CONF_SUPPORTS_DOUBLE, True),
                    CONF_SUPPORTS_LONG: user_input.get(CONF_SUPPORTS_LONG, True),
                }
                return await self.async_step_reconfigure_events()

        fields: dict[vol.Marker, Any] = {
            vol.Required(CONF_NAME): selector.TextSelector()
        }
        if lutron:
            fields[vol.Required(CONF_DEVICE_ID)] = _PICO_DEVICE
            suggested: dict[str, Any] = {
                CONF_NAME: entry.title,
                CONF_DEVICE_ID: entry.data.get(CONF_DEVICE_ID),
            }
        else:
            current_double, current_long = remote_capabilities(entry.data)
            fields[vol.Optional(CONF_SUPPORTS_DOUBLE, default=current_double)] = (
                selector.BooleanSelector()
            )
            fields[vol.Optional(CONF_SUPPORTS_LONG, default=current_long)] = (
                selector.BooleanSelector()
            )
            fields[vol.Optional(CONF_DEVICE_ID)] = _PICO_DEVICE
            all_entities = [
                entity
                for sub in entry.subentries.values()
                for entity in sub.data.get(CONF_ENTITIES, [])
            ]
            supports_double, supports_long = remote_capabilities(entry.data)
            suggested = {
                CONF_NAME: entry.title,
                CONF_SUPPORTS_DOUBLE: supports_double,
                CONF_SUPPORTS_LONG: supports_long,
            }
            if pico := lutron_device_for_entities(self.hass, all_entities):
                suggested[CONF_DEVICE_ID] = pico

        return self.async_show_form(
            step_id="reconfigure_lutron" if lutron else "reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), user_input or suggested
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure_events(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what each event type from the buttons means, and let it change."""
        entry = self._get_reconfigure_entry()
        title = self._reconfigure_title or entry.title
        overrides = event_role_overrides(entry.data)

        # Every event type the remote's entities can send, in the order they
        # report them, plus any the user mapped before.
        reported: list[str] = []
        for sub in entry.subentries.values():
            for entity_id in sub.data.get(CONF_ENTITIES, []):
                if state := self.hass.states.get(entity_id):
                    reported += list(state.attributes.get("event_types") or [])
        event_types = list(dict.fromkeys([*reported, *overrides]))

        if user_input is not None or not event_types:
            data = {
                key: value
                for key, value in entry.data.items()
                if key not in (CONF_PRESS_EVENT, CONF_RELEASE_EVENT)
            }
            data[CONF_SOURCE] = SOURCE_EVENT_ENTITY
            data.update(self._reconfigure_caps)
            data[CONF_EVENT_ROLES] = (
                {t: user_input[t] for t in event_types if t in user_input}
                if user_input is not None
                else overrides
            )
            return self.async_update_reload_and_abort(entry, title=title, data=data)

        role_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(ROLES),
                translation_key="event_role",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        schema = vol.Schema(
            {
                vol.Required(
                    event_type, default=resolve_role(event_type, reported, overrides)
                ): role_selector
                for event_type in event_types
            }
        )
        return self.async_show_form(
            step_id="reconfigure_events",
            data_schema=schema,
            description_placeholders={"remote": title},
        )

    async def async_step_reconfigure_lutron(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Submit target for the Pico-remote version of the reconfigure form."""
        return await self.async_step_reconfigure(user_input)

    async def async_step_import_blueprint(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Convert an existing Pico blueprint automation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            automation = user_input[CONF_AUTOMATION]
            try:
                prepared = await async_prepare_import(self.hass, automation)
            except NotABlueprintRemote:
                errors[CONF_AUTOMATION] = "not_blueprint"
            else:
                errors = await self._async_check(prepared.subentries)
                if not errors:
                    self._pending = prepared
                    self._disable_source = user_input.get(CONF_DISABLE_SOURCE, True)
                    if prepared.pico:
                        return await self.async_step_import_choice()
                    return await self._async_finish_import(use_pico=False)

        return self.async_show_form(
            step_id="import_blueprint",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTOMATION): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="automation")
                    ),
                    vol.Optional(
                        CONF_DISABLE_SOURCE, default=True
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_import_choice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to read presses straight from the Pico."""
        assert self._pending is not None
        return self.async_show_menu(
            step_id="import_choice",
            menu_options=["import_pico", "import_entities"],
            description_placeholders={"remote": self._pending.title},
        )

    async def async_step_import_pico(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import, reading presses straight from core Lutron."""
        return await self._async_finish_import(use_pico=True)

    async def async_step_import_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import, keeping the blueprint's event entities."""
        return await self._async_finish_import(use_pico=False)

    async def _async_finish_import(self, use_pico: bool) -> ConfigFlowResult:
        prepared = self._pending
        assert prepared is not None
        if self._disable_source:
            await _async_turn_off(self.hass, [prepared.automation])
        return self.async_create_entry(**prepared.entry_args(use_pico))

    async def async_step_import_all(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import every Pico blueprint automation at once."""
        found = await _async_find_blueprint_remotes(self.hass)
        if not found:
            return self.async_abort(reason="no_blueprint_automations")

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = [a for a in user_input.get(CONF_AUTOMATIONS, []) if a in found]
            prepared_all: list[PreparedImport] = []
            for automation in selected:
                try:
                    prepared = await async_prepare_import(self.hass, automation)
                except NotABlueprintRemote:
                    continue
                if not await self._async_check(prepared.subentries):
                    prepared_all.append(prepared)
            if not prepared_all:
                errors["base"] = "nothing_to_import"
            else:
                use_pico = user_input.get(CONF_USE_PICO, True)
                if user_input.get(CONF_DISABLE_SOURCE, True):
                    await _async_turn_off(
                        self.hass, [p.automation for p in prepared_all]
                    )
                # A flow creates one entry; hand the rest to import flows.
                for prepared in prepared_all[1:]:
                    self.hass.async_create_task(
                        self.hass.config_entries.flow.async_init(
                            DOMAIN,
                            context={"source": SOURCE_IMPORT},
                            data=prepared.entry_args(use_pico),
                        )
                    )
                return self.async_create_entry(**prepared_all[0].entry_args(use_pico))

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTOMATIONS, default=list(found)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=entity_id, label=name)
                            for entity_id, name in found.items()
                        ],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_USE_PICO, default=True): selector.BooleanSelector(),
                vol.Optional(
                    CONF_DISABLE_SOURCE, default=True
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="import_all", data_schema=schema, errors=errors
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Create one remote handed over by Import all."""
        return self.async_create_entry(**import_data)

    async def async_step_duplicate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Copy an existing remote's buttons, actions and timing."""
        remotes = {
            entry.entry_id: entry.title
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if any(
                s.subentry_type == SUBENTRY_BUTTON for s in entry.subentries.values()
            )
        }
        if not remotes:
            return self.async_abort(reason="no_remotes")

        if user_input is not None:
            source = self.hass.config_entries.async_get_entry(user_input[CONF_REMOTE])
            if source is not None:
                self._copy = copy_remote(
                    source,
                    user_input[CONF_NAME],
                    user_input.get(CONF_FIND) or "",
                    user_input.get(CONF_REPLACE) or "",
                )
                return await self.async_step_duplicate_source()

        schema = vol.Schema(
            {
                vol.Required(CONF_REMOTE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=entry_id, label=title)
                            for entry_id, title in sorted(
                                remotes.items(), key=lambda item: item[1]
                            )
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Optional(CONF_FIND): selector.TextSelector(),
                vol.Optional(CONF_REPLACE): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="duplicate",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
        )

    async def async_step_duplicate_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose where the copy reads presses from."""
        assert self._copy is not None
        return self.async_show_menu(
            step_id="duplicate_source",
            menu_options=["duplicate_pico", "duplicate_entities"],
            description_placeholders={"remote": self._copy.title},
        )

    async def async_step_duplicate_pico(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the copy at a Lutron Caséta Pico."""
        copied = self._copy
        assert copied is not None
        errors: dict[str, str] = {}
        placeholders = {"missing": ""}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            buttons = await async_pico_buttons(self.hass, device_id)
            missing = [
                b[CONF_SLOT] for b in copied.buttons if b[CONF_SLOT] not in buttons
            ]
            if error := _pico_conflict(self.hass, device_id):
                errors[CONF_DEVICE_ID] = error
            elif not buttons:
                errors[CONF_DEVICE_ID] = "not_a_pico"
            elif missing:
                errors[CONF_DEVICE_ID] = "buttons_missing"
                placeholders["missing"] = ", ".join(SLOT_TITLES[s] for s in missing)
            else:
                return self.async_create_entry(
                    title=copied.title,
                    data={
                        CONF_SOURCE: SOURCE_LUTRON,
                        CONF_DEVICE_ID: device_id,
                        CONF_PICO_BUTTONS: buttons,
                    },
                    options=copied.options,
                    subentries=copied.subentries({}),
                )

        return self.async_show_form(
            step_id="duplicate_pico",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_DEVICE_ID): _PICO_DEVICE}), user_input
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_duplicate_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the event entities for each button on the copy."""
        copied = self._copy
        assert copied is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = {
                b[CONF_SLOT]: _as_list(user_input.get(b[CONF_SLOT]))
                for b in copied.buttons
            }
            subentries = copied.subentries(entities)
            errors = await self._async_check(subentries)
            if not errors:
                return self.async_create_entry(
                    title=copied.title,
                    data={
                        CONF_SOURCE: SOURCE_EVENT_ENTITY,
                        CONF_EVENT_ROLES: copied.event_roles,
                        **copied.shape,
                    },
                    options=copied.options,
                    subentries=subentries,
                )

        schema = vol.Schema(
            {vol.Required(b[CONF_SLOT]): _EVENT_ENTITIES for b in copied.buttons}
        )
        numbered = copied.shape.get(CONF_LAYOUT) == LAYOUT_NUMBERED
        return self.async_show_form(
            step_id="duplicate_numbered" if numbered else "duplicate_entities",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_duplicate_numbered(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Numbered-button version of the duplicate entities form."""
        return await self.async_step_duplicate_entities(user_input)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the remote, and say how many buttons it has and what it can do."""
        if user_input is not None:
            self._manual = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_BUTTON_COUNT: int(user_input[CONF_BUTTON_COUNT]),
                CONF_SUPPORTS_DOUBLE: user_input.get(CONF_SUPPORTS_DOUBLE, True),
                CONF_SUPPORTS_LONG: user_input.get(CONF_SUPPORTS_LONG, True),
            }
            return await self.async_step_manual_buttons()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_BUTTON_COUNT, default=2): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=MAX_BUTTONS,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SUPPORTS_DOUBLE, default=True
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SUPPORTS_LONG, default=True
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema)

    async def async_step_manual_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the event entity for each button."""
        manual = self._manual
        assert manual is not None
        slots = NUMBERED_SLOTS[: manual[CONF_BUTTON_COUNT]]
        errors: dict[str, str] = {}
        if user_input is not None:
            subentries = [
                _button_subentry(slot, _as_list(user_input.get(slot)), {}, False)
                for slot in slots
            ]
            errors = await self._async_check(subentries)
            if not errors:
                return self.async_create_entry(
                    title=manual[CONF_NAME],
                    data={
                        CONF_SOURCE: SOURCE_EVENT_ENTITY,
                        CONF_EVENT_ROLES: {},
                        CONF_LAYOUT: LAYOUT_NUMBERED,
                        CONF_SUPPORTS_DOUBLE: manual[CONF_SUPPORTS_DOUBLE],
                        CONF_SUPPORTS_LONG: manual[CONF_SUPPORTS_LONG],
                    },
                    options={
                        CONF_HOLD_MS: DEFAULT_HOLD_MS,
                        CONF_DOUBLE_MS: DEFAULT_DOUBLE_MS,
                        CONF_REPEAT_MS: DEFAULT_REPEAT_MS,
                    },
                    subentries=subentries,
                )

        schema = vol.Schema({vol.Required(slot): _EVENT_ENTITIES for slot in slots})
        return self.async_show_form(
            step_id="manual_buttons",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders={"remote": manual[CONF_NAME]},
        )

    async def _async_check(
        self, subentries: list[ConfigSubentryData]
    ) -> dict[str, str]:
        if not subentries or any(not sub["data"][CONF_ENTITIES] for sub in subentries):
            return {"base": "no_buttons"}
        all_entities = {e for sub in subentries for e in sub["data"][CONF_ENTITIES]}
        if all_entities & _entities_in_use(self.hass):
            return {"base": "already_configured"}
        if _pico_conflict(
            self.hass, lutron_device_for_entities(self.hass, sorted(all_entities))
        ):
            return {"base": "pico_in_use"}
        for sub in subentries:
            for sequence in sub["data"][CONF_ACTIONS].values():
                try:
                    await async_validate_sequence(self.hass, sequence)
                except (vol.Invalid, HomeAssistantError) as err:
                    _LOGGER.warning("Imported action is invalid: %s", err)
                    return {"base": "invalid_action"}
        return {}


# ---------------------------------------------------------------------------
# Options flow (remote-wide settings, the gear icon)
# ---------------------------------------------------------------------------


class ButtonActionsOptionsFlow(OptionsFlow):
    """Click timing for the whole remote."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Adjust click timing."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=_timing_schema(dict(self.config_entry.options)),
        )


# ---------------------------------------------------------------------------
# Button subentry flow (add a button, or edit one with the pencil)
# ---------------------------------------------------------------------------


class ButtonSubentryFlow(ConfigSubentryFlow):
    """Add or edit one button."""

    def __init__(self) -> None:
        """Initialize."""
        self._slot: str | None = None
        self._entities: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick which button to add and its event entities."""
        entry = self._get_entry()
        lutron = _is_lutron(entry)
        used = {sub.unique_id for sub in entry.subentries.values()}
        numbered = not lutron and entry.data.get(CONF_LAYOUT) == LAYOUT_NUMBERED
        free = [slot for slot in _layout_slots(entry) if slot not in used]
        if not free:
            return self.async_abort(reason="all_buttons_added")

        errors: dict[str, str] = {}
        if user_input is not None and lutron:
            self._slot = user_input[CONF_SLOT]
            return await self.async_step_actions()
        if user_input is not None:
            entities = _as_list(user_input.get(CONF_ENTITIES))
            if not entities:
                errors[CONF_ENTITIES] = "no_entities"
            elif set(entities) & _entities_in_use(self.hass):
                errors[CONF_ENTITIES] = "already_configured"
            else:
                self._slot = user_input[CONF_SLOT]
                self._entities = entities
                return await self.async_step_actions()

        schema = vol.Schema(
            {
                vol.Required(CONF_SLOT, default=free[0]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=free,
                        translation_key="numbered_slot" if numbered else CONF_SLOT,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                **({} if lutron else {vol.Required(CONF_ENTITIES): _EVENT_ENTITIES}),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Set what the new button does."""
        assert self._slot is not None
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            actions, errors = await _async_actions_from_input(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=SLOT_TITLES[self._slot],
                    data=_button_data(
                        self._slot,
                        self._entities,
                        actions,
                        bool(user_input.get(CONF_REPEAT)),
                        bool(user_input.get(CONF_DETECT_ALL)),
                    ),
                    unique_id=self._slot,
                )

        return self.async_show_form(
            step_id="actions",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_actions_schema(entry.data)), user_input
            ),
            errors=errors,
            description_placeholders={
                "button": button_title(
                    entry.data.get(CONF_LAYOUT, LAYOUT_PICO), self._slot, [self._slot]
                )
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a button's actions and event entities."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        slot = subentry.data[CONF_SLOT]

        lutron = _is_lutron(entry)
        errors: dict[str, str] = {}
        if user_input is not None:
            entities = _as_list(user_input.get(CONF_ENTITIES))
            actions, errors = await _async_actions_from_input(self.hass, user_input)
            if lutron:
                entities = []
            elif not entities:
                errors[CONF_ENTITIES] = "no_entities"
            elif set(entities) & _entities_in_use(self.hass, subentry.subentry_id):
                errors[CONF_ENTITIES] = "already_configured"
            if not errors:
                actions = _keep_hidden_actions(
                    entry.data, subentry.data.get(CONF_ACTIONS, {}), actions
                )
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    data=_button_data(
                        slot,
                        entities,
                        actions,
                        bool(user_input.get(CONF_REPEAT)),
                        bool(user_input.get(CONF_DETECT_ALL)),
                    ),
                )

        suggested = user_input or {
            CONF_ENTITIES: subentry.data.get(CONF_ENTITIES, []),
            **subentry.data.get(CONF_ACTIONS, {}),
            CONF_REPEAT: subentry.data.get(CONF_REPEAT, False),
            CONF_DETECT_ALL: subentry.data.get(CONF_DETECT_ALL, False),
        }
        schema = vol.Schema(
            _actions_schema(entry.data)
            if lutron
            else {
                vol.Required(CONF_ENTITIES): _EVENT_ENTITIES,
                **_actions_schema(entry.data),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"button": subentry.title},
        )
