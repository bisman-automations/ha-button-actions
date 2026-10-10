# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.7.3] - 2026-10-09

### Added

- **Pick a device** finds buttons on a device connected via a hub, such as the "Buttons" device a SwitchBot Hub 2 adds over Matter. Pick the hub or the buttons device; the remote is linked to the device the buttons are on.

### Changed

- A remote linked to a device has no gesture event entities: the device shows its own button events. Existing ones, including those 1.7.2 disabled, are removed. Device triggers and actions work as before. Remotes that aren't linked keep theirs.

## [1.7.2] - 2026-10-09

### Changed

- A remote linked to a device no longer adds a second set of button events to that device's page. Its gesture event entities are created disabled, and those of existing linked remotes are disabled once. Device triggers and actions work as before; enable the entities to see gestures in the logbook and history. If a remote stops being linked, they're enabled again.
- Gesture event entities no longer poll.

### Fixed

- Reconfigure no longer triggers Home Assistant 2026.10's warning about reloading an entry that already reloads itself, which stops working in 2026.12.

## [1.7.1] - 2026-10-09

### Fixed

- Remotes weren't linked to their Pico or button device on Home Assistant 2026.8 and newer, where a device can only belong to one integration. Gesture entities are now shown on the linked device on every supported version.
- **Reconfigure** on a remote that isn't a Pico only let you pick Lutron Caséta devices. It now lets you link any device; picking a Pico still switches the remote to read presses from Lutron.
- Avoided Home Assistant 2026.8+ deprecation warnings about device lookups.

### Changed

- Every remote keeps its own device again, shown as connected via its Pico or button device. Its device triggers are listed there, so automations made before 1.7.0 keep working. Triggers picked on a linked device with 1.7.0 still work.
- Requires Home Assistant 2025.8 or newer.

## [1.7.0] - 2026-10-09

### Added

- **Pick a device**: choose a Lutron Pico, a hub, a Matter switch or a Zigbee remote, and its buttons are found and set up for you. The number of buttons and whether long press works are filled in from what the device reports.
- Remotes are linked to the device their buttons belong to. Their gesture entities and device triggers show up on that device's page, next to the device's own integration, instead of on a separate "Button remote" device.
- Several remotes can share one device; each keeps its own device triggers.

### Changed

- Existing remotes move onto their Pico or button device automatically the first time Home Assistant starts with 1.7.0. Entity IDs and automations using their triggers keep working, and the old standalone device is removed. Remotes whose buttons come from more than one device keep a device of their own.
- The setup menu's separate "Lutron Caséta Pico" option is now part of **Pick a device**. "Another remote or button device" is now **Set up a remote by hand**.

## [1.6.0] - 2026-10-08

### Added

- Set up any remote by saying how many buttons it has (1–12) and whether it supports double press and long press. Its buttons are named Button 1, Button 2 and so on.
- Gestures a remote doesn't support aren't offered in its button forms, aren't timed, and aren't listed as device triggers or gesture entity event types. Without double press, short presses always fire instantly; without long press, holding a button counts as a short press.
- **Reconfigure** can turn double and long press support on or off. Actions for a gesture that's turned off are kept, in case it's turned back on.
- **Add button** on a numbered remote offers the next button numbers.
- Remotes with 10 or more buttons number them 01, 02… so they stay in order.

### Changed

- "Set up a remote from event entities" is now "Another remote or button device", and uses the new numbered setup. Lutron Pico remotes keep their named buttons through the Pico, import and duplicate options.
- Existing remotes are unchanged: they keep their buttons and support every gesture.

## [1.5.0] - 2026-10-08

### Added

- Support for button devices beyond Lutron, such as Matter switches and hub buttons (for example a SwitchBot Hub 2), Zigbee and ESPHome. Every event type a device sends is recognized automatically:
  - Press and release events (Lutron `press`/`release`, Matter `initial_press`/`short_release`/`long_release`): short, double and long presses are timed by Button Actions.
  - Press-only devices (Matter `initial_press` without release): each press counts as a full press, and double presses work.
  - Devices that detect gestures themselves (Matter `multi_press_1`/`multi_press_2`/`long_press`, Zigbee `single`/`double`/`hold`): their gestures are used as they are, including hold-to-repeat.
- **Reconfigure** on an event-entity remote now lists every event type its buttons send, with what each one means, so you can correct a device that uses unusual names.
- Diagnostics show the role of every event type for each button.

### Changed

- Setting up a remote from event entities no longer asks for press and release event names.
- Existing remotes keep working as before; their press and release names carry over.

## [1.4.1] - 2026-10-07

### Changed

- Buttons are numbered in the order they sit on the remote, top to bottom, so Home Assistant's alphabetical lists match the remote. Gesture entities read "1 · On", "2 · Raise", "3 · Middle", "4 · Lower", "5 · Off", and buttons on the integration page read "1 · On button" and so on. Off is always last, including on scene Picos.
- Existing remotes are renumbered automatically. Entity IDs don't change, and entities or buttons you renamed yourself keep your names.

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

[Unreleased]: https://github.com/bisman-automations/ha-button-actions/compare/v1.7.3...HEAD
[1.7.3]: https://github.com/bisman-automations/ha-button-actions/compare/v1.7.2...v1.7.3
[1.7.2]: https://github.com/bisman-automations/ha-button-actions/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/bisman-automations/ha-button-actions/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/bisman-automations/ha-button-actions/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/bisman-automations/ha-button-actions/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/bisman-automations/ha-button-actions/releases/tag/v1.0.0
