# Lefant for Home Assistant

Home Assistant integration for Lefant robot vacuums built on Tuya. It talks to the robot over your LAN. An optional Tuya cloud project adds the map of the last cleaning.

This is an independent project. It is not made, endorsed or supported by Lefant or Tuya. See [Legal](#legal).

## Features

- Local push over the Tuya LAN protocol (3.3, 3.4, 3.5). The robot pushes every change; commands go straight to it.
- Vacuum entity: start, pause, stop, return to dock, locate, suction level and room cleaning, also through Home Assistant's **Clean area** action.
- Sensors for battery, status, faults, the running cleaning and the base station (clean water, dirty water, dust bag).
- Wear counters for main brush, side brush, filter and mop pads. The robot does not report wear, so Home Assistant counts the cleaning minutes of each part. A button resets a counter when you replace the part.
- With the cloud project: an image of the last cleaning map with rooms and route, and sensors for the last cleaning.
- A dashboard card: map with rooms to pick, cleaning controls, no-go areas, barriers, and room split, merge and rename. It follows the Home Assistant language: Italian or English.
- Experimental: the same card for Roborock robots set up with Home Assistant's Roborock integration.

## Status

Beta. Tested on a **Lefant M5 Max** with Home Assistant 2026.10.

Other Lefant robots on Tuya may work in part. Each model can use different data points (DPs), and this integration knows the M5 Max set only. Reports for other models are welcome in the issues.

## Requirements

- Home Assistant 2026.10 or newer.
- The robot on a network Home Assistant can reach, with TCP port 6668 open between them.
- The robot's **device ID** and **local key**. The [tinytuya setup wizard](https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys) reads them from a Tuya IoT Platform cloud project linked to the Smart Life account that holds the robot.
- For the map only: the **Access ID** and **Access Secret** of that cloud project, with the Sweeping Robot Open Service authorized.

## Install

### HACS

1. In HACS, open the menu, pick **Custom repositories**, add `https://github.com/Paol0B/ha-lefant` with type **Integration**.
2. Install **Lefant** and restart Home Assistant.

### Manual

Copy `custom_components/lefant` into the `custom_components` folder of your Home Assistant configuration, then restart Home Assistant.

## Setup

Go to **Settings > Devices & services > Add integration > Lefant** and fill in:

| Field | Value |
|---|---|
| Host | IP address or host name of the robot |
| Device ID | from the tinytuya wizard |
| Local key | from the tinytuya wizard |
| Tuya protocol version | 3.5 for the M5 Max |
| Cloud Access ID, Access Secret | optional, for the map |
| Cloud data center | the region of your cloud project |

The flow checks the local connection, and the cloud credentials when given. Without cloud credentials the integration makes no cloud request at all.

To rename rooms, open the integration's **Configure** dialog. Names stay in Home Assistant; the robot keeps its own.

## Dashboard card

The integration serves the card, but Home Assistant needs it as a dashboard resource:

1. **Settings > Dashboards**, menu **Resources** (it needs advanced mode in your user profile).
2. Add `/lefant_static/lefant-vacuum-card.js?v=0.6.0` as **JavaScript module**.
3. Add the card to a dashboard:

```yaml
type: custom:lefant-vacuum-card
entity: vacuum.lefant_m5_max
title: Robot # optional
```

Browsers keep the card in cache. After an update, change the `?v=` value of the resource to the new version.

For a Roborock robot, use `type: custom:roborock-vacuum-card` with the Roborock vacuum entity. This part reads data that Home Assistant's Roborock integration keeps in memory, not a public interface. A Home Assistant update can break it.

## Entities

| Platform | Entities |
|---|---|
| vacuum | the robot |
| sensor | battery, status, error, alarm code, cleaning time, cleaning area, main brush / side brush / filter / mop pads usage, dust bag emptyings |
| sensor (cloud) | last cleaning, last cleaning duration, last cleaning area |
| binary_sensor | mop attached, docked, problem, clean water tank, dirty water tank, dust bag |
| select | water level |
| switch | carpet boost, carpet detection, resume after charging |
| button | main brush, side brush, filter, mop pads, dust bag replaced |
| image (cloud) | last cleaning map |

The vacuum attribute `cleaning_job` describes the running cleaning: whole house or rooms, start time and mop washes.

## Commands

Clean rooms by name or ID, more than one pass:

```yaml
action: vacuum.send_command
target:
  entity_id: vacuum.lefant_m5_max
data:
  command: clean_rooms
  params:
    rooms: [Kitchen, 3]
    repeats: 2
```

`set_dp` writes one raw data point, for DPs the integration does not cover. A wrong value can change robot settings, so use it only if you know the DP.

```yaml
action: vacuum.send_command
target:
  entity_id: vacuum.lefant_m5_max
data:
  command: set_dp
  params:
    dp: 172
    value: true
```

### Example: full dust bag

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.lefant_m5_max_dust_bag
    to: "on"
actions:
  - action: notify.notify
    data:
      message: The robot's dust bag is full.
```

## Known limits

- The robot does not report its live position or the room it is in.
- The map shows the last finished cleaning. The robot sends it to the Tuya cloud a few minutes after docking, and the integration fetches it then.
- After a room split or merge, the map shows a preview until the next cleaning brings the robot's own map.
- Map edits work only while the robot is not cleaning.
- Re-pairing the robot gives it a new local key. Remove the integration entry and add it again.
- Faults outside the seven known bits show as **Other**.

## Troubleshooting

- **Cannot connect**: check host, local key and protocol version, and that port 6668 is reachable. Close other tools that keep a local connection to the robot.
- **No map**: the map needs a cloud project and one finished cleaning. Check the Tuya console: the cloud project must be linked to the app account and its API services enabled.

Debug logs:

```yaml
logger:
  logs:
    custom_components.lefant: debug
    tinytuya: debug
```

Debug logs can hold the device ID and the local key. Remove them before you share a log.

## Remove

1. Delete the Lefant entry in **Settings > Devices & services**.
2. Remove the card resource and the cards that use it.
3. Uninstall the integration in HACS, or delete `custom_components/lefant`, and restart Home Assistant.

## Security

- The local key gives full control of the robot. Keep it, and the cloud Access Secret, private. Home Assistant stores both in its configuration, like any integration's credentials.
- Map edits through the card need a Home Assistant administrator.
- `vacuum.send_command` is open to every Home Assistant user, like any other action. `set_dp` included.

Report a vulnerability privately, as [SECURITY.md](SECURITY.md) says. Do not open a public issue for it.

## Development

The tests need Python 3.14.2 or newer, as Home Assistant 2026.10 does, and Node.js 18 or newer for the card.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
node --test tests/frontend/*.test.mjs
```

CI runs the tests, hassfest and the HACS check.

Contributions are welcome under the project's license (Apache-2.0, section 5). Sign off each commit (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/). Never add code, firmware, keys or files copied from the vendor's apps or devices.

## Credits

- [tinytuya](https://github.com/jasonacox/tinytuya) (MIT) handles the Tuya LAN protocol. Home Assistant installs it.
- The Roborock map reader follows the block layout documented by [vacuum-map-parser-roborock](https://github.com/PiotrMachowski/Python-package-vacuum-map-parser-roborock) (Apache-2.0).

## Legal

### Trademarks

Lefant, Tuya, Smart Life, Roborock, Home Assistant and the other product names here are trademarks of their owners. They appear only to say which devices and software this project works with. None of those owners make, endorse or support it. The repository uses none of their logos; the integration icon is an original drawing.

### Interoperability

This is an independently written program. Its only purpose is to let a robot you own work with Home Assistant.

- It holds no code, firmware, keys or files from Lefant or Tuya.
- The data points, commands and map format come from observing the robot's own messages and cloud records, and from testing on the robot. No app or firmware was decompiled.
- It uses the robot's local key and your own Tuya cloud project. It does not bypass any access control or copy protection.

EU law lets the user of a program observe, study and test how it works ([Directive 2009/24/EC](https://eur-lex.europa.eu/eli/dir/2009/24/oj), art. 5(3)). US law has a similar exemption for interoperability ([17 U.S.C. § 1201(f)](https://www.law.cornell.edu/uscode/text/17/1201)).

If you hold rights in something here and think it should not be published, open an issue or write to paolobertinetti200f4@proton.me. Every request gets a review.

### Privacy

- Without cloud credentials, the integration talks only to the robot.
- With them, it reads the robot's state and cleaning records from your own Tuya cloud project. A cleaning record holds the floor plan of your home. The robot uploads it to the Tuya cloud on its own, whether or not you use this integration.
- The integration sends nothing to the author. What Home Assistant stores, for example the map image in its history, depends on your setup.

### No warranty

The software comes as is, without warranty. The license excludes liability as far as the law allows (sections 7 and 8 of [LICENSE](LICENSE)). No-go areas and barriers are not a safety feature: do not rely on them to keep the robot away from stairs, water, pets or children. A firmware update can break the integration at any time.

This is free and open-source software, written and shared without payment and outside any commercial activity, as the EU [Cyber Resilience Act](https://eur-lex.europa.eu/eli/reg/2024/2847/oj) and [Product Liability Directive](https://eur-lex.europa.eu/eli/dir/2024/2853/oj) use the term.

## License

Copyright 2026 Paolo Bertinetti. Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
