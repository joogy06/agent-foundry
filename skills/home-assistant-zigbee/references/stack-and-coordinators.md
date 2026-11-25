# Zigbee stacks and network-attached coordinators

Labels: [V] verified 2026-09-27 against the cited source; [I] re-verify.

## Zigbee2MQTT on HA OS

1. Install the **Mosquitto broker** app; create a dedicated HA user for MQTT (not an admin), password in the app/secret store [I].
2. Install the **Zigbee2MQTT** app. Minimum config (Z2M `configuration.yaml`, or the app's options):

```yaml
mqtt:
  server: mqtt://core-mosquitto:1883     # HA OS app hostname [I]
  user: <mqtt_user>
  password: '!secret.yaml <key-name>'    # key in secret.yaml beside this file; quotes required [V mqtt docs]
homeassistant:
  enabled: true                           # MQTT discovery into HA; needs HA's MQTT integration set up [I]
serial:
  port: tcp://<coordinator-ip>:<port>    # [V] syntax; port from the coordinator's web UI
  adapter: ember                          # [V] EFR32/EmberZNet; ezsp deprecated
advanced:
  channel: 20                             # set BEFORE first start; default 11 [V]
  network_key: GENERATE                   # Z2M writes the random key back [V]
  pan_id: GENERATE
  ext_pan_id: GENERATE
availability:
  enabled: true                           # off by default [V]
  active: {timeout: 10}                   # minutes, mains devices [V default]
  passive: {timeout: 1500}                # minutes, battery devices [V default]
frontend:
  enabled: true
```

3. After the first start, back up the **whole Z2M data directory** (`data/`; named `zigbee2mqtt/` under the HA app) [V FAQ]: it holds `configuration.yaml` with the generated `network_key`/`pan_id`/`ext_pan_id`, `coordinator_backup.json` [V FAQ] and the device database. Keys alone are not enough. Serial-port options (`baudrate`, `rtscts`) do not apply to most `tcp://` coordinators; the coordinator handles its own UART [I]. For USB EFR32 sticks: ZBT-2 needs `baudrate: 460800` and `rtscts: true`; ZBDongle-E uses `rtscts: false` [V].

Other adapter values: `zstack` (TI CC2652/CC1352), `deconz` (ConBee/RaspBee), `zigate`, `zboss` (Nordic) [V].

## ZHA

Settings > Devices & services > Add integration > Zigbee Home Automation; choose "enter manually", radio type EZSP for EFR32, path `socket://<coordinator-ip>:<port>` [V]. Use "Smart" channel selection or set 15/20/25 [V]. Change unavailable timeouts under ZHA options (defaults 2 h mains / 6 h battery) [V].

## Network-attached coordinators (traits)

| Trait | Why it matters | Check |
|---|---|---|
| Wired link (Ethernet/PoE) | Serial-over-IP handles loss poorly; Wi-Fi links flap [V] | Coordinator shows Ethernet as active interface |
| Fixed address | The stack config holds `tcp://ip:port` | DHCP reservation or static IP (`unifi-network`) |
| Reachable port | HA to coordinator TCP must pass VLAN/firewall rules | `nc -vz <ip> <port>` from the HA host [I] |
| One client | Two stacks on one socket corrupt the conversation [I] | Stop the old stack before starting a new one |
| Firmware type visible | Web UI shows Zigbee NCP vs Thread RCP | Screenshot/record version before any change |
| Power independent of HA | Coordinator should ride through HA reboots, and vice versa | Reboot each; the network resumes with no re-pair |
| Survives power loss | Mesh routers + coordinator + HA host + switch on a UPS | Later phase; note it |

### Dated product evidence (re-verify before relying)

- **SONOFF Dongle Max (Dongle-M)**: EFR32MG24 radio + ESP32, Ethernet/PoE/Wi-Fi/USB, Zigbee or Thread firmware, optional dual-network mode described as experimental [I, from a consumer project brief 2026-09-27; vendor page did not render]. Default Zigbee TCP port commonly 6638 [I]: read it from the web UI.
- **SMLIGHT SLZB-06**: CC2652P (Z-Stack, `adapter: zstack`) Ethernet/PoE coordinator; SLZB-06M is the EFR32MG21 variant (`ember`) [I, training knowledge; vendor manual URL 404 on 2026-09-27].
- Port 6638 is the example in Z2M's EmberZNet docs (`tcp://...:6638`) [V].

## Migration paths

| From -> To | Path | Re-pair? |
|---|---|---|
| HA host A -> host B, same network coordinator | Restore HA backup on B (or copy the full Z2M data dir), stop A first, same `tcp://` | No [V FAQ: move the data dir, update the port] |
| Z2M adapter X -> Y, same family (ember->ember, zstack->zstack) | Keep the full data dir, copy the old adapter's IEEE address to the new one, change `port` | No, when the IEEE copy succeeds [V FAQ] |
| Z2M across families (zstack <-> ember) | Z2M says results may vary; test devices afterwards [V FAQ] | Maybe |
| ZHA radio X -> Y | ZHA "Migrate radio" wizard (Silicon Labs, TI, ConBee) [V] | No |
| ZHA <-> Z2M | Different device databases; plan it as a new network [I] | Yes, usually |
