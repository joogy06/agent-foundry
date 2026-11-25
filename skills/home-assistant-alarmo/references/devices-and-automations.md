# Alarmo: keypads, sirens, notifications and automations

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: alarmo-mqtt-and-services
    source_url: https://github.com/nielsfaber/alarmo
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "MQTT topics alarmo/state, alarmo/event, alarmo/command with {command, code} payload (code as string); services alarmo.arm (code, mode, skip_delay, force), alarmo.disarm, alarmo.skip_delay, enable_user/disable_user; events alarmo_failed_to_arm, alarmo_command_success."
  - kind: external_fact
    subject: z2m-keypad-siren-pages
    source_url: https://www.zigbee2mqtt.io/devices/KEYZB-110.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "KEYZB-110 action/action_code/action_transaction/arm_mode; SIRZB-110 warning + squawk, commands work on firmware <=1.7.1; HS2WD-E warning duration up to 1800 s."
-->

Labels: **[V]** checked 2026-09-27 against the Alarmo README/source or the cited Zigbee2MQTT page; **[I]** inferred. Device models are **examples of traits**, not recommendations; check the Zigbee2MQTT/ZHA device page for the exact model before buying.

## Notifications

Alarmo has built-in actions (notification, switch/light/script) for Triggered, Failed to arm, Armed, Disarmed, Leave (exit delay) and Entry (entry delay), with message wildcards `{{open_sensors}}`, `{{arm_mode}}`, `{{delay}}`, `{{changed_by}}` [V README].

For the **Triggered** alert, use an HA automation on the panel **state** with a critical payload (HA Companion app [V companion.home-assistant.io]):

```yaml
alias: Alarm triggered - critical push
id: alarm_triggered_critical_push
triggers:
  - trigger: state
    entity_id: alarm_control_panel.alarmo
    to: triggered
actions:
  - action: notify.mobile_app_<phone>
    data:
      title: "ALARM"
      message: >-
        Triggered: {{ state_attr('alarm_control_panel.alarmo', 'open_sensors') or 'see Alarmo log' }}
      data:
        push: {sound: {name: default, critical: 1, volume: 1.0}}   # iOS
        ttl: 0                                                     # Android
        priority: high
        channel: alarm_stream
mode: single
```
The `open_sensors` attribute name is [I]; check the entity's attributes in Developer tools > States first. A state trigger has no `trigger.event`; use `trigger.event.data` only in event-triggered automations (below). Whether Alarmo's own action editor passes the nested `data:` through is **unverified**, which is why the critical alert lives in an HA automation.

## Keypads

Two integration shapes:

| Shape | How | Notes |
|---|---|---|
| **Zigbee keypad via Zigbee2MQTT** | Automation on the keypad's `action` + `action_code`, calling `alarmo.arm`/`alarmo.disarm`; then publish the resulting mode back to the keypad | Example KEYZB-110 exposes `action` (disarm, arm_day_zones, arm_night_zones, arm_all_zones, exit_delay, emergency), `action_code`, `action_transaction`, writable `arm_mode`, `tamper`, battery [V z2m]. The keypad expects a reply echoing the transaction, e.g. `{"arm_mode":{"mode":"arm_all_zones","transaction":<n>}}` [V] |
| **Keypad speaking Alarmo's MQTT API** | Publish `{"command":"ARM_AWAY","code":"1234"}` to `alarmo/command`; read `alarmo/state` and `alarmo/event` [V README] | Send the code as a **string** so leading zeros survive [V]. Keep "Require code" on [V warning] |
| ZHA keypad | ZHA provides an `alarm_control_panel` platform [V HA zha docs] (IAS ACE cluster [I]) | Map it to Alarmo with an automation; community blueprints exist but are **unverified** here, read before import |

Rules: map `emergency` to an immediate trigger; handle `tamper` as an `always_on` tamper sensor; never log `action_code` in notifications.

## Sirens

- Zigbee sirens take a `warning` payload in Zigbee2MQTT, e.g. SIRZB-110: `{"warning":{"duration":60,"level":"low","mode":"burglar","strobe":false,"strobe_duty_cycle":0}}`; modes stop, burglar, fire, emergency, police_panic, fire_panic, emergency_panic; `squawk` for armed/disarmed chirps [V]. Its page says the commands work on firmware 1.7.1 or lower [V]; check firmware before relying on it.
- HS2WD-E: `{"warning":{"duration":10,"mode":"emergency","strobe":false}}`, duration up to 1800 s [V].
- ZHA exposes sirens as `siren` entities [V].
- Trigger the siren from an automation on the panel state `triggered`, stop it on `disarmed`. Set the siren's own duration no longer than the Alarmo trigger time, so a lost "stop" message does not leave it sounding.
- Test at low level first. Battery-backed sirens keep sounding after mains loss; whether a given model has a backup battery is per device (**unverified** for the examples).
- A Zigbee siren depends on the coordinator and HA; if either is down it cannot sound. Record this limitation.

## Automation patterns

```yaml
# Failed to arm: tell the person what is open, offer force-arm
triggers:
  - trigger: event
    event_type: alarmo_failed_to_arm
actions:
  - action: notify.mobile_app_<phone>
    data:
      message: "Not armed: {{ trigger.event.data.reason }} {{ trigger.event.data.sensors }}"
      data:
        actions:   # offer force-arm only after reading the sensor list
          - {action: ALARMO_FORCE_ARM, title: "Arm anyway"}
          - {action: ALARMO_RETRY_ARM, title: "Retry"}
```
Event fields `reason`, `sensors`, `command` and the action IDs are from Alarmo's source [V event.py, const.py]; trigger/action YAML syntax follows current HA (`triggers:`/`actions:`) [I].

Other patterns:
- **Armed but a watchdog sensor is unavailable** → notify immediately, even if `trigger_unavailable` is off for it.
- **Arming reminder** at bedtime if disarmed and everyone home → actionable notification, not silent auto-arm.
- **Trigger** → siren, lights on, critical push to every user, optional Frigate snapshot attached if available (never waited on).
- **Disarm after trigger** → stop siren, send "disarmed by {{changed_by}}".
- After trigger time expires: disarm if `disarm_after_trigger`, otherwise re-arm (skipping blocking sensors if `ignore_blocking_sensors_after_trigger`) or return to the armed mode [V].

## Commissioning test list

- [ ] Each sensor triggers in each mode it belongs to, and not in others.
- [ ] Exit and entry delays run with audible/visual feedback.
- [ ] Wrong code rejected; each user's code works with the right permissions.
- [ ] Open door blocks arming; notification lists it; force-arm works.
- [ ] Forced `unavailable` state on a `trigger_unavailable` sensor triggers while armed; a pulled battery does too, within the configured availability timeout.
- [ ] Siren starts and stops; its own timeout ends it if "stop" is lost.
- [ ] Critical push breaks through Do Not Disturb on every phone.
- [ ] HA restart while armed: the panel returns armed [I, verify].
