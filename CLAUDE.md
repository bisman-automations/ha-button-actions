# Button Actions: notes for Claude and other coding agents

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

Minimum is in `hacs.json` (currently 2025.11). Code must work from that version
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

## Checks

Run the shared checks at the end of this file. They include the Node tests of
the dashboard (`tests/test_panel_frontend.mjs`) and pytest on both the oldest
supported Home Assistant (`requirements_test_min.txt`, 2025.11 on Python 3.13)
and the newest (`requirements_test.txt`, Python 3.14). Deprecation calls raise
in tests on newer Home Assistant, which is how the 2026.8+ issues above were
found. Tests that need a behaviour only one version has are skipped with
`pytest.mark.skipif` on a `hasattr` check.

## Release notes for this repo

- The manifest version is what Home Assistant and HACS show; 1.9.0 once
  shipped still saying 1.8.0. Bump it in the release commit.
- History was rewritten once (October 2026), so the tags `v1.0.0` to
  `v1.9.1` point at commits that are not on `main`. Their trees match commits
  on `main` (for example `v1.9.1` and `8111e61`), and the shared Draft release
  workflow uses that match as the start of the commit list. Don't move or
  re-create the tags; the next releases are tagged on `main` as usual.

## Docs

- README and screenshots in `docs/images/`. Write for users in plain English.
- Never put the owner's own account details, device serials, MAC addresses or
  addresses in the README or other docs; use placeholders.

<!-- BEGIN bisman-automations shared rules -->
<!-- This block is the same in every bisman-automations repo. Edit it in
     bisman-automations/.github (templates/CLAUDE.shared.md) and copy it to
     every repo; the Validate workflow's "standards" job checks it matches. -->

## Shared rules (every bisman-automations repo)

### Releases

- The version lives in `custom_components/<domain>/manifest.json`. Anything
  else that repeats it is called out in the repo-specific notes below and is
  bumped in the same commit.
- Versions follow [Semantic Versioning](https://semver.org): patch for fixes,
  translations, docs and CI; minor for new features, options or entities;
  major when something users rely on is removed or renamed (entities,
  services, events, options) or setup has to be redone.
- Check what is released before choosing a version:
  `git ls-remote --tags origin | awk -F/ '{print $3}' | sort -V | tail -1`
  (`sort -V`: plain sorting puts `v1.10.0` before `v1.9.0`). Never add
  changes to a released version. If the manifest version has no tag yet,
  add to its CHANGELOG section instead of bumping again.
- Every push to `main` ships as a release. In the same push: bump the
  manifest version, and add a dated `## [X.Y.Z] - YYYY-MM-DD` section to
  `CHANGELOG.md` (Keep a Changelog: Added, Changed, Deprecated, Removed,
  Fixed, Security) with its compare link at the bottom. Small follow-ups can
  collect under `## [Unreleased]` first; move them into the version section
  when you bump.
- Ask Donavan before every push. Push fast-forward only: never force-push,
  rebase or amend anything already pushed, or rewrite history in any other
  way. Rewriting history orphans the release tags (it broke drafting in
  ha-button-actions).
- Pushing to `main` runs **Draft release**, which creates or refreshes a
  draft `vX.Y.Z` with that version's CHANGELOG section as the notes, the
  commits since the last release and `<domain>.zip`. **Donavan publishes
  the draft himself**, and publishing creates the tag. Never create or push
  tags, publish releases, or edit published releases.
- Publishing runs **Release check**: the tag must match the manifest version
  and the CHANGELOG, and be on `main`. If it fails, fix it with a new patch
  release, not by moving the tag.

### Commits

- Author commits as `Donavan Becker <donavan.becker@icloud.com>` (set
  `git config user.name` / `user.email` in the clone). HACS's
  default-repository check needs the submitter to have a fair share of the
  commits. Credit an AI assistant with a `Co-Authored-By:` trailer if you
  like, never as the author.
- Subject lines are plain, imperative and say what changed for the user
  ("Show Pico remotes as unavailable when Lutron isn't running"). No
  `fix:`/`feat:` prefixes. Release commits are "Release X.Y.Z".
- Commit and push only when asked.

### CI (shared workflows)

- `.github/workflows/` holds four thin callers of the reusable workflows in
  [bisman-automations/.github](https://github.com/bisman-automations/.github):
  `test.yml` (lint, frontend, pytest on the oldest supported and the newest
  Home Assistant, plus the upcoming one as information only), `validate.yml`
  (hassfest, HACS, standards), `draft-release.yml` and `release-check.yml`.
  Don't add jobs to the callers. Use the shared workflow's inputs, or change
  the shared workflow so every repo gets the improvement.
- `requirements_test.txt` leaves `pytest-homeassistant-custom-component`
  unpinned (newest Home Assistant) and pins ruff (and mypy where used).
  `requirements_test_min.txt` pins the harness release for the minimum in
  `hacs.json`: the newest harness release of that month. CI fails if they
  drift apart.
- Raising the minimum Home Assistant means changing, together: `hacs.json`,
  `requirements_test_min.txt`, `python-min` in `test.yml` (3.13 up to
  2026.2, 3.14 from 2026.3), the README's Home Assistant badge, and a
  CHANGELOG entry.
- Home Assistant 2026.3 and newer need Python 3.14 (3.14.2+).
- The published hassfest rejects `categories` in `manifest.json` and Pillow
  in `requirements`. Leave both out.
- Dependabot (`.github/dependabot.yml`) proposes action and pinned-tool
  updates weekly. It ignores the test harness on purpose.
- Test and Validate also run every Thursday, the day after Home Assistant's
  betas come out. The **next** test job (newest pre-release harness) is
  information only: when it fails, fix the cause before that release ships.

### Before saying work is done

Run from the repo root, in a Python 3.14 venv with `requirements_test.txt`
installed:

```
ruff check .
ruff format --check .
pytest
```

Also run `node --test tests/*.mjs` when the repo has Node tests, mypy when
the repo-specific notes list it, and the tests in a second venv with
`requirements_test_min.txt` when a change could behave differently on the
oldest supported Home Assistant. The standards check (also in CI) is
`python <path to bisman-automations/.github>/scripts/check_repo.py .`.

### Code and docs

- Support every Home Assistant from the `hacs.json` minimum to the newest
  release. Check for deprecations in the newest release and the beta.
- Keep entity IDs, unique IDs, service names and event names stable. When
  one has to change, migrate it and say so under Changed in the CHANGELOG.
- `strings.json` and `translations/en.json` hold the same keys. Home
  Assistant reads only `translations/`, so change both in the same commit.
- Never put personal details in the repo (README, CHANGELOG, code, tests,
  screenshots): no names, addresses, account or device identifiers, or real
  entity IDs. Use placeholders such as `light.living_room`.
- `README.md` is user documentation with the standard header (badges, HACS
  and "add integration" My buttons) and sections Installation, Setup, ...,
  Troubleshooting, Development, License. Use plain language and show names,
  not entity IDs, wherever the UI does.
<!-- END bisman-automations shared rules -->
