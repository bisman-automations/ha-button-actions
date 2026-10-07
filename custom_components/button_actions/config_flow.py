"""Config and options flows for Button Actions."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
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
    CONF_BUTTONS,
    CONF_DOUBLE_MS,
    CONF_HOLD_MS,
    CONF_PRESS_EVENT,
    CONF_RELEASE_EVENT,
    CONF_REPEAT,
    CONF_REPEAT_MS,
    DEFAULT_DOUBLE_MS,
    DEFAULT_HOLD_MS,
    DEFAULT_PRESS_EVENT,
    DEFAULT_RELEASE_EVENT,
    DEFAULT_REPEAT_MS,
    DOMAIN,
    GESTURES,
    SLOTS,
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


def _buttons_schema() -> dict[vol.Marker, Any]:
    return {vol.Optional(slot): _EVENT_ENTITIES for slot in SLOTS}


def _buttons_from_input(user_input: dict[str, Any]) -> dict[str, list[str]]:
    return {slot: ents for slot in SLOTS if (ents := _as_list(user_input.get(slot)))}


def _entities_in_use(
    hass: HomeAssistant, exclude_entry_id: str | None = None
) -> set[str]:
    in_use: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        for entities in entry.data.get(CONF_BUTTONS, {}).values():
            in_use.update(entities)
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
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Convert blueprint inputs to (entry data buttons, entry options)."""
    buttons: dict[str, list[str]] = {}
    for key, slot in BLUEPRINT_ENTITY_INPUTS.items():
        if entities := _as_list(inputs.get(key)):
            buttons[slot] = entities

    actions: dict[str, dict[str, list[Any]]] = {}
    for key, value in inputs.items():
        for prefix, gesture in BLUEPRINT_GESTURE_PREFIXES.items():
            if not key.startswith(prefix):
                continue
            slot = key.removeprefix(prefix)
            if slot in SLOTS and (sequence := _as_list(value)):
                actions.setdefault(slot, {})[gesture] = copy.deepcopy(sequence)

    options = {
        CONF_HOLD_MS: int(inputs.get("delay_hold", BLUEPRINT_DEFAULT_HOLD_MS)),
        CONF_DOUBLE_MS: int(inputs.get("delay_click", BLUEPRINT_DEFAULT_DOUBLE_MS)),
        CONF_REPEAT_MS: DEFAULT_REPEAT_MS,
        CONF_ACTIONS: actions,
        CONF_REPEAT: [],
    }
    return buttons, options


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


class ButtonActionsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a remote."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ButtonActionsOptionsFlow()

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
                buttons, options = parse_blueprint_inputs(inputs)
                errors = await self._async_check(buttons, options)
                if not errors:
                    if user_input.get(CONF_DISABLE_SOURCE, True):
                        await self.hass.services.async_call(
                            "automation",
                            "turn_off",
                            {"entity_id": automation, "stop_actions": False},
                            blocking=True,
                        )
                    state = self.hass.states.get(automation)
                    title = state.name if state else automation
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_BUTTONS: buttons,
                            CONF_PRESS_EVENT: DEFAULT_PRESS_EVENT,
                            CONF_RELEASE_EVENT: DEFAULT_RELEASE_EVENT,
                        },
                        options=options,
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
            buttons = _buttons_from_input(user_input)
            errors = await self._async_check(buttons, {})
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_BUTTONS: buttons,
                        CONF_PRESS_EVENT: user_input[CONF_PRESS_EVENT],
                        CONF_RELEASE_EVENT: user_input[CONF_RELEASE_EVENT],
                    },
                    options={
                        CONF_HOLD_MS: DEFAULT_HOLD_MS,
                        CONF_DOUBLE_MS: DEFAULT_DOUBLE_MS,
                        CONF_REPEAT_MS: DEFAULT_REPEAT_MS,
                        CONF_ACTIONS: {},
                        CONF_REPEAT: [],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                **_buttons_schema(),
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
        self, buttons: dict[str, list[str]], options: dict[str, Any]
    ) -> dict[str, str]:
        if not buttons:
            return {"base": "no_buttons"}
        all_entities = {e for ents in buttons.values() for e in ents}
        if all_entities & _entities_in_use(self.hass):
            return {"base": "already_configured"}
        for gestures in options.get(CONF_ACTIONS, {}).values():
            for sequence in gestures.values():
                try:
                    await async_validate_sequence(self.hass, sequence)
                except (vol.Invalid, HomeAssistantError) as err:
                    _LOGGER.warning("Imported action is invalid: %s", err)
                    return {"base": "invalid_action"}
        return {}


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


def _slot_step(
    slot: str,
) -> Callable[
    [ButtonActionsOptionsFlow, dict[str, Any] | None],
    Coroutine[Any, Any, ConfigFlowResult],
]:
    async def _step(
        self: ButtonActionsOptionsFlow, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_configure_button(slot, user_input)

    return _step


class ButtonActionsOptionsFlow(OptionsFlow):
    """Edit what each button does."""

    def __init__(self) -> None:
        """Initialize."""
        self._options: dict[str, Any] = {}
        self._buttons: dict[str, list[str]] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show one menu entry per button, plus timing and sources."""
        if not self._options:
            self._options = copy.deepcopy(dict(self.config_entry.options))
            self._options.setdefault(CONF_ACTIONS, {})
            self._options.setdefault(CONF_REPEAT, [])
            self._buttons = copy.deepcopy(
                dict(self.config_entry.data.get(CONF_BUTTONS, {}))
            )
        menu = [slot for slot in SLOTS if self._buttons.get(slot)]
        menu += ["timing", "sources", "save"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    # One step per slot so each button is a single click from the menu.
    async_step_on = _slot_step("on")
    async_step_raise = _slot_step("raise")
    async_step_stop = _slot_step("stop")
    async_step_lower = _slot_step("lower")
    async_step_off = _slot_step("off")
    async_step_button_1 = _slot_step("button_1")
    async_step_button_2 = _slot_step("button_2")
    async_step_button_3 = _slot_step("button_3")
    async_step_button_4 = _slot_step("button_4")

    async def async_configure_button(
        self, slot: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Edit the four gesture actions for one button."""
        errors: dict[str, str] = {}
        if user_input is not None:
            gestures: dict[str, list[Any]] = {}
            for gesture in GESTURES:
                sequence = _as_list(user_input.get(gesture))
                if not sequence:
                    continue
                try:
                    await async_validate_sequence(self.hass, sequence)
                except (vol.Invalid, HomeAssistantError):
                    errors[gesture] = "invalid_action"
                gestures[gesture] = sequence
            if not errors:
                if gestures:
                    self._options[CONF_ACTIONS][slot] = gestures
                else:
                    self._options[CONF_ACTIONS].pop(slot, None)
                repeat = set(self._options[CONF_REPEAT])
                if user_input.get(CONF_REPEAT):
                    repeat.add(slot)
                else:
                    repeat.discard(slot)
                self._options[CONF_REPEAT] = sorted(repeat)
                return await self.async_step_init()

        current = self._options[CONF_ACTIONS].get(slot, {})
        suggested = user_input or {
            **current,
            CONF_REPEAT: slot in self._options[CONF_REPEAT],
        }
        schema = vol.Schema(
            {
                **{
                    vol.Optional(gesture): selector.ActionSelector()
                    for gesture in GESTURES
                },
                vol.Optional(CONF_REPEAT): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id=slot,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_timing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Adjust click timing."""
        if user_input is not None:
            for key in (CONF_HOLD_MS, CONF_DOUBLE_MS, CONF_REPEAT_MS):
                self._options[key] = int(user_input[key])
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DOUBLE_MS,
                    default=self._options.get(CONF_DOUBLE_MS, DEFAULT_DOUBLE_MS),
                ): _ms_selector(100, 1000),
                vol.Required(
                    CONF_HOLD_MS,
                    default=self._options.get(CONF_HOLD_MS, DEFAULT_HOLD_MS),
                ): _ms_selector(300, 4000),
                vol.Required(
                    CONF_REPEAT_MS,
                    default=self._options.get(CONF_REPEAT_MS, DEFAULT_REPEAT_MS),
                ): _ms_selector(100, 2000),
            }
        )
        return self.async_show_form(step_id="timing", data_schema=schema)

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change which event entities feed each button."""
        errors: dict[str, str] = {}
        if user_input is not None:
            buttons = _buttons_from_input(user_input)
            all_entities = {e for ents in buttons.values() for e in ents}
            if not buttons:
                errors["base"] = "no_buttons"
            elif all_entities & _entities_in_use(self.hass, self.config_entry.entry_id):
                errors["base"] = "already_configured"
            else:
                self._buttons = buttons
                return await self.async_step_init()

        schema = vol.Schema(_buttons_schema())
        return self.async_show_form(
            step_id="sources",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self._buttons
            ),
            errors=errors,
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Store everything; the entry reloads with the new config."""
        if self._buttons != self.config_entry.data.get(CONF_BUTTONS):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_BUTTONS: self._buttons},
            )
        return self.async_create_entry(data=self._options)
