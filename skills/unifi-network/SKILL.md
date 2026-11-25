---
name: unifi-network
description: UniFi Network (Ubiquiti) for smart-home and Home Assistant work - DHCP reservations (Fixed IP) and local DNS records, IoT and camera VLANs, the zone-based firewall (ZBF, Network 9.0+) vs legacy LAN_IN rules, mDNS proxy and multicast across VLANs for discovery, PoE port modes and power-cycling, reading access-point 2.4 GHz radio plans, and read-only queries through the local Network API with X-API-KEY. Use when changing or inspecting a UniFi network that hosts Home Assistant, cameras or IoT devices.
---

# UniFi Network

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: unifi-network-version
    source_url: https://fw-update.ui.com/api/firmware-latest?filter=eq~~product~~unifi-controller&filter=eq~~channel~~release
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Latest stable UniFi Network Application 10.6.106 (2026-09-15); UniFi OS console firmware 5.1.x/5.2.x."
  - kind: external_fact
    subject: unifi-zone-based-firewall
    source_url: https://help.ui.com/hc/en-us/articles/115003173168
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "ZBF introduced in Network 9.0.108, gateway firmware 4.1+; built-in zones External, Internal, Gateway, VPN, Hotspot, DMZ plus custom zones; migration via Traffic & Firewall Rules > Upgrade; reversibility not documented."
  - kind: external_fact
    subject: unifi-local-api
    source_url: https://help.ui.com/hc/en-us/articles/30076656117655
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Local Network API documented in-app under Integrations; key created there; header X-API-KEY; base /proxy/network/integration/v1; now includes write endpoints."
  - kind: external_fact
    subject: unifi-mdns-proxy
    source_url: https://help.ui.com/hc/en-us/articles/12648701398807
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Gateway mDNS proxy modes Auto/Off/Custom with per-VLAN and per-service scope; per-gateway network limits."
-->

## Overview

UniFi is the network under Home Assistant, the Zigbee coordinator and the cameras. Mistakes here silently break the critical layer (HA cannot reach the coordinator) or lock people out. **Two guardrails are non-negotiable:**

1. **Read before write.** Inspect the current state (API or UI export) and show it before proposing a change.
2. **Never change the production firewall, VLANs or PoE without a rollback plan** and the user's explicit go-ahead: a fresh backup, the exact change, how to test it, how to undo it.

Evidence labels: **[V]** fetched 2026-09-27 (help.ui.com via archive captures, fw-update.ui.com, HA docs); **[I]** inferred, re-verify in the user's UI. Current stable **Network 10.6.106** (2026-09-15) [V]; menu paths moved between 9.3, 9.4 and 10.x, so confirm the version first (Settings > System, or `/v1/info`). Commands and API detail: [references/api-and-recipes.md](references/api-and-recipes.md).

## When to use

- Reserving IPs for HA, a network coordinator, bridges or cameras.
- Designing an IoT or camera VLAN and its firewall policies.
- HA cannot discover Cast, Hue, HomeKit or other devices across VLANs.
- Turning PoE on/off or power-cycling a port.
- Choosing a Zigbee channel against the APs' 2.4 GHz channels.

**Not for:** Zigbee pairing and channel setting itself (`home-assistant-zigbee`); Proxmox bridges/VLAN tags on the host (`proxmox-admin`); HA config (`home-assistant`).

## Ask before changing

Ask one compact question when unknown:
1. **Gateway model and Network version** (menu paths and limits differ).
2. **Firewall mode**: zone-based or legacy rules?
3. **Is a change window agreed**, and who can physically reach the gateway if remote access drops?

## Change protocol (every write)

1. **Read** the current config (screenshots or API reads).
2. **Back up** (Settings > System > Backups [I path]).
3. **Plan** one change with its expected result.
4. **Rollback**: exact undo steps plus "restore backup"; keep a wired same-VLAN admin path.
5. **Apply** with explicit approval.
6. **Test** from the affected client (e.g. HA reaches the coordinator's IP and port), plus internet and admin access.
7. **Record** it in the project notes.

## DHCP reservations and local DNS

- Client Devices > device > Settings > **Fixed IP Address**, optionally **Local DNS Record** with a hostname > Apply [V]. The name resolves only for clients using the gateway as DNS [V].
- Reserve **before** configuring anything that stores an IP (Zigbee2MQTT `tcp://<ip>:<port>`, ZHA `socket://`, integrations).
- Never also set a different static IP on the device itself.
- DNS policies (A, AAAA, CNAME, ...): Settings > Policy Table > DNS in 9.4+ [V]; CNAME needs UniFi OS 4.3+ and Network 9.3+ [V].

## VLANs and the zone-based firewall

**ZBF** arrived in Network 9.0 and needs gateway firmware 4.1+ [V]. Built-in zones: External, Internal, Gateway, VPN, Hotspot, DMZ (locked); admins can add custom zones; each network belongs to exactly one zone [V].

| | Zone-based (current) | Legacy rules |
|---|---|---|
| Model | Policies between zone pairs, both directions [V] | LAN_IN / LAN_OUT / LAN_LOCAL / WAN_IN rule sets |
| Where | Settings > Zones or Policy Table (9.4+) [V] | Settings > Security > Traffic & Firewall Rules |
| Return traffic | "Auto Allow Return Traffic" on Allow [V] | Manual established/related rules |
| Migration | Traffic & Firewall Rules > **Upgrade**, no downtime; may create redundant rules [V] | |
| Undo | Not documented [V absence]; treat as **one-way** except by restoring a pre-migration backup [I] | |

Typical smart-home layout (a trait pattern; adapt names and subnets):

| Zone / VLAN | Holds | Policy |
|---|---|---|
| Internal (trusted) | Phones, PCs, **HA** | Default |
| Custom `IoT` | Plugs, bulbs, bridges, network coordinator | Internal → IoT: allow only what HA and admins need (per device/port); IoT → Internal **block** except return traffic; IoT → Gateway DNS/NTP/DHCP allow; IoT → External per device |
| Custom `Cameras` | IP cameras | Only the NVR and admins connect; allow gateway DNS/NTP; internet **blocked** (open briefly for firmware updates) |

Rules:
- If HA and a **network-attached coordinator** are on different VLANs, allow HA → coordinator TCP port explicitly (and return traffic). Simplest: keep them on the same VLAN.
- Write a per-device traffic matrix (source, destination, port, why) before creating policies, and test every policy in **both** directions afterwards.
- Policy order: custom policies beat built-ins; reorder with "Reorder" [V]. Put narrow allows above broad blocks.
- Use Block (silent) toward IoT/External, Reject for internal troubleshooting [V actions].

## mDNS and multicast for HA discovery

mDNS (UDP 5353) and SSDP (UDP 1900) do not cross VLANs by themselves [V HA cast docs]. Use the gateway **mDNS Proxy** in **Custom** mode, scoped to the needed VLANs and services only [V]; add SSDP devices by IP; allow the control traffic in the firewall too. Fallback where the integration supports it: fixed IPs plus a manual host (e.g. Cast `known_hosts`); then test control, not just discovery. Full checklist: [references/mdns-multicast.md](references/mdns-multicast.md).

## PoE

- Per-port modes: Auto, Off, Passive 24V, Passthrough [V]; Port Manager on the switch device page [I].
- A port **power-cycle** is a write (disruptive).
- The HA UniFi integration exposes PoE switches and power-cycle buttons [V]; never automate PoE-off on the port feeding the coordinator or HA host.
- Passive 24V can damage an 802.3af/at device [I].

## 2.4 GHz channels for Zigbee planning

1. Read each AP's current 2.4 GHz channel and width: device page > Radios, or the API device detail [I paths]; Channel AI lives under AirView > Radios [V].
2. Keep 2.4 GHz at **20 MHz** width on channels 1/6/11 [I].
3. Pick the Zigbee channel furthest from the used WiFi channels: Zigbee **15** (between WiFi 1 and 6), **20** (between 6 and 11), **25** (above 11) [I standard overlap]. Channel 26 is least affected but many devices do not support it [V oscium].
4. Pin the APs' 2.4 GHz channels (or omit channels in Channel AI's plan [V]) so automatic optimisation does not later move WiFi onto the Zigbee channel.
5. Check other Zigbee networks too (e.g. a Hue bridge).

## Anti-patterns

| Don't | Why |
|---|---|
| Change firewall/VLAN/PoE without backup, approval and rollback plan | Can cut HA off the coordinator or lock out remote admin |
| Migrate to ZBF casually | No documented undo [V absence]; rules get rewritten |
| Configure device IPs before reserving them | IP moves, integration dies at 3 a.m. |
| Put HA and its network coordinator on different VLANs with no allow policy | Zigbee network goes offline |
| Enable every mDNS service on every VLAN | Leaks device inventory and chatter to IoT |
| Give cameras internet access | Firmware phones home; isolate them |
| Let Channel AI move 2.4 GHz freely after Zigbee is set | WiFi can land on the Zigbee channel |
| Use an admin UI account password or cloud SSO for scripts | Use a scoped local API key [V HA docs: SSO users fail] |
| Use write API endpoints for "read-only" work | The local API now writes [V]; keep scripts GET-only |
