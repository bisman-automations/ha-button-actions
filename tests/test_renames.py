"""A button keeps working when its source entity's ID is changed (1.13.2)."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.button_actions.const import CONF_ENTITIES, CONF_SLOT, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from tests.test_v1_3 import LIGHT_ON, OFF, ON, _button, _event_remote, _fire, _settle

RENAMED = "event.hall_remote_on"


def _entities(entry) -> dict[str, list[str]]:
    return {
        sub.data[CONF_SLOT]: list(sub.data[CONF_ENTITIES])
        for sub in entry.subentries.values()
    }


async def test_button_follows_a_renamed_source_entity(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    entry = await _event_remote(
        hass,
        [_button("on", [ON], {"short_press": LIGHT_ON}), _button("off", [OFF])],
    )

    # The source entity is given a new ID; its state moves with it.
    hass.states.async_remove(ON)
    er.async_get(hass).async_update_entity(ON, new_entity_id=RENAMED)
    hass.states.async_set(RENAMED, "unknown")
    _fire(hass, RENAMED, "release")
    await _settle(hass)

    assert _entities(entry) == {"on": [RENAMED], "off": [OFF]}
    # Nothing is reported missing.
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"source_missing_{entry.entry_id}")
        is None
    )

    # Presses on the new ID run the button's action.
    _fire(hass, RENAMED, "press")
    _fire(hass, RENAMED, "release")
    await _settle(hass, 1)
    assert len(calls) == 1


async def test_other_renames_leave_the_buttons_alone(hass: HomeAssistant) -> None:
    entry = await _event_remote(hass, [_button("on", [ON]), _button("off", [OFF])])
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("light", "test", "lamp")
    ent_reg.async_update_entity("light.test_lamp", new_entity_id="light.desk_lamp")
    ent_reg.async_update_entity(ON, name="On button")
    await _settle(hass)
    assert _entities(entry) == {"on": [ON], "off": [OFF]}
