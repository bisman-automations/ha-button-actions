"""Repairs issues for a remote.

- automation_enabled: the blueprint automation a remote was imported from is
  on again, so every press runs twice. Fixable: turns the automation off.
- entities_missing / pico_missing: a button's event entity, or the remote's
  Pico, no longer exists, so those buttons can't fire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_DEVICE_ID, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started

from .const import CONF_SOURCE_AUTOMATION, DOMAIN, SOURCE_LUTRON

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .controller import ButtonActionsController


def automation_issue_id(entry_id: str) -> str:
    """Issue id for a re-enabled source automation."""
    return f"automation_enabled_{entry_id}"


def source_issue_id(entry_id: str) -> str:
    """Issue id for a missing event entity or Pico."""
    return f"source_missing_{entry_id}"


@callback
def async_delete_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove every issue for a remote."""
    ir.async_delete_issue(hass, DOMAIN, automation_issue_id(entry_id))
    ir.async_delete_issue(hass, DOMAIN, source_issue_id(entry_id))


def find_source_automation(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the blueprint automation this remote replaced, if known.

    Remotes imported since 1.3.0 store it. Older imports took the
    automation's name as their title, so match on that for those.
    """
    if automation := entry.data.get(CONF_SOURCE_AUTOMATION):
        return automation

    from homeassistant.components.automation import DATA_COMPONENT

    if (component := hass.data.get(DATA_COMPONENT)) is None:
        return None
    for entity in component.entities:
        state = hass.states.get(entity.entity_id)
        if (
            state is not None
            and state.name == entry.title
            and entity.referenced_blueprint is not None
        ):
            return entity.entity_id
    return None


@callback
def async_track_issues(
    hass: HomeAssistant, entry: ConfigEntry, controller: ButtonActionsController
) -> None:
    """Raise and clear this remote's issues as things change."""
    # -- source automation ----------------------------------------------------
    if automation := find_source_automation(hass, entry):

        @callback
        def _check_automation(_event: Event | None = None) -> None:
            state = hass.states.get(automation)
            if state is not None and state.state == STATE_ON:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    automation_issue_id(entry.entry_id),
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="automation_enabled",
                    translation_placeholders={
                        "remote": entry.title,
                        "automation": state.name,
                    },
                    data={"automation": automation},
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, automation_issue_id(entry.entry_id))

        entry.async_on_unload(
            async_track_state_change_event(hass, [automation], _check_automation)
        )
        _check_automation()

    # -- missing sources ------------------------------------------------------
    @callback
    def _check_sources(_event: Any = None) -> None:
        if not hass.is_running:
            return
        issue_id = source_issue_id(entry.entry_id)
        placeholders = {"remote": entry.title}
        if controller.source == SOURCE_LUTRON:
            device_id = entry.data.get(CONF_DEVICE_ID)
            missing = dr.async_get(hass).async_get(device_id) is None
            key = "pico_missing"
        else:
            registry = er.async_get(hass)
            gone = [
                entity_id
                for button in controller.buttons
                for entity_id in button.entities
                if registry.async_get(entity_id) is None
                and hass.states.get(entity_id) is None
            ]
            missing = bool(gone)
            key = "entities_missing"
            placeholders["entities"] = ", ".join(gone)
        if missing:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders=placeholders,
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    # Wait until startup is done so entities from slower integrations exist.
    entry.async_on_unload(async_at_started(hass, _check_sources))
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _check_sources)
    )
    entry.async_on_unload(
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _check_sources)
    )
