# Critical notifications and availability watchdogs

Labels: [V] verified 2026-09-27 against the cited source; [I] re-verify.

## Critical push (Companion app)

Source: https://companion.home-assistant.io/docs/notifications/critical-notifications/ [V].

```yaml
# script: notify_critical (fields: title, message)
sequence:
  - action: notify.mobile_app_<device>
    data:
      title: "{{ title }}"
      message: "{{ message }}"
      data:
        push:                 # iOS
          sound:
            name: default
            critical: 1
            volume: 1.0
        ttl: 0                # Android
        priority: high
        channel: alarm_stream
```

- iOS critical alerts bypass Do Not Disturb and mute [V]; the user must allow critical alerts for the Companion app once.
- The Android keys only apply when **local push** is not in use [V]. `ttl: 0` and `priority: high` make delivery immediate; whether the alert sounds through Do Not Disturb depends on the `alarm_stream` channel's settings on each phone (sound, override DND). Check them on every phone after the first alert.
- Send to every responsible person's device, not one phone. A `notify` group is fine for normal alerts; for critical ones call each device so one failure does not hide the others [I].
- Time the alert end to end during testing (event to phone) and record the number.

## Repeat until handled

A device that re-reports "wet" every few minutes does not change HA state, so no new trigger fires. Repeat from the automation:

```yaml
actions:
  - repeat:
      sequence:
        - action: script.notify_critical
          data: {title: "LEAK", message: "{{ trigger.to_state.name }} is wet"}
        - delay: {minutes: 5}
      until:
        - condition: state
          entity_id: binary_sensor.<leak_entity>
          state: "off"
```

Add an acknowledge path (an `input_boolean` or an actionable notification) if the repeats should stop before the sensor dries. Use `mode: single` so a second trigger does not start a parallel loop.

## Unavailable, battery, coordinator offline

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.<leak_entity>
    to: unavailable
    for: {hours: 1}
  - trigger: numeric_state
    entity_id: sensor.<leak_entity>_battery
    below: 20
```

- `for:` stops noise from brief drop-outs and restarts. Pick it above the stack's own availability timeout (see `home-assistant-zigbee`), or HA never sees the gap.
- On HA restart entities pass through `unavailable`/`unknown`; state triggers that mean a real change should use `not_from: [unavailable, unknown]` [I].
- A leak sensor going from `unavailable` straight to `on` is still a leak: do **not** add `not_from` to the leak trigger itself.
- Coordinator offline: Zigbee2MQTT publishes a bridge state entity (`binary_sensor` / `sensor` for the bridge connection) and ZHA marks all devices unavailable when the radio drops [I]. Alert on the bridge entity, not on every device.
- Test each watchdog by causing it (pull the battery, power down the router or coordinator) and time it.

## External heartbeat

HA cannot report its own death. For a safety setup, run a monitor elsewhere (another host, a hosted uptime checker) that polls HA or receives a periodic webhook, and alerts through a path that does not depend on HA [I].
