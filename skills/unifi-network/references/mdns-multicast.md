# mDNS and multicast across VLANs

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: unifi-mdns-proxy
    source_url: https://help.ui.com/hc/en-us/articles/12648701398807
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Gateway mDNS proxy Auto/Off/Custom, custom VLAN and service scope, per-gateway network limits (UDR/UDM 30, UDM Pro/SE/UCG 50, EFG 60, Express/UXG Lite 2)."
  - kind: external_fact
    subject: ha-cast-cross-subnet
    source_url: https://www.home-assistant.io/integrations/cast/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "mDNS not routed across subnets; cross-subnet discovery unsupported; use mDNS forwarding or static IPs plus known_hosts; Docker needs host networking."
-->

Labels: **[V]** fetched 2026-09-27 (help.ui.com via archive capture, HA docs); **[I]** inferred.

## Checklist

- mDNS (UDP 5353) and SSDP (UDP 1900) are link-local; they do not cross VLANs by themselves [V HA cast docs / I ports].
- The gateway **mDNS Proxy**: Auto / Off / **Custom**; Custom picks VLANs and services (e.g. `_googlecast._tcp.local`, `_hue._tcp.local`, `_hap._tcp.local`) [V]. Per-gateway network limits apply (e.g. UDR/UDM 30, UDM Pro/SE/UCG 50) [V].
- The mDNS proxy does not relay SSDP [I]. For SSDP devices, add them by IP, or keep them on HA's VLAN.
- Firewall must also allow the actual control traffic (e.g. HA → Cast TCP 8009 [I]) after discovery.
- If AP Multicast Filtering / enhancement is enabled in WiFi settings, it can hide multicast from wireless IoT [V/I]; disable it on the IoT SSID when discovery fails.
- Fallback: fixed IPs plus manual host entries, **only where the integration supports it** (e.g. Cast `known_hosts` [V]; Hue and many others accept a manual IP at setup [I]). It is not a universal substitute for discovery; after setup, test that control works, not just that the device appears.


## Common service types

| Device family | mDNS service [I] |
|---|---|
| Google Cast / Nest speakers | `_googlecast._tcp.local` |
| Philips Hue bridge | `_hue._tcp.local` |
| HomeKit / Matter-over-IP | `_hap._tcp.local`, `_matter._tcp.local` |
| ESPHome | `_esphomelib._tcp.local` |
| Home Assistant itself | `_home-assistant._tcp.local` |

Verify the exact service name with an mDNS browser (`avahi-browse -a` on Linux, `dns-sd -B` on macOS) on the device's own VLAN before adding it to the Custom list.
