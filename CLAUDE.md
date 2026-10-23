# Button Actions: working notes

Home Assistant custom integration (`custom_components/button_actions`, domain
`button_actions`), installed through HACS. It maps short, double and long
presses on Lutron Picos and other button devices to actions, configured in the
UI, so remotes need no automations.

## Layout

- `__init__.py`: entry setup, migrations (entry `VERSION 1`, `MINOR_VERSION` in
  `config_flow.py`), the remote's own service device, and registering the
  sidebar panel once in `async_setup`.
- `config_flow.py`: user flow (menu: pick a device, import blueprint, import
  all, duplicate, by hand), reconfigure, options (timing) and the `button`
  subentry flow. One subentry per physical button.
- `controller.py`: per-remote runtime; listens to event entities or core
  `lutron_caseta_button_event`, runs actions, fires `button_actions_gesture`.
- `gesture.py`: pure state machine (no HA imports); unit tested with a fake clock.
- `events.py`: maps a device's event types to roles (press, release, click,
  single, double, hold, ignore).
- `device_trigger.py`, `event.py`, `issues.py`/`repairs.py`, `diagnostics.py`,
  `lutron.py`. Blueprint import lives in `config_flow.py`.
- `panel.py` + `frontend/button-actions-panel.js`: admin-only sidebar dashboard.
  Read-only summary over websocket (`button_actions/panel/config`, never
  returns action bodies), live updates via `button_actions/panel/subscribe`;
  all edits go through HA's existing config/options/subentry flow REST APIs.
- `strings.json` and `translations/en.json` must stay identical.

## Home Assistant compatibility

Minimum is in `hacs.json` (currently 2025.8). Code must work from that version
through the current release. Things that changed and bit us:

- 2026.8+: a device belongs to one config entry and subentry, identifiers are
  unique per config entry, `async_get_device`, `device.config_entries`,
  `add/remove_config_entry_id` and `async_device_info_to_link_from_device_id`
  are deprecated (the last returns None). Use `own_device()` /
  `device_belongs_to()` in `controller.py`, which branch on
  `hasattr(registry, "async_get_device_by_identifier")` /
  `hasattr(device, "config_entry_id")`.
- Never attach entities to another integration's device with `device_info`;
  set `entity.device_entry` (supported since 2025.8).
- A remote linked to a physical device has no gesture event entities. Its own
  service device shares the linked device's identifiers on 2026.8+ (shows under
  "Linked devices") and uses `via_device_id` on older versions.
- Reconfigure: use `async_update_and_abort` when the entry is loaded (the
  update listener reloads it); 2026.10 warns about reloading twice.
- Don't iterate `registry.devices.values()`; it's deprecated on 2026.10.

## Checks before every commit

```sh
ruff check custom_components tests
ruff format --check custom_components tests
pytest -q                                  # against the pinned HA
node --test tests/test_panel_frontend.mjs  # dashboard
```

Run pytest against both an older HA (e.g. 2026.2, Python 3.13) and the newest
release (Python 3.14 via `uv venv -p 3.14`, `uv pip install homeassistant==X
pytest-homeassistant-custom-component`). Deprecation calls raise in tests on
newer HA, which is how the 2026.8+ issues above were found. Tests that need a
behaviour only one version has are skipped with `pytest.mark.skipif` on a
`hasattr` check.

## Releasing

- Work on a branch and open a PR to `main`; don't push to `main` directly.
- Commits are authored as Donavan Becker <donavan.becker@icloud.com> (set
  `git config user.name`/`user.email` in the clone), with Claude credited by a
  `Co-Authored-By` trailer. HACS's default-repository check requires the
  submitter to have at least a third of the top contributor's commits, so
  commits must not be authored as Claude.
- Every user-visible change bumps `version` in `manifest.json` and adds a
  section to `CHANGELOG.md` (Keep a Changelog; also update the compare links
  at the bottom). The manifest version is what HA and HACS show; 1.9.0 once
  shipped still saying 1.8.0.
- Each push to `main` refreshes a draft GitHub release for the manifest version
  (`.github/workflows/draft-release.yml`); publishing it creates the tag.
- CI (`validate.yml`): hassfest, HACS, ruff, pytest, dashboard tests.

## Docs

- README and screenshots in `docs/images/`. Write for users in plain English.
- Never put the owner's own account details, device serials, MAC addresses or
  addresses in the README or other docs; use placeholders.
