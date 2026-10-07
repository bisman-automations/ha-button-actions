# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/bisman-automations/ha-button-actions/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/bisman-automations/ha-button-actions/releases/tag/v1.0.0
