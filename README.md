<p align="center">
  <img src="https://raw.githubusercontent.com/bisman-automations/ha-button-actions/main/custom_components/button_actions/brand/icon@2x.png" alt="Button Actions icon" width="128">
</p>

# Button Actions

Map short, double and long presses on Lutron Pico and other button remotes to any Home Assistant action, configured entirely in the UI. No automations needed.

## Why

The usual way to get click, double-click and hold out of a Pico is a blueprint automation. That works, but:

- **Buttons block each other.** One automation handles every button, so while it waits out a hold on one button, presses on another can be dropped or queued.
- **Timing is loose.** Template triggers and `wait_for_trigger` add latency, which matters inside a 250 ms double-click window.
- **Short presses always wait.** The automation can't know you never set a double-click action, so every short press waits for one.
- **Hold-to-dim is awkward.** Repeating an action while a button is held isn't something a blueprint does well.

Button Actions runs a small state machine per button inside Home Assistant, so every button is independent, timing is tight, and each remote is just a device you configure.

## Features

- **Gestures per button:** short press, double press, long press, and release after a long press.
- **Any action:** each gesture uses the same action editor as scripts and automations. Target areas, devices or entities, use any service, add delays, conditions, templates.
- **Hold to repeat:** turn on repeat for a button and its long-press action keeps running while held. Pair it with `brightness_step_pct` or `volume_up` for hold-to-dim and hold-to-raise.
- **No waiting when you don't need it:** a button with no double-press action fires its short press the instant you let go. A button with no long-press action treats a long press as a short one.
- **Import your blueprint automations:** convert automations made with the *Lutron Pico Universal Actions (Event Entities)* blueprint in one step. Buttons, actions and timing carry over, and the old automation is turned off for you.
- **Gesture event entities:** each button also gets an event entity that reports `short_press`, `double_press`, `long_press` and `long_release`, so presses show up in the logbook and history.
- **Works with any press/release event entity**, not just Lutron.

## Requirements

- Home Assistant 2025.4 or newer. The integration icon shows in the UI on 2026.3 and newer.
- Event entities that report a press and a release for each button. For Lutron Caséta, [lutron-caseta-events](https://github.com/jharris4/lutron-caseta-events) provides these.

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/bisman-automations/ha-button-actions` as an **Integration**.
3. Install **Button Actions** and restart Home Assistant.

### Manual

Copy `custom_components/button_actions` into your `config/custom_components` folder and restart Home Assistant.

## Setup

Go to **Settings → Devices & services → Add integration → Button Actions**. You can add a remote two ways.

### Import from a blueprint automation

Pick an automation made with the Pico blueprint. Its button entities, every short, double and long-press action, and its timing are copied over. Leave **Turn off the original automation** checked so presses don't run twice. Nothing is deleted.

Repeat for each remote.

### Set up a new remote

Give the remote a name and pick the event entity for each button it has. Leave the rest empty. You can pick more than one entity for a button so several remotes share the same actions.

The press and release event types default to `press` and `release`, which is what Lutron uses. Change them if your remote reports something else.

## Configuring buttons

Each remote lists its buttons right under it on the Button Actions integration page:

```
Living Room Remote                ⚙  ⋮
  Living Room Remote  (device)       ⋮
  On button                       ✎  ⋮
  Raise button                    ✎  ⋮
  Middle button                   ✎  ⋮
  Lower button                    ✎  ⋮
  Off button                      ✎  ⋮
```

| Control | What it does |
| --- | --- |
| ✎ next to a button | Set its short press, double press, long press and release-after-long-press actions, whether the long press repeats while held, and which event entities feed it. |
| ⋮ next to a button | Delete that button. Its gesture entity is removed too. |
| ⚙ on the remote | Click timing for the whole remote: double-press window, hold time and repeat interval. |
| ⋮ on the remote → **Add button** | Add a button you skipped during setup. |

Actions get these variables for templates: `remote` (the remote's name), `button` (`on`, `raise`, `stop`, `lower`, `off`, `button_1` … `button_4`) and `gesture`.

### Hold-to-dim example

On the **Raise** button, set the long-press action to:

```yaml
action: light.turn_on
target:
  area_id: living_room
data:
  brightness_step_pct: 10
```

Turn on **Repeat long press while held**. Holding Raise now steps the lights up every repeat interval until you let go. Do the same on **Lower** with `-10`.

## Timing defaults

| Setting | New remote | Imported remote |
| --- | --- | --- |
| Double-press window | 300 ms | the blueprint's value, or 250 ms |
| Hold time | 600 ms | the blueprint's value, or 1000 ms |
| Repeat interval | 400 ms | 400 ms |

Imported remotes keep the blueprint's timing so they feel the same as before. Lowering the hold time to around 600 ms makes long presses noticeably snappier.

## Upgrading from 1.0.0

Remotes set up with 1.0.0 convert automatically the first time Home Assistant starts with 1.1.0. Each button becomes its own entry under the remote with its actions intact, and entity IDs don't change.

## Notes

- Gesture event entities only report gestures the remote is watching for. A button with no double-press action never reports `double_press`, because it doesn't wait for one.
- If a release event goes missing, the next press resets the button, and repeat stops after 30 seconds, so a button can't get stuck.

## License

MIT
