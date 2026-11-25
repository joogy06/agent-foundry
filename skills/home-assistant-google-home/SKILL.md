---
name: home-assistant-google-home
description: Home Assistant to Google Home and Google Assistant - Nabu Casa Home Assistant Cloud vs the manual google_assistant integration (Google Home Developer Console, cloud-to-cloud, test mode, service account, secure_devices_pin), entity exposure, voice security for locks, garage doors and alarm panels, Matter as an alternative path (HA as Matter controller, Matter Hub bridges), and bringing Philips Hue, TP-Link Tapo and Govee into HA locally. Use when exposing HA devices to Google Home or integrating existing Hue, Tapo or Govee devices.
---

# Home Assistant + Google Home

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: nabu-casa-pricing
    source_url: https://www.nabucasa.com/pricing/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "US/intl $6.50/mo or $65/yr ex tax; EU EUR 7.50/mo or 75/yr incl VAT; UK GBP 6.50/mo or 65/yr incl VAT."
  - kind: external_fact
    subject: google-assistant-manual-setup
    source_url: https://www.home-assistant.io/integrations/google_assistant/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Manual setup via Google Home Developer Console (console.home.google.com), cloud-to-cloud, needs external hostname + SSL and service_account; project stays in test mode; secure_devices_pin required to open/unlock secure devices; alarm panel code must equal secure_devices_pin."
  - kind: external_fact
    subject: google-account-linking-change
    source_url: https://developers.home.google.com/cloud-to-cloud/get-started
    verified_on: 2026-09-27
    review_by: 2026-11-15
    claim: "Google moving third-party smart-home account linking fully into the Google Home app; integration updates may be needed before 2026-09-30. Impact on personal test-mode HA projects unverified."
  - kind: external_fact
    subject: matter-hub-fork
    source_url: https://github.com/RiDDiX/home-assistant-matter-hub
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "t0bst4r/home-assistant-matter-hub archived Jan 2026; RiDDiX fork maintained (v2.0.57); HA itself is a Matter controller, not a bridge."
  - kind: external_fact
    subject: ha-local-integrations-hue-tapo-govee
    source_url: https://www.home-assistant.io/integrations/tplink/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Hue local push (v2 event stream); tplink integration controls Tapo locally; govee_light_local (2024.2) needs LAN control enabled in the Govee app."
-->

## Overview

Google Home is a **convenience surface**, never a safety path. Voice commands and account linking need Google's cloud; device control can be local (Google local fulfillment [V HA docs], Matter), but authentication and voice still depend on the internet. So the rule is: expose the minimum, protect anything that opens or disarms with a PIN, and keep every safety automation working when Google or the internet is down.

Evidence labels: **[V]** fetched from the cited source on 2026-09-27; **[I]** inferred or from memory, re-verify before relying on it.

## When to use

- Exposing HA entities to Google Home or Google Assistant (voice, Google Home app, Nest Hub).
- Choosing Nabu Casa vs the manual `google_assistant` setup.
- Deciding what voice may do with locks, covers, garage doors and alarm panels.
- Bringing existing Hue, Tapo or Govee devices into HA.

**Not for:** HA core config, notifications or backups (`home-assistant`); the alarm itself (`home-assistant-alarmo`); Zigbee pairing (`home-assistant-zigbee`); network reachability, VLANs and mDNS (`unifi-network`).

## Ask before building

Ask one compact question when unknown, because each changes the design:
1. **Nabu Casa subscription, or will the user run a public HTTPS endpoint?**
2. **Which entities should voice control**, and which must never be voice-controlled?
3. **Does an alarm panel or lock exist**, and may Google arm it only, or also disarm/unlock with a PIN?

## Path choice

| Path | How it works | Pick when | Cost / effort |
|---|---|---|---|
| **Nabu Casa Home Assistant Cloud** | HA's cloud relays Google requests; no open ports | Default for most homes | UK £6.50/mo or £65/yr incl VAT; US $6.50/mo ex tax [V nabucasa.com/pricing, 2026-09-27]. Minutes to set up |
| **Manual `google_assistant`** | Your own project in the **Google Home Developer Console** (console.home.google.com), cloud-to-cloud, service-account JSON [V HA docs] | No subscription, and the user already runs a secure public HTTPS endpoint | HA must be externally reachable with a hostname and valid SSL [V]. Project stays in **test mode forever**; sync can fail after ~30 days, regenerate the draft to fix [V] |
| **Matter bridge** (HA entities re-exposed as Matter devices) | Community bridge app (Matter Hub or Matterbridge) presents HA entities to Google Home locally | Want local control without cloud relay; accept a community component | HA is a Matter **controller**, not a bridge [V HA matter docs]. `t0bst4r/home-assistant-matter-hub` archived Jan 2026; the maintained fork is `RiDDiX/home-assistant-matter-hub` [V, 2026-09-27]. Matterbridge: Android commissioning can fail on country code, commission from iOS [V] |
| **Matter device, multi-fabric** | A native Matter device paired to both HA and Google Home | Buying new devices | No bridge needed; Thread devices need a border router (Nest Hub or HA's OTBR app) [V] |

The legacy **Actions on Google** console is gone for this: Conversational Actions sunset 2023-06-13 and smart home moved to the Google Home Developer Console [V developers.google.com/assistant/ca-sunset]. Guides that start in `console.actions.google.com` are stale.

**Watch item:** Google is moving third-party account linking fully into the Google Home app, with integrations possibly needing updates before **2026-09-30** [V developers.home.google.com, 2026-09-27]. Its effect on personal test-mode projects is **unverified**; if manual linking breaks after that date, check the HA `google_assistant` docs and issue tracker before debugging config.

## Exposure rules

- Expose deliberately: Settings > Voice assistants > **Expose** tab, per entity per assistant [V HA docs]. HA frames this as preventing accidental voice control of "sensitive devices, such as locks and garage doors" [V].
- Manual YAML: set `expose_by_default: false` (the default is **true** [V]) and list entities explicitly, or filter by domain.
- Turn on `report_state` for faster responses [V]; it pushes state to Google.
- Use spoken-friendly names and rooms; after renaming, say "Hey Google, sync my devices".
- Never expose raw sensors whose state Google could misrepresent as safety status (leak, smoke) as the only indication; the HA critical notification remains the alert path.

## Locks, covers and alarm panels

| Device | Google behaviour | Rule |
|---|---|---|
| Lock, garage door, gate | Opening/unlocking needs `secure_devices_pin`; closing/locking does not [V HA docs] | Always set a PIN; prefer not exposing garage/gate at all |
| Alarm panel (`alarm_control_panel`, e.g. Alarmo) | Arm and disarm supported; if the panel has a code, it **must equal** `secure_devices_pin`; with `code_arm_required: false` it arms without prompting [V HA docs] | An exposed panel **can be disarmed** by voice (PIN challenge). To forbid disarm, **do not expose the panel**; expose only reviewed **scripts** ("arm night", "arm away") |
| Nabu Casa | Offers an equivalent secure-devices PIN in Cloud > Google Assistant settings [I, support article returned 403] | Verify in the UI before relying on it |

Google's ArmDisarm trait supports disarm with a PIN challenge [V developers.home.google.com/cloud-to-cloud/traits/armdisarm]; possible is not safe.

## Bringing Hue, Tapo and Govee into HA

**Local integration first**, cloud only when no local path exists; then expose via HA and unlink the vendor's own Google link so each device appears once. Details and caveats: [references/ecosystems.md](references/ecosystems.md).

| Ecosystem | Preferred integration | Key fact |
|---|---|---|
| Philips Hue | Core `hue`, via the bridge | Local push over the v2 bridge event stream [V HA docs]; keep the bridge rather than re-pairing bulbs to your own Zigbee coordinator [I] |
| TP-Link Tapo | Core `tplink` | Controls Tapo plugs, bulbs, strips, hubs and cameras locally, but setup uses the TP-Link cloud credentials [V HA docs] |
| Govee lights | Core `govee_light_local` (since 2024.2) | Enable **LAN control** per device in the Govee app first [V HA docs]; core integration is local-only; models without LAN API need a separate cloud integration (HACS), a deliberate choice |

## Anti-patterns

| Don't | Why |
|---|---|
| Leave `expose_by_default` at its default in manual YAML | Default is true [V]; every new entity, including locks, goes to Google |
| Expose alarm disarm or a garage door to voice | A spoken PIN is overheard; opening is the attack, closing is the convenience |
| Use a different alarm code from `secure_devices_pin` | The manual integration requires them equal [V]; mismatches fail confusingly |
| Make Google Home part of a leak or alarm alert path | Cloud-dependent; the HA critical notification is the alert |
| Follow an Actions on Google console tutorial | Retired for this; use the Google Home Developer Console [V] |
| Port-forward 8123 with no TLS for the manual path | HA requires a hostname and SSL [V]; plain HTTP exposes the instance |
| Keep Hue/Tapo/Govee linked to Google directly and through HA | Duplicate devices, and routines act twice |
| Build on the archived t0bst4r Matter Hub | Unmaintained since Jan 2026 [V]; use the maintained fork or Matterbridge |
