"""Changing an entity's ID keeps it running (Home Assistant 2026.11+)."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

import custom_components.button_actions as package
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from tests.test_init import ON, _fire, _light_on, _setup

LIFECYCLE = (
    "async_prepare_to_add_to_hass",
    "async_added_to_hass",
    "async_will_remove_from_hass",
)


def _entity_classes() -> list[type[Entity]]:
    classes: dict[str, type[Entity]] = {}
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        module = importlib.import_module(info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, Entity) and cls.__module__.startswith(package.__name__):
                classes[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return list(classes.values())


def test_every_entity_with_lifecycle_code_handles_entity_id_changes() -> None:
    """Without the hook, 2026.11 removes and re-adds the entity on a rename."""
    classes = _entity_classes()
    assert classes
    missing = sorted(
        f"{cls.__module__}.{cls.__qualname__}"
        for cls in classes
        if any(name in cls.__dict__ for name in LIFECYCLE)
        and "async_entity_id_changed" not in cls.__dict__
    )
    assert not missing, f"Missing async_entity_id_changed: {', '.join(missing)}"


@pytest.mark.skipif(
    not hasattr(Entity, "async_entity_id_changed"),
    reason="Home Assistant before 2026.11 re-adds a renamed entity",
)
async def test_gesture_event_keeps_working_after_rename(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    await _setup(hass, {"on": {"short_press": _light_on({})}})
    old, new = "event.kitchen_remote_1_on", "event.renamed_on_button"
    assert hass.states.get(old) is not None

    er.async_get(hass).async_update_entity(old, new_entity_id=new)
    await hass.async_block_till_done()
    assert hass.states.get(old) is None
    assert hass.states.get(new) is not None

    _fire(hass, ON, "press")
    _fire(hass, ON, "release")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(new).attributes["event_type"] == "short_press"
    assert hass.states.get(old) is None
