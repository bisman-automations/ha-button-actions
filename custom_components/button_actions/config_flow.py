"""Config, options and button subentry flows for Button Actions."""

from __future__ import annotations

import copy
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.util.yaml import load_yaml

from .const import (
    BLUEPRINT_DEFAULT_DOUBLE_MS,
    BLUEPRINT_DEFAULT_HOLD_MS,
    BLUEPRINT_ENTITY_INPUTS,
    BLUEPRINT_GESTURE_PREFIXES,
    CONF_ACTIONS,
    CONF_DOUBLE_MS,
    CONF_ENTITIES,
    CONF_HOLD_MS,
    CONF_PRESS_EVENT,
    CONF_RELEASE_EVENT,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    CONF_SLOT,
    DEFAULT_DOUBLE_MS,
    DEFAULT_HOLD_MS,
    DEFAULT_PRESS_EVENT,
    DEFAULT_RELEASE_EVENT,
    DEFAULT_REPEAT_MS,
    DOMAIN,
    GESTURES,
    SLOT_TITLES,
    SLOTS,
    SUBENTRY_BUTTON,
)
from .controller import async_validate_sequence

_LOGGER = logging.getLogger(__name__)

CONF_AUTOMATION = "automation"
CONF_DISABLE_SOURCE = "disable_source"

_EVENT_ENTITIES = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="event", multiple=True)
)


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


def _actions_schema() -> dict[vol.Marker, Any]:
    return {
        **{vol.Optional(gesture): selector.ActionSelector() for gesture in GESTURES},
        vol.Optional(CONF_REPEAT): selector.BooleanSelector(),
    }


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
    slot: str, entities: list[str], actions: dict[str, list[Any]], repeat: bool
) -> dict[str, Any]:
    return {
        CONF_SLOT: slot,
        CONF_ENTITIES: entities,
        CONF_ACTIONS: actions,
        CONF_REPEAT: repeat,
    }


def _button_subentry(
    slot: str, entities: list[str], actions: dict[str, list[Any]], repeat: bool
) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=_button_data(slot, entities, actions, repeat),
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


# ---------------------------------------------------------------------------
# Config flow (one entry per remote)
# ---------------------------------------------------------------------------


class ButtonActionsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a remote."""

    VERSION = 1
    MINOR_VERSION = 2

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
            step_id="user", menu_options=["import_blueprint", "manual"]
        )

    async def async_step_import_blueprint(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Convert an existing Pico blueprint automation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            automation = user_input[CONF_AUTOMATION]
            try:
                inputs = await _async_blueprint_inputs(self.hass, automation)
            except NotABlueprintRemote:
                errors[CONF_AUTOMATION] = "not_blueprint"
            else:
                subentries, options = parse_blueprint_inputs(inputs)
                errors = await self._async_check(subentries)
                if not errors:
                    if user_input.get(CONF_DISABLE_SOURCE, True):
                        await self.hass.services.async_call(
                            "automation",
                            "turn_off",
                            {"entity_id": automation, "stop_actions": False},
                            blocking=True,
                        )
                    state = self.hass.states.get(automation)
                    return self.async_create_entry(
                        title=state.name if state else automation,
                        data={
                            CONF_PRESS_EVENT: DEFAULT_PRESS_EVENT,
                            CONF_RELEASE_EVENT: DEFAULT_RELEASE_EVENT,
                        },
                        options=options,
                        subentries=subentries,
                    )

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

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the event entities for a new remote."""
        errors: dict[str, str] = {}
        if user_input is not None:
            subentries = [
                _button_subentry(slot, entities, {}, False)
                for slot in SLOTS
                if (entities := _as_list(user_input.get(slot)))
            ]
            errors = await self._async_check(subentries)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_PRESS_EVENT: user_input[CONF_PRESS_EVENT],
                        CONF_RELEASE_EVENT: user_input[CONF_RELEASE_EVENT],
                    },
                    options={
                        CONF_HOLD_MS: DEFAULT_HOLD_MS,
                        CONF_DOUBLE_MS: DEFAULT_DOUBLE_MS,
                        CONF_REPEAT_MS: DEFAULT_REPEAT_MS,
                    },
                    subentries=subentries,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                **{vol.Optional(slot): _EVENT_ENTITIES for slot in SLOTS},
                vol.Required(
                    CONF_PRESS_EVENT, default=DEFAULT_PRESS_EVENT
                ): selector.TextSelector(),
                vol.Required(
                    CONF_RELEASE_EVENT, default=DEFAULT_RELEASE_EVENT
                ): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def _async_check(
        self, subentries: list[ConfigSubentryData]
    ) -> dict[str, str]:
        if not subentries:
            return {"base": "no_buttons"}
        all_entities = {e for sub in subentries for e in sub["data"][CONF_ENTITIES]}
        if all_entities & _entities_in_use(self.hass):
            return {"base": "already_configured"}
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
        used = {sub.unique_id for sub in entry.subentries.values()}
        free = [slot for slot in SLOTS if slot not in used]
        if not free:
            return self.async_abort(reason="all_buttons_added")

        errors: dict[str, str] = {}
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
                        translation_key=CONF_SLOT,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_ENTITIES): _EVENT_ENTITIES,
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
                    ),
                    unique_id=self._slot,
                )

        return self.async_show_form(
            step_id="actions",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_actions_schema()), user_input
            ),
            errors=errors,
            description_placeholders={"button": SLOT_TITLES[self._slot]},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a button's actions and event entities."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        slot = subentry.data[CONF_SLOT]

        errors: dict[str, str] = {}
        if user_input is not None:
            entities = _as_list(user_input.get(CONF_ENTITIES))
            actions, errors = await _async_actions_from_input(self.hass, user_input)
            if not entities:
                errors[CONF_ENTITIES] = "no_entities"
            elif set(entities) & _entities_in_use(self.hass, subentry.subentry_id):
                errors[CONF_ENTITIES] = "already_configured"
            if not errors:
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    data=_button_data(
                        slot, entities, actions, bool(user_input.get(CONF_REPEAT))
                    ),
                )

        suggested = user_input or {
            CONF_ENTITIES: subentry.data.get(CONF_ENTITIES, []),
            **subentry.data.get(CONF_ACTIONS, {}),
            CONF_REPEAT: subentry.data.get(CONF_REPEAT, False),
        }
        schema = vol.Schema(
            {vol.Required(CONF_ENTITIES): _EVENT_ENTITIES, **_actions_schema()}
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"button": subentry.title},
        )
