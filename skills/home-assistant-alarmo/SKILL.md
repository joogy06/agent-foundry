---
name: home-assistant-alarmo
description: Alarmo DIY alarm for Home Assistant - arm modes (away, home, night, vacation, custom bypass), exit, entry and trigger times, sensor types and options (always on, arm on close, allow open, trigger when unavailable), codes and users, alarmo.arm force and skip_delay, failed-to-arm events, alarm push alerts, MQTT keypad interface, Zigbee sirens and keypads through Zigbee2MQTT or ZHA, and fail-safe handling of unavailable sensors. Not an EN 50131 or insurance-grade alarm. Use when building, tuning or testing an Alarmo alarm.
---

# Home Assistant Alarmo

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: alarmo-release
    source_url: https://github.com/nielsfaber/alarmo/releases
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Latest v1.10.19 (2026-08-09); HACS install; hacs.json requires HA 2026.5.0+."
  - kind: external_fact
    subject: alarmo-unavailable-default
    source_url: https://github.com/nielsfaber/alarmo/blob/main/custom_components/alarmo/sensors.py
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "With trigger_unavailable off (default), an unavailable sensor neither blocks arming nor triggers; with it on, it blocks arming or triggers while armed."
  - kind: external_fact
    subject: zigbee2mqtt-siren-keypad
    source_url: https://www.zigbee2mqtt.io/devices/SIRZB-110.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "SIRZB-110 driven by warning payload (mode burglar etc., level, duration, strobe) and squawk; KEYZB-110 exposes action, action_code, action_transaction, arm_mode."
  - kind: external_fact
    subject: uk-alarm-certification
    source_url: https://www.nsi.org.uk/specifiers/insurers/
    verified_on: 2026-09-27
    review_by: 2027-09-27
    claim: "Insurers may require NPCC-policy systems from certificated installers (Certificate of Compliance, police URN); design to PD 6662 with EN 50131 grades."
-->

## Overview

Alarmo turns HA sensors into an alarm panel entity (`alarm_control_panel`). It is a good **DIY deterrent and notifier**. Two principles:

1. **It is not a certified alarm.** Say so explicitly (next section).
2. **Fail safe, not fail silent.** By default Alarmo treats an unavailable sensor as safe [V sensors.py]; a dead or jammed sensor then stays quiet. Turn on `trigger_unavailable` for critical sensors and supervise batteries and connectivity.

Evidence labels: **[V]** checked on 2026-09-27 against the cited source or Alarmo source code; **[I]** inferred, re-verify. Current release **v1.10.19** (2026-08-09), installed via HACS, needs HA **2026.5.0+** [V GitHub]. Keypad, siren and automation detail: [references/devices-and-automations.md](references/devices-and-automations.md).

## Not EN 50131 / not insurance-grade (state this to the user)

- Certification is **locale-specific**; ask where the home is. Example, UK: insurers may require an intruder alarm installed and maintained by an NSI or SSAIB certificated company to PD 6662 / EN 50131, often monitored, with a police URN [V nsi.org.uk, ssaib.org]. An HA + Alarmo system has no certificate, no grade and no URN [I].
- EN 50131 grades run 1 (low risk) to 4 (high risk); homes are typically Grade 2 [I, grade definitions not fetched].
- Consequences: do not tell an insurer the home has a "graded" or "professional" alarm on the strength of Alarmo; check the policy wording; treat Alarmo as supplementary.
- HA signalling **supplements, never replaces**, independent smoke/CO alarms and life-safety devices.
- It depends on HA, the host, Zigbee and the internet for remote notification. Add a UPS and an external heartbeat (see `home-assistant`).

## When to use

- Setting up Alarmo modes, sensors, delays, codes and users.
- Arming/disarming automations, notifications, keypads, sirens.
- Deciding what happens when a sensor goes unavailable.

**Not for:** pairing Zigbee devices or channels (`home-assistant-zigbee`); notification payload basics and HA backups (`home-assistant`); voice arming via Google (`home-assistant-google-home`); cameras (`frigate-nvr`).

## Ask before building

Ask one compact question when unknown:
1. **Which modes** the household will use (away only, or home/night too) and which sensors belong to each.
2. **How people arm/disarm**: keypad, phone, NFC tag, presence automation.
3. **What a trigger should do**: siren (indoor/outdoor), lights, critical push to whom.

## Modes and timers

| Mode | Typical sensors | Exit / entry | Notes |
|---|---|---|---|
| `armed_away` | All doors, windows, motion | Exit 60 s, entry 60 s (factory default) [V] | Main mode |
| `armed_home` | Perimeter doors and windows only | Exit 0, entry on main door | People move inside |
| `armed_night` | Perimeter + downstairs motion | Short or none | Bedrooms excluded |
| `armed_vacation` | As away | Longer trigger time | Optional |
| `armed_custom_bypass` | User-chosen | | Optional |

- Each mode has its own `exit_time`, `entry_time`, `trigger_time` [V]. Factory trigger time is 1800 s [V]; `0` means triggered **until disarmed** [V]. Pick a finite trigger time (e.g. 180-600 s) and check local noise rules for sirens [I].
- Entry delay only on the sensors on the entry path (`use_entry_delay`); everything else immediate.

## Sensors

Types: door, window, motion, tamper, environmental, other [V]. Options (UI name / key) [V]:

| Option | Key | Use for |
|---|---|---|
| Use exit delay / entry delay | `use_exit_delay` / `use_entry_delay` | Entry-path door and hall motion only |
| Always on | `always_on` | Tamper (and optionally smoke/leak as an extra signal): trigger even when disarmed |
| Allow open after arming | `allow_open` | A door left open at arming whose closing should not trigger |
| Arm after closing | `arm_on_close` | Front door closes, then arm (5 s debounce) |
| Bypass automatically | `auto_bypass` | Windows left open in `armed_home` |
| **Trigger when unavailable** | `trigger_unavailable` | **All perimeter and critical sensors** |

"Immediate" is a legacy option, migrated to both delays off [V]. Sensor groups require two different sensors to trigger [V]; use for false-alarm-prone motion, never for the only sensor on a door.

## Fail-safe for unavailable sensors

| State | `trigger_unavailable` off (default) | on |
|---|---|---|
| Unavailable at arming | Arms anyway [V] | Arming blocked, `alarmo_failed_to_arm` event [V] |
| Goes unavailable while armed | Nothing happens [V] | Alarm triggers [V] |
| Entity missing from HA | Blocks arming [V] | Blocks arming |

Pattern:
1. `trigger_unavailable: true` on door/window contacts and the siren-side sensors. For motion sensors on flaky links, prefer a **notification** instead of a trigger.
2. Automation on `alarmo_failed_to_arm` → notify with the listed sensors. Offer force-arm (`ALARMO_FORCE_ARM` [V]) only for sensors a human may bypass (e.g. a window left open), **never** for an unavailable perimeter sensor. Alarmo's actionable notifications work only for the master panel in multi-area setups [V README].
3. HA watchdog per sensor: `to: unavailable` for 30-60 min, and battery below 20%, notify even when disarmed (see `home-assistant`).
4. Tamper sensors as `always_on` [V README].
5. Know the detection delay: `unavailable` appears only after the Zigbee stack's availability timeout (Zigbee2MQTT default for battery devices is **25 h** [V z2m device-availability docs]); shorten it for alarm sensors (see `home-assistant-zigbee`). Test twice: force the state (set the entity `unavailable` in Developer tools) for the logic, and pull a battery for the real timeout.

## Codes, users and arming

- Settings: `code_arm_required` (now `code_mode_change_required`), `code_disarm_required`, `code_format` number/text [V]. Codes are stored like HA login credentials and cannot be recovered [V].
- One **user per person**, with `can_arm`, `can_disarm`, area limits and `is_override_code` [V] (an override code, not a duress code; check its exact effect in the Alarmo UI before assigning it [I]). Disable a user with `alarmo.disable_user` instead of sharing codes.
- `alarmo.arm` takes `code`, `mode`, `skip_delay`, `force` (bypasses open sensors until next disarm) [V]. Use `force` only after a human saw the open-sensor list.
- Automations react to `alarmo_command_success` and `alarmo_failed_to_arm` events [V].
- Presence-based auto-arm: notify with an "arm?" action rather than arming silently [I]; never auto-**disarm** on phone presence alone (a stolen phone disarms the house) [I].

## Anti-patterns

| Don't | Why |
|---|---|
| Call it a certified, graded or insurance-approved alarm | It is uncertified DIY; no EN 50131 grade, no URN [V NSI / I] |
| Leave `trigger_unavailable` off on perimeter sensors | Default is fail-silent: dead sensor = safe [V] |
| Set `trigger_time: 0` with an outdoor siren | Sounds until disarmed [V]; noise complaints and nuisance |
| Put entry delay on every sensor | An intruder through a window gets the delay too |
| Share one code among everyone | No audit trail, cannot revoke one person |
| Auto-disarm on phone presence | A stolen or spoofed phone disarms the house |
| Expose disarm to voice assistants | Spoken PINs are overheard (see `home-assistant-google-home`) |
| Use normal-priority push for a trigger | DND silences it; use critical / `alarm_stream` |
| Rely on a camera detection to confirm before sounding | The NVR is non-critical and may be down |
| Skip a live test of trigger, siren and unavailable | Untested alarms fail when needed |
