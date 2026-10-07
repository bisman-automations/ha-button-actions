"""Fix flows for Button Actions issues."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult


class TurnOffAutomationFlow(RepairsFlow):
    """Turn off the blueprint automation a remote replaced."""

    def __init__(self, automation: str) -> None:
        """Initialize."""
        self._automation = automation

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start with the confirmation step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm, then turn the automation off."""
        if user_input is not None:
            await self.hass.services.async_call(
                "automation",
                "turn_off",
                {"entity_id": self._automation, "stop_actions": False},
                blocking=True,
            )
            return self.async_create_entry(data={})
        state = self.hass.states.get(self._automation)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "automation": state.name if state else self._automation
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for an issue."""
    return TurnOffAutomationFlow(str((data or {})["automation"]))
