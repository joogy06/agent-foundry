# Home Assistant: config layout and API

Labels: [V] verified against the cited source on 2026-09-27; [I] re-verify before relying on it.
Docs roots: https://www.home-assistant.io/docs/configuration/ and https://developers.home-assistant.io/docs/api/rest/ [I].

## Layout that survives a host move

```
/config
  configuration.yaml      # short: defaults + includes only
  secrets.yaml            # never in git
  automations.yaml        # owned by the UI editor
  scripts.yaml, scenes.yaml
  packages/
    leak.yaml             # one feature per file
    availability.yaml
  blueprints/automation/<author>/<name>.yaml
```

```yaml
# configuration.yaml
default_config:
homeassistant:
  packages: !include_dir_named packages   # [I]
automation: !include automations.yaml     # UI automations
script: !include scripts.yaml
scene: !include scenes.yaml
```

A package file can hold any integration keys (`automation:`, `template:`, `input_boolean:` ...), so a feature moves as one file [I]. When both a package and `configuration.yaml` define `automation:`, give the package list its own label key (e.g. `automation leak: ...`) or keep it inside the package [I].

```yaml
# secrets.yaml (excluded by .gitignore)
mqtt_password: "..."
# usage elsewhere
password: !secret mqtt_password
```

`.gitignore` minimum for a versioned `/config`: `secrets.yaml`, `.storage/`, `*.db*`, `home-assistant.log*`, `backups/`, `.cloud/` [I]. `.storage/` holds UI-managed state and credentials; it travels in HA backups, not in git.

## Validate before restart

- UI: Developer tools > YAML > Check configuration [I].
- HA OS CLI: `ha core check` [I].
- Reload single domains (automations, scripts, templates) instead of restarting when possible.

## Automation skeleton for reviewable YAML

```yaml
automation:
  - id: leak_bathroom_critical        # enables traces and UI viewing
    alias: "Leak - bathroom - critical alert"
    description: "Test: wet the probe; expect phone alert within 30 s"
    mode: single
    triggers:
      - trigger: state
        entity_id: binary_sensor.<leak_entity>
        to: "on"
    actions:
      - action: script.<notify_critical>
```

The 2024.10+ syntax uses `triggers:`/`trigger:`, `conditions:` and `actions:`/`action:`; older `trigger:`/`platform:`/`service:` still loads [I]. Match the style already in the instance.

## Blueprints

```yaml
blueprint:
  name: Sensor unavailable watchdog
  domain: automation
  input:
    sensor: {selector: {entity: {}}}
    minutes: {default: 60, selector: {number: {min: 5, max: 1440}}}
triggers:
  - trigger: state
    entity_id: !input sensor
    to: unavailable
    for: {minutes: !input minutes}
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.to_state.name }} unavailable for {{ minutes }} min"
variables:
  minutes: !input minutes
```

Instance: `use_blueprint: {path: <author>/<file>.yaml, input: {...}}` [I]. Updating the blueprint changes every instance on reload: re-test the safety ones.

## REST API

```bash
curl -s -H "Authorization: Bearer $HA_TOKEN" https://<ha-host>:8123/api/            # {"message": "API running."}
curl -s -H "Authorization: Bearer $HA_TOKEN" https://<ha-host>:8123/api/states/<entity_id>
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "<entity_id>"}' https://<ha-host>:8123/api/services/<domain>/<service>
```
[I] Read the token from an environment variable or secret store, never inline it in a committed script.

## WebSocket API

1. Connect to `wss://<ha-host>:8123/api/websocket`; server sends `auth_required`.
2. Send `{"type": "auth", "access_token": "<token>"}`; expect `auth_ok`.
3. Every later message carries an incrementing `id`: e.g. `{"id": 1, "type": "subscribe_events", "event_type": "state_changed"}` [I].

Use WebSocket for live events and registry reads (devices, entities, areas); REST for simple state reads and service calls.

## Long-lived access tokens

- Created under the user's profile > Security; shown once [I].
- One per client, named for the client, revoked when the client goes.
- Integrations that only read state get a non-admin user.
