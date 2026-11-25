# Hue, Tapo and Govee in Home Assistant

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: hue-integration
    source_url: https://www.home-assistant.io/integrations/hue/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Local push via v2 bridge event stream; v1 bridges polled; 2025.9.1 added support for migrated Hue bridges."
  - kind: external_fact
    subject: tplink-tapo
    source_url: https://www.home-assistant.io/integrations/tplink/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Core tplink controls Tapo locally without the TP-Link cloud; credentials are the TP-Link cloud email (case-sensitive) and password; camera live view needs the Tapo camera account."
  - kind: external_fact
    subject: govee
    source_url: https://www.home-assistant.io/integrations/govee_light_local/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "govee_light_local added 2024.2, LAN control must be enabled in the Govee app, 200+ models; govee_ble sensors only; LaggAt/hacs-govee cloud integration maintenance-only, 60 req/min."
-->

Labels: **[V]** fetched 2026-09-27 from the cited page; **[I]** inferred.

## Order of work

1. Give each bridge or device a DHCP reservation first (see `unifi-network`); local integrations break when IPs move.
2. If IoT devices sit on a separate VLAN, make sure HA can reach them and that discovery (mDNS/SSDP) crosses the VLAN boundary, or add them by IP.
3. Add the local HA integration. Confirm control works with the internet unplugged where the vendor allows it.
4. Expose the HA entities to Google (SKILL.md), then unlink the vendor's own Google Home link so devices are not duplicated.

## Philips Hue

- Integration: core `hue` [V https://www.home-assistant.io/integrations/hue/].
- V2 bridges push state instantly over the local event stream; V1 bridges are polled and supported "as long as it is technically possible" [V].
- 2025.9.1 added support for migrated Hue bridges [V release notes 2025.9]; that this is the Bridge Pro migration flow is [I].
- Keep the bridge. Moving Hue bulbs onto your own Zigbee coordinator (ZHA/Z2M) loses the Hue app, entertainment/sync and bridge firmware updates and needs a factory reset of each bulb [I]. Do it only for a deliberate reason, e.g. to use mains bulbs as Zigbee routers.
- The Hue bridge runs its own Zigbee network. Its channel matters when planning your own Zigbee channel: read it in the Hue app and keep the two networks on different channels [I].

## TP-Link Tapo

- Integration: core `tplink`; controls Tapo plugs (P100, P110, P115...), bulbs and strips, H100/H200 hubs and their child sensors, and cameras locally "without going via the TP-Link cloud" [V].
- Credentials: the TP-Link cloud email (case-sensitive) and password are needed at setup [V]. Camera live view also needs the camera account created in the Tapo app (Advanced Settings > Camera Account) [V].
- The HA version that added Tapo support is **unverified** (around 2024, KLAP protocol via python-kasa [I]).
- Firmware updates from TP-Link have broken local auth before [I]; hold firmware updates on critical plugs until the integration's issue tracker is quiet.
- Cameras: the HACS `tapo_control` integration adds PTZ and more; it needs "Third Party Compatibility" enabled in the Tapo app and ports 443, 8800, 554, 2020, 20005/udp reachable, and warns that running several Tapo integrations at once conflicts [V github.com/JurajNyiri/HomeAssistant-Tapo-Control]. For recording, feed the camera's RTSP stream to Frigate (`frigate-nvr`) instead.

## Govee

| Integration | Scope | Caveat |
|---|---|---|
| `govee_light_local` (core, 2024.2+) | Wi-Fi lights, 200+ models across H6xxx/H7xxx/H8xxx [V] | LAN control must be switched on per device in the Govee app [V]; some scenes unsupported [V]; LAN API uses multicast discovery, so VLAN multicast rules matter [I] |
| `govee_ble` (core, 2022.8+) | Sensors only: thermo-hygrometers, motion, window, buttons, CO2, meat thermometers [V] | Needs a Bluetooth adapter or proxy in range |
| `LaggAt/hacs-govee` (HACS, cloud) | Models without LAN API | Govee API key, 60 requests/min, maintenance-only and seeking a maintainer [V] |
| Matter (newer Govee models) | Multi-fabric to HA and Google Home | Which models ship Matter is **unverified** [I] |

## Local-API caveats (all vendors)

- "Local" control can still need a cloud account at setup (Tapo) or a vendor-app toggle (Govee LAN control). Record which, so a restore or new host knows the dependency.
- Vendor firmware can remove or change a local API without notice [I]. Prefer standards (Zigbee, Matter) for anything important.
- None of these belong in a safety path. A leak or alarm automation may use a Hue flash as a secondary cue, never as the alert.
