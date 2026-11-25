---
name: home-assistant-zigbee
description: Zigbee for Home Assistant - Zigbee2MQTT (Mosquitto, adapter ember, deprecated ezsp, tcp:// network coordinators, coordinator_backup.json, network_key) vs ZHA (socket://), Zigbee channel choice against Wi-Fi (15, 20, 25), pairing routers before battery end devices, LQI and route diagnostics, availability timeouts, EmberZNet NCP vs Thread RCP firmware, moving a coordinator between hosts, and a leak-sensor validation checklist. Use when setting up, debugging or migrating a Zigbee network under Home Assistant; not for HA-core config (home-assistant).
---

# Home Assistant Zigbee

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: z2m-ember-adapter
    source_url: https://www.zigbee2mqtt.io/guide/adapters/emberznet.html
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "adapter: ezsp is deprecated, use ember; supported EmberZNet 7.4.x, 8.0.x-8.2.x, 9.0.x, 9.1.x; network port syntax tcp://host:6638; allowed adapters zstack, ember, deconz, zigate, zboss."
  - kind: external_fact
    subject: z2m-network-and-availability
    source_url: https://www.zigbee2mqtt.io/guide/configuration/zigbee-network.html
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Default channel 11; network_key GENERATE; channel change only on zstack and ember, sleeping devices may need re-pair. Availability disabled by default; active 10 min, passive 1500 min (device-availability page)."
  - kind: external_fact
    subject: zha-network-coordinators
    source_url: https://www.home-assistant.io/integrations/zha/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "socket://IP:PORT for network radios; prefer channels 15/20/25; automatic network backups and radio migration; unavailable after 2 h (mains) and 6 h (battery) by default."
-->

## Overview

A Zigbee network is healthy when **routers form a mesh before end devices join**, the **channel avoids Wi-Fi**, the **network identity is backed up** (so a new host or adapter does not mean re-pairing), and **every safety device is validated in its final position**. Detail: [references/stack-and-coordinators.md](references/stack-and-coordinators.md), [references/validation-checklist.md](references/validation-checklist.md).

Labels: **[V]** checked against the cited source 2026-09-27; **[I]** re-verify.

## When to use

- Choosing Zigbee2MQTT vs ZHA, or configuring either against a USB or network coordinator.
- Picking a channel, pairing order, or diagnosing drop-outs, poor LQI, "device unavailable".
- Moving HA to another host, or replacing the adapter.
- Commissioning or validating a sensor before it becomes inaccessible (behind tiles, in a ceiling).

**Not for:** HA-core config, notifications and backups (`home-assistant`); VLANs, DHCP reservations and Wi-Fi channels on UniFi (`unifi-network`); USB passthrough into a VM (`proxmox-admin`).

## Ask before

Changing the channel after devices are paired, flashing coordinator firmware, deleting `coordinator_backup.json`, or pointing a second stack at the same coordinator. Each can orphan the whole network.

## Stack choice

| | Zigbee2MQTT | ZHA |
|---|---|---|
| Needs | MQTT broker (Mosquitto app) + Z2M app on HA OS [I] | Nothing extra (built-in integration) |
| EFR32 / EmberZNet radio | `adapter: ember` [V] (`ezsp` deprecated [V]) | Radio type EZSP [V] |
| Network radio | `port: tcp://<ip>:<port>` [V] | `socket://<ip>:<port>` [V] |
| Diagnostics | Rich: network map, per-device LQI, OTA, device converters | Simpler: visualisation, fewer device quirks exposed |
| Network backup | Whole Z2M data dir incl. `coordinator_backup.json` [V] | Automatic backups, migration wizard [V] |
| Default unavailable | Off; active 10 min, passive 25 h when on [V] | 2 h mains, 6 h battery [V] |

Default to Zigbee2MQTT when device diagnostics and wide device support matter; ZHA when fewer moving parts matter. Only **one** stack may hold a coordinator at a time [I].

## Channel

- Zigbee channel n sits at 2405 + 5(n-11) MHz; Wi-Fi 1/6/11 centre on 2412/2437/2462 MHz with ~20 MHz width [I].
- 15 (2425) sits between Wi-Fi 1 and 6, 20 (2450) between 6 and 11, 25 (2475) above 11 [I]; ZHA recommends 15/20/25 [V].
- Read the access points' actual 2.4 GHz channels first; pick the Zigbee channel furthest from them. Where Wi-Fi 12/13 are used (UK/EU), 25 overlaps: prefer 15 or 20 [I].
- Set it **before the first start** (Z2M default is 11 [V]). Later changes reach sleeping devices only when they wake, and some need re-pairing [V].

## Pairing order

1. Coordinator up, channel set, backup location decided.
2. **Mains-powered routers** (plugs, in-wall switches) in their final positions.
3. Battery end devices, joined **in or near their final position**: they pick a parent at join time [I].
4. After each join: rename to the site's naming convention, record the IEEE address, check LQI and route.

## Diagnostics

- LQI is 0-255 and vendor-relative [I]: compare against other devices on the same coordinator and watch the trend, not a single number.
- Check the **route**: a far sensor should reach the coordinator through a router, not directly at marginal LQI.
- Drop-outs across many devices at once point at the coordinator, its link (Wi-Fi-connected coordinators are less stable than Ethernet [V]) or USB interference (use a 50 cm extension [V]), not at the devices.
- Z2M availability is off by default [V]: turn it on. The default battery timeout is **25 h** [V], so a dead safety sensor is noticed a day late: set a shorter per-device timeout for safety sensors, tell the user the resulting detection time, and set HA's `for:` with that in mind.

## Firmware

- Zigbee coordinator = **EmberZNet NCP** firmware for EFR32 radios; Z2M `ember` supports 7.4.x-9.1.x [V].
- **RCP / OpenThread** firmware turns the same radio into a Thread border-router radio: no Zigbee [I]. Multi-protocol (Zigbee + Thread on one radio) is experimental; leave it off for a safety network [I].
- Confirm the firmware type in the coordinator's web UI before configuring the stack; flash only with the user's approval and a fresh network backup.

## Moving hosts or adapters

- **Network coordinator, new host:** stop the old host's stack first, then move the **whole** Z2M data dir (`zigbee2mqtt/` under the HA app; an HA OS backup carries it [I]) and keep the same `tcp://`/`socket://` address [V FAQ]. No re-pairing.
- **New adapter, same family** (ember->ember): keep the full data dir and copy the old adapter's IEEE address to the new one [V FAQ]; across families results vary [V FAQ]. ZHA offers "migrate radio" [V].
- Deleting `coordinator_backup.json` or changing `pan_id`/`ext_pan_id`/`network_key` forms a **new** network: every device must re-pair [V].

## Anti-patterns

| Don't | Why |
|---|---|
| `adapter: ezsp` on a new Z2M install | Deprecated; `ember` is the driver [V] |
| Pair on the default channel 11, then move | Sleeping devices miss the change; some need re-pairing [V] |
| Pair battery sensors before routers | They attach to the coordinator at poor LQI and stay there |
| Pair a sensor on the desk, then install it far away | Its parent and route were chosen at the desk |
| Run Z2M and ZHA against one coordinator | One TCP/serial client only; the network corrupts or flaps [I] |
| Use Wi-Fi to reach a network coordinator when Ethernet exists | Serial-over-IP tolerates loss badly [V] |
| Delete `coordinator_backup.json` to "fix" a start error | Forms a new network; everything re-pairs [V] |
| Read LQI as an absolute quality score | Vendor-relative; compare and trend |
| Flash Thread/RCP firmware onto the Zigbee coordinator | The Zigbee network disappears |
| Leave availability off in Z2M | Dead battery sensors look healthy |
