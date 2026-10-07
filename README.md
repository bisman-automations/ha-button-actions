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
- **Import your blueprint automations:** convert automations made with the *Lutron Pico Universal Actions (Event Entities)* blueprint one at a time or all at once. Buttons, actions and timing carry over, the old automations are turned off for you, and remotes can read presses straight from Lutron.
- **Device triggers:** use "Living Room Remote: Middle button double pressed" in your own automations when you need one.
- **Repairs:** you're told if an imported blueprint automation gets turned back on (presses would run twice), or if a button's event entity or Pico disappears.
- **Gesture event entities:** each button also gets an event entity that reports `short_press`, `double_press`, `long_press` and `long_release`, so presses show up in the logbook and history.
- **Lutron Caséta Picos built in:** pick a Pico from the core Lutron Caséta integration and its buttons are set up for you. No extra integration needed.
- **Works with any press/release event entity** too, so Zigbee, ESPHome and other remotes work as well.

## Requirements

- Home Assistant 2025.4 or newer. The integration icon shows in the UI on 2026.3 and newer.
- One of:
  - A Pico paired with the core **Lutron Caséta** integration, or
  - Event entities that report a press and a release for each button, such as those from [lutron-caseta-events](https://github.com/jharris4/lutron-caseta-events), Zigbee or ESPHome.

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/bisman-automations/ha-button-actions` as an **Integration**.
3. Install **Button Actions** and restart Home Assistant.

### Manual

Copy `custom_components/button_actions` into your `config/custom_components` folder and restart Home Assistant.

## Setup

Go to **Settings → Devices & services → Add integration → Button Actions**. You can add a remote three ways.

### Lutron Caséta Pico

Pick the Pico. Its buttons are added automatically, and presses are read straight from the Lutron Caséta integration. Then use the ✎ next to each button to choose what it does.

### Import from a blueprint automation

Pick an automation made with the Pico blueprint. Its button entities, every short, double and long-press action, and its timing are copied over. Leave **Turn off the original automation** checked so presses don't run twice. Nothing is deleted.

If every button belongs to a Pico in the Lutron Caséta integration, you're asked whether to read presses straight from Lutron. That's recommended, since the remote then doesn't need its event entities.

### Import all Pico blueprint automations

Lists every Pico blueprint automation that hasn't been imported yet, with all of them selected. Each one becomes its own remote. Turn on **Read presses from Lutron when possible** to set up Pico-backed remotes wherever that works.

### Set up a remote from event entities

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
| ✎ next to a button | Set its short press, double press, long press and release-after-long-press actions, whether the long press repeats while held, whether to detect every gesture, and which event entities feed it. |
| ⋮ next to a button | Delete that button. Its gesture entity is removed too. |
| ⚙ on the remote | Click timing for the whole remote: double-press window, hold time and repeat interval. |
| ⋮ on the remote → **Add button** | Add a button you skipped during setup. |
| ⋮ on the remote → **Reconfigure** | Rename the remote, change its press and release event types, or switch it to a Lutron Caséta Pico. |

### Switching a remote to core Lutron

Remotes imported from the blueprint use event entities from lutron-caseta-events. To read presses straight from the Lutron Caséta integration instead, open **Reconfigure** on the remote and pick its Pico. If the event entities belong to the Pico's device, it's already filled in. Every button keeps its actions, and once all your remotes are switched you no longer need lutron-caseta-events.

Actions get these variables for templates: `remote` (the remote's name), `button` (`on`, `raise`, `stop`, `lower`, `off`, `button_1` … `button_4`) and `gesture`.

### Using a button in your own automations

Each remote is a device with triggers for every button and gesture, such as *"Middle button" double pressed*. Pick the remote as the device in the automation editor's trigger list.

A button only waits for double and long presses when it has an action for them, so its short presses stay instant. To use a double or long press only from an automation, turn on **Detect every gesture** on that button. Its short presses then wait briefly for a possible second press.

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

- Gesture event entities and device triggers only report gestures the button is watching for. A button with no double-press action never reports `double_press` unless **Detect every gesture** is on.
- If a release event goes missing, the next press resets the button, and repeat stops after 30 seconds, so a button can't get stuck.

## License

MIT
