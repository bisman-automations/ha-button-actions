"""Download diagnostics for a remote."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .controller import settings_for_button
from .events import resolve_role
from .issues import automation_issue_id, source_issue_id

if TYPE_CHECKING:
    from . import ButtonActionsConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> dict[str, Any]:
    """Everything needed to understand why a remote behaves the way it does."""
    controller = entry.runtime_data
    issues = ir.async_get(hass)
    return {
        "remote": {
            "title": entry.title,
            "version": f"{entry.version}.{entry.minor_version}",
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "buttons": [
            {
                "button": button.slot,
                "entities": button.entities,
                "actions": button.actions,
                "repeat": button.repeat,
                "detect_all": button.detect_all,
                "detection": {
                    "double": settings.detect_double,
                    "hold": settings.detect_hold,
                    "repeat": settings.repeat,
                },
                "entity_states": {
                    entity_id: (
                        {
                            "state": state.state,
                            "event_type": state.attributes.get("event_type"),
                            "event_roles": {
                                event_type: resolve_role(
                                    event_type,
                                    state.attributes.get("event_types"),
                                    controller.event_roles,
                                )
                                for event_type in state.attributes.get("event_types")
                                or []
                            },
                        }
                        if (state := hass.states.get(entity_id))
                        else None
                    )
                    for entity_id in button.entities
                },
            }
            for button in controller.buttons
            if (settings := settings_for_button(entry.options, button))
        ],
        "runtime": controller.diagnostics(),
        "issues": [
            issue_id
            for issue_id in (
                automation_issue_id(entry.entry_id),
                source_issue_id(entry.entry_id),
            )
            if issues.async_get_issue(DOMAIN, issue_id) is not None
        ],
    }
