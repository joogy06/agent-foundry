---
name: home-assistant
description: Home Assistant (HA) platform and router - install types (HA OS, Container, deprecated Core/Supervised), configuration.yaml layout with packages, secrets.yaml and !include, YAML vs UI automations, blueprints, REST and WebSocket API with long-lived access tokens, backups to off-VM storage and restore, Companion app critical notifications (iOS critical, Android alarm_stream), and unavailable-entity alerts. Use when building, configuring or recovering a Home Assistant instance; routes Zigbee, UniFi, Alarmo, Frigate, Google Home and Proxmox work to child skills.
---

# Home Assistant

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: home-assistant-release
    source_url: https://www.home-assistant.io/blog/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Calendar versioning YYYY.M, monthly; latest 2026.9 (2026-09-02), patch 2026.9.4 seen on the docs site."
  - kind: external_fact
    subject: home-assistant-install-types
    source_url: https://www.home-assistant.io/blog/2025/05/22/deprecating-core-and-supervised-installation-methods-and-32-bit-systems/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Core and Supervised deprecated from 2025.6, unsupported from 2025.12; supported: HA OS (has apps, formerly add-ons) and Container (no apps)."
  - kind: external_fact
    subject: companion-critical-notifications
    source_url: https://companion.home-assistant.io/docs/notifications/critical-notifications/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "iOS push.sound.critical: 1 with volume; Android ttl: 0, priority: high, channel: alarm_stream."
  - kind: external_fact
    subject: home-assistant-backups
    source_url: https://www.home-assistant.io/common-tasks/general/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Automatic scheduled backups with retention; locations local /backup, HA Cloud (max 5 GB), network storage and integrations; encrypted by default (always for HA Cloud), emergency kit needed to restore encrypted backups; restore offered during onboarding, also onto a different device type."
-->

## Overview

Home Assistant is a local-first automation hub. Its value depends on three properties this skill protects: **alerts that reach a person** (critical notifications, unavailable detection), **config that survives a host move** (packages, secrets, off-host backups), and **no silent failure** (every safety automation has a test and a watchdog).

Evidence labels: **[V]** checked against the cited source on the date given; **[I]** secondary or training knowledge, re-verify before relying on it.

## Routing

| Topic | Skill |
|---|---|
| Zigbee coordinator, Zigbee2MQTT or ZHA, channels, pairing, LQI, leak-sensor validation | `home-assistant-zigbee` |
| UniFi VLANs, DHCP reservations, firewall rules, PoE, Wi-Fi channels | `unifi-network` |
| Alarm panel built on Alarmo | `home-assistant-alarmo` |
| Cameras and object detection with Frigate | `frigate-nvr` |
| Google Home exposure, Nabu Casa / manual Google Assistant, Matter, and bringing Hue / Tapo / Govee into HA | `home-assistant-google-home` |
| The hypervisor under an HA OS VM (qm, snapshots, vzdump, USB passthrough) | `proxmox-admin` |

This skill owns everything HA-core: install type, config layout, automations, API, backups, notifications, availability.

## Ask before building

Ask one compact question when any of these is unknown, because each changes the output:
1. **Install type** (HA OS vs Container) - decides whether apps (Mosquitto, Zigbee2MQTT) exist.
2. **Phones that receive alerts** (iOS, Android, both) - decides the notification payload.
3. **Where backups go off the host** (NAS share, HA Cloud, other).

Always ask before: rebooting a host, changing firewall/VLAN/PoE, changing a Zigbee channel after devices are paired, flashing firmware.

## Install types

| Type | Status | Apps (formerly add-ons) | Pick when |
|---|---|---|---|
| **HA OS** (VM or bare metal) | Supported [V] | Yes, via Supervisor [V] | Default. Full backups include apps and their data |
| **Container** (Docker) | Supported [V] | No [V]; run Mosquitto, Z2M etc. as your own containers | Host already runs a container stack you manage |
| **Core** (Python venv) | Unsupported since 2025.12 [V] | No | Never for new builds; migrate to Container |
| **Supervised** | Unsupported since 2025.12 [V] | Was yes | Never; migrate to HA OS |

Versions are `YYYY.M.patch`, released monthly [V]. Read release notes' "Backward-incompatible changes" before each monthly update.

## Configuration layout

Details and templates: [references/config-and-api.md](references/config-and-api.md).

- Keep `configuration.yaml` short; group each feature (leak, alarm, heating) into a **package**: `homeassistant: packages: !include_dir_named packages` [I].
- Every credential goes in `secrets.yaml` and is referenced as `!secret name`; `secrets.yaml` never enters git.
- `!include`, `!include_dir_list`, `!include_dir_merge_named` split large sections [I].
- Validate before restart: Developer tools > YAML > Check configuration, or `ha core check` on HA OS [I].

## YAML vs UI automations

| | UI editor | YAML in a package |
|---|---|---|
| Stored in | `automations.yaml` (UI rewrites it, drops comments) [I] | Your file, version-controlled |
| Editable in UI | Yes | No (read-only in UI) |
| Traces | Yes | Yes, if the automation has an `id` [I] |
| Best for | Quick, user-owned rules | Safety-critical rules you review and diff |

Rule: safety automations (leak, alarm, offline) live in YAML packages with an `id`, a `description`, and a named test.

**Blueprints** parameterise a pattern (`blueprint:` + `input:`; instances use `use_blueprint:`) [I]. Use one when the same automation repeats across 3+ devices; imported blueprints are code from the internet: read them before use.

## API and tokens

- REST: `https://<host>:8123/api/...` with `Authorization: Bearer <token>` [I].
- WebSocket: `/api/websocket`; first message `{"type": "auth", "access_token": "<token>"}` [I]. Use it for event subscriptions; REST for one-shot reads and service calls.
- Long-lived access tokens: user profile > Security [I]. One token per client, named after it; store in the client's secret store; revoke when the client is retired. Prefer a dedicated non-admin user for integrations that do not need admin.

## Backups

- Turn on **automatic backups** with retention [V], and send at least one copy **off the machine HA runs on**: network storage (NAS share), HA Cloud (max 5 GB) [V], or a storage integration.
- Download and store the **emergency kit** outside HA; encrypted backups cannot be restored without it [V]. Encryption is the default (and always on for HA Cloud) [I on which locations may disable it].
- Restore is offered during onboarding and works onto a different device type [V]: this is the host-migration path.
- Hypervisor snapshots/backups (see `proxmox-admin`) complement HA backups; they do not replace them, because they are tied to that hypervisor.
- Zigbee network state has its own backup (see `home-assistant-zigbee`).
- A backup is proven only by a restore test on a scratch VM or new host.

## Notifications and availability

Payloads, the repeat-until-dry pattern and the unavailable watchdog: [references/notifications-and-availability.md](references/notifications-and-availability.md).

- Critical alerts: iOS `push.sound.critical: 1` + `volume`; Android `ttl: 0`, `priority: high`, `channel: alarm_stream` [V]. Send both key sets when recipients use both platforms.
- A device re-sending the same "wet"/"on" does **not** create a new state change, so repeat alerts must come from the automation (`repeat ... until`).
- Every safety sensor gets an **unavailable** automation (`to: unavailable` with `for:`), a **low battery** automation, and the hub/coordinator gets an **offline** automation.
- An alert path that depends on HA itself cannot report HA being down: add an external heartbeat (e.g. an uptime monitor on another host) for critical setups.

## Anti-patterns

| Don't | Why |
|---|---|
| Start a new build on Core or Supervised | Unsupported since 2025.12 [V]; no apps, and issues on those installs are not supported |
| Keep the only backup on the HA disk or VM | Dies with the host; the restore path needs an off-host copy |
| Lose the backup emergency kit | Encrypted backups become unrecoverable [V] |
| Put tokens or MQTT passwords in `configuration.yaml` or git | Leaks credentials; use `secrets.yaml` / `!secret` |
| Rely on the device re-sending "wet" for repeat alerts | Same state = no trigger; use `repeat` until clear |
| Normal-priority push for a leak | Muted by Do Not Disturb; use critical / alarm_stream |
| Treat `unavailable` as "off" or "dry" | A dead sensor looks safe; alert on unavailable with a `for:` delay |
| Edit safety automations only in the UI | No diff, no review, comments lost |
| Import a blueprint unread | Runs someone else's code with your devices |
| Treat an HA alarm as certified | Not insurance-grade (EN 50131) [I]; say so to the user |
