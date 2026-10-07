# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-10-07

### Added

- **Duplicate an existing remote** from setup: copies every button's actions, repeat and detection settings and the click timing, with optional find-and-replace across all copied actions. The copy can read presses from a Lutron Caséta Pico or its own event entities.
- **Download diagnostics** for a remote: its config, each button's detection settings and source entity states, live gesture state, and any open Repairs issues.
- Debug logging of every source state change a remote receives, to help track down missed presses.
- Screenshots in the README.

### Fixed

- The first press on a button that had never been pressed before was ignored. A source entity that has never fired sits at `unknown`, and the change from `unknown` was mistaken for a restore after restart.

## [1.3.0] - 2026-10-07

### Added

- Device triggers for every button and gesture, such as *"Middle button" double pressed*, for use in your own automations.
- **Detect every gesture** option on a button, so double and long presses are reported to device triggers and the gesture entity even without an action for them.
- Repairs: a fixable issue when the blueprint automation a remote was imported from is turned back on, and a warning when a button's event entity or a remote's Pico no longer exists. Issues clear by themselves once resolved.
- **Import all Pico blueprint automations** in one step, optionally reading presses from Lutron wherever possible.
- Importing a single blueprint automation offers to read presses straight from Lutron when every button belongs to one Pico.

## [1.2.0] - 2026-10-07

### Added

- Set up a remote straight from a Pico in the core Lutron Caséta integration. Its buttons are added automatically and presses are read from Lutron's own button events, so lutron-caseta-events is no longer needed.
- **Reconfigure** on a remote to rename it, change its press and release event types, or switch an event-entity remote to a Lutron Caséta Pico while keeping every button's actions. Pico remotes can also be pointed at a replacement Pico.
- Setup and Reconfigure refuse a Pico that already drives another remote, so presses can't run twice.

### Changed

- **Add button** on a Pico remote only offers buttons that Pico has, and button edit forms on Pico remotes no longer ask for event entities.

## [1.1.0] - 2026-10-07

### Changed

- Each button is now listed under its remote on the integration page, with its own edit button for its actions and event entities. This replaces the old Configure menu.
- The gear on a remote now opens just the click timing settings.
- Button Actions is now a device integration instead of a helper. Remotes appear as regular integration entries and are added from **Add integration**.
- Requires Home Assistant 2025.4 or newer.

### Added

- **Add button** on a remote, for buttons skipped during setup.
- Deleting a button also removes its gesture event entity.

### Migration

- Remotes set up with 1.0.0 convert automatically on startup. Actions, repeat settings and entity IDs are kept.

## [1.0.0] - 2026-10-06

First release.

### Added

- Per-button gesture detection: short press, double press, long press, and release after a long press. Each button runs its own state machine, so presses on one button never block another.
- Each gesture runs a full Home Assistant action sequence, edited in the options flow with the same action editor as scripts and automations. Actions get `remote`, `button` and `gesture` variables for templates.
- Hold to repeat: re-run a button's long-press action at a set interval while it's held, for hold-to-dim and similar. Repeat stops after 30 seconds if a release never arrives.
- Short presses fire instantly on buttons with no double-press action, and a long press counts as a short press on buttons with no long-press action.
- Import from *Lutron Pico Universal Actions (Event Entities)* blueprint automations, carrying over button entities, actions and timing, and optionally turning off the original automation.
- Manual setup for any remote whose event entities report a press and a release, with configurable press and release event types.
- Options to adjust the double-press window, hold time and repeat interval, and to change which event entities feed each button.
- An event entity per button that reports `short_press`, `double_press`, `long_press` and `long_release`.
- Integration icon, shown in the Home Assistant UI on 2026.3 and newer.
- HACS support, plus CI running hassfest, HACS validation, ruff and tests.

[Unreleased]: https://github.com/bisman-automations/ha-button-actions/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/bisman-automations/ha-button-actions/releases/tag/v1.0.0
