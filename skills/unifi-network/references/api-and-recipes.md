# UniFi APIs and read-only recipes

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: unifi-integration-api-endpoints
    source_url: https://github.com/Art-of-WiFi/unifi-network-application-api-client
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Integration API: X-API-KEY, base https://<console>/proxy/network/integration, /v1/info, /v1/sites, /v1/sites/{siteId}/devices, /clients, device statistics/latest, action endpoints; client 1.0.0 (2026-02-17) targets API 10.1.84 and includes write endpoints."
  - kind: external_fact
    subject: unifi-site-manager-api
    source_url: https://developer.ui.com/site-manager-api/gettingstarted
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Site Manager API base https://api.ui.com/v1, X-API-KEY from unifi.ui.com settings, 10000 req/min on v1, 429 over limit."
  - kind: external_fact
    subject: ha-unifi-integration
    source_url: https://www.home-assistant.io/integrations/unifi/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "HA UniFi integration needs a local account (SSO users fail), no EA/RC versions; PoE port switches and power-cycle buttons, ZBF policy switches."
-->

Labels: **[V]** fetched 2026-09-27; **[I]** inferred. Endpoint lists come from a maintained third-party client and the in-app docs reference; the **authoritative list is the in-app API documentation** of the user's own console (UniFi Network > Integrations) [V]. Read it there before using any endpoint.

## Which API

| API | Auth | Scope | Use for |
|---|---|---|---|
| **Local Network Integration API** (official) | `X-API-KEY` header; key from Network > Settings/Integrations > Create New API Key [V] | Devices, clients, sites, statistics; now also writes (networks, WiFi, firewall policies/zones, DNS, ACLs, vouchers) and device/port actions [V] | Default for scripts and agents |
| **Site Manager API** (cloud) | `X-API-KEY` from unifi.ui.com > Settings > API Keys, shown once [V] | Aggregate monitoring across consoles; `https://api.ui.com/v1/hosts` etc.; 10,000 req/min, 429 over [V] | Multi-site overview; read-only in practice [I] |
| **Legacy/unofficial** `/proxy/network/api/s/{site}/...` and `/v2/api/site/{site}/...` | Local account session cookie (login `/api/auth/login` [I]) | Everything the UI does, unsupported [V] | Only when the official API lacks a read; never for writes by an agent |

## Key hygiene

- Create a dedicated key named for the client (e.g. `ha-agent-readonly`), store it in the secrets store (`~/.secrets/<project>.env` or HA `secrets.yaml`), never in git.
- The local API has no separate read-only key scope documented [I]; enforce read-only in the script (GET only) and review the script.
- Revoke the key when the agent's task ends.
- Consoles use a self-signed certificate; pin it or use `--cacert` rather than disabling verification globally [I].

## Read-only recipes (curl)

```bash
# Load the key from the secrets file, never inline it
set -a; . ~/.secrets/<project>.env; set +a     # provides UNIFI_HOST, UNIFI_API_KEY
BASE="https://$UNIFI_HOST/proxy/network/integration"
H="X-API-KEY: $UNIFI_API_KEY"
CA=~/.secrets/unifi-console-ca.pem   # the console's exported certificate

curl -s --cacert "$CA" -H "$H" "$BASE/v1/info"                                 # app version
curl -s --cacert "$CA" -H "$H" "$BASE/v1/sites"                                # site ids
SITE="replace-with-site-id"                  # from the /v1/sites output
curl -s --cacert "$CA" -H "$H" "$BASE/v1/sites/$SITE/devices?limit=200"        # APs, switches, gateway
curl -s --cacert "$CA" -H "$H" "$BASE/v1/sites/$SITE/devices/<id>"             # detail: ports, radios
curl -s --cacert "$CA" -H "$H" "$BASE/v1/sites/$SITE/devices/<id>/statistics/latest"
curl -s --cacert "$CA" -H "$H" "$BASE/v1/sites/$SITE/clients?limit=200"        # find a device's IP/MAC
```
Paths [V client source]; query parameters (`limit`, `offset`, `filter`) and response field names vary by version: read the in-app docs [I]. Export the console certificate once (browser, or `openssl s_client -showcerts -connect "$UNIFI_HOST:443"`) and pin it; do not use `-k`, which disables verification [I]. If the certificate CN/SAN does not match the host, add `--resolve` with the certificate's name.

What to extract for smart-home planning:
- **AP radios**: 2.4 GHz channel and width per AP (device detail) → Zigbee channel plan.
- **Switch ports**: which port feeds the coordinator/HA host, PoE mode and draw.
- **Clients**: IP and MAC of the coordinator, bridges and cameras, before reserving.

## Writes (only with approval and a rollback plan)

| Action | Official API | Legacy |
|---|---|---|
| Restart device | `POST .../devices/{id}/actions` `{"action":"RESTART"}` [V] | |
| Port action (power-cycle) | `POST .../devices/{id}/interfaces/ports/{portIdx}/actions` [V path]; action name `POWER_CYCLE` [I, unverified] | `POST /cmd/devmgr {"cmd":"power-cycle","mac":...,"port_idx":...}` [V aiounifi] |
| PoE mode | UI Port Manager preferred | `PUT /rest/device/{id}` with `port_overrides[].poe_mode` auto/off/pasv24/passthrough [V aiounifi]; replaces the whole overrides list, so read-modify-write [I] |
| Firewall policy / zone | Available in the official API [V]; prefer the UI so the user sees the change | |

Before any write: read and save the current object's JSON, write the inverse request next to it, get approval, apply, test, keep both files in the project notes.

## Home Assistant UniFi integration

- Needs a **local** UniFi account; Ubiquiti SSO cloud users do not work; EA/RC Network versions are unsupported; admin role recommended for controls [V].
- Provides device trackers, sensors, PoE port switches, port power-cycle buttons, client block, WLAN, traffic/firewall policy switches [V].
- Disable the entities you will not use, especially PoE switches for critical ports, and keep them out of voice exposure.
