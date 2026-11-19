"""Download diagnostics for a remote."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_CODE,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_TOKEN,
    CONF_USERNAME,
    CONF_WEBHOOK_ID,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .controller import remote_capabilities, settings_for_button
from .events import resolve_role
from .issues import automation_issue_id, source_issue_id

if TYPE_CHECKING:
    from . import ButtonActionsConfigEntry

# Keys whose values are replaced with "**REDACTED**" anywhere in the remote's
# data, its options and its buttons' actions, at any depth. A button's actions
# are ordinary Home Assistant actions, so they can carry an alarm or lock
# code, a PIN, a password, an API key or token, or a webhook id (for example
# ``alarm_control_panel.alarm_disarm`` with ``data: {code: ...}``). The
# remote's own settings hold nothing secret today, but options are redacted
# too so a future or legacy option (1.0.0 kept actions in the options) can't
# leak into a shared diagnostics file. The keys only, never the structure:
# what a button does stays readable.
TO_REDACT: Final = {
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_CODE,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_TOKEN,
    CONF_USERNAME,
    CONF_WEBHOOK_ID,
    "secret",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ButtonActionsConfigEntry
) -> dict[str, Any]:
    """Everything needed to understand why a remote behaves the way it does.

    Secrets in the remote's data, options and actions are redacted (see
    ``TO_REDACT``), so the file is safe to attach to a GitHub issue.
    """
    controller = entry.runtime_data
    issues = ir.async_get(hass)
    return {
        "remote": {
            "title": entry.title,
            "version": f"{entry.version}.{entry.minor_version}",
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "buttons": [
            {
                "button": button.slot,
                "entities": button.entities,
                "actions": async_redact_data(button.actions, TO_REDACT),
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
            if (
                settings := settings_for_button(
                    entry.options, button, *remote_capabilities(entry.data)
                )
            )
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
