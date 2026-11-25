# HA manager in PVE 9: rules, fencing, maintenance, CRS

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-ha-manager-docs
    source_url: https://pve.proxmox.com/pve-docs/chapter-ha-manager.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Admin guide 9.2.12: resource options failback (default 1), auto-rebalance (default 1), max_restart/max_relocate (default 1); rules in /etc/pve/ha/rules.cfg; disarm-ha freeze|ignore and arm-ha; node-maintenance enable|disable; shutdown_policy conditional (default)|migrate|failover|freeze; CRS basic (default)|static|dynamic."
-->

Labels: [V] = Proxmox admin guide 9.2.12 or roadmap, checked 2026-09-27; [I] = inferred, re-verify.

## Resource commands [V]

```bash
ha-manager add vm:100 --state started --max_restart 1 --max_relocate 1
ha-manager set vm:100 --state stopped        # explicit; qm stop/start also only set the HA requested state
ha-manager migrate vm:100 node2              # live
ha-manager relocate vm:100 node2             # stop, move, start
ha-manager status
ha-manager remove vm:100
```

On an HA-managed guest, `qm start`/`qm stop` (and the GUI buttons) are forwarded to HA and only set the requested state to `started`/`stopped`; HA keeps enforcing that state [V 2026-09-27: ha-manager guide]. `ha-manager set` makes the intent explicit.

Resource options: `failback` (default 1: return to the highest-priority node), `auto-rebalance` (default 1: may be moved by CRS rebalancing), `max_restart`, `max_relocate` [V].

## HA rules (replacing groups)

- Groups deprecated in 9.0 and migrated automatically once all nodes run 9 [V]. Old group semantics map as: `restricted 1` -> strict node rule; priorities -> `node:prio` pairs; `nofailback 1` -> resource `failback 0` [V/I].
- Node affinity [V]:

```bash
ha-manager rules add node-affinity pin-db --resources vm:100 --nodes node1 --strict 1
ha-manager rules add node-affinity avoid-n3 --affinity negative --resources ct:200,vm:300 --nodes node3
ha-manager rules add node-affinity cascade --resources vm:400,ct:500 --nodes "node1:2,node2:1,node3:1,node4"
```

- Resource affinity (strict by default) [V]:

```bash
ha-manager rules add resource-affinity web-db --affinity positive --resources vm:100,vm:200
ha-manager rules add resource-affinity shards --affinity negative --resources vm:200,ct:300
```

- Overlapping positive rules merge; members of a positive rule inherit each other's negative rules [V]. Negative constraints are applied before positive ones [V]. Rules are feasibility-checked; infeasible rules are reported [V].
- Feasibility tests [V]: a resource is in at most one node-affinity rule; negative node rules take no priorities and cannot list all nodes; a resource-affinity rule needs 2+ resources; a negative one cannot list more resources than nodes; the same resources cannot be both together and apart. Failing rules are **disabled** until fixed [V].

## Fencing

- Each node's LRM holds a watchdog while it has active HA services; the CRM master holds one too [V]. On quorum loss the watchdog is not fed and the node resets after 60 s [V].
- Default watchdog: `softdog`; hardware watchdog modules are blocked by default and selected in `/etc/default/pve-ha-manager` [V].
- A node with no active HA services closes its watchdog and does not self-fence [V].

## Maintenance patterns

| Scenario | Do |
|---|---|
| Reboot one node for updates | `node-maintenance enable <node>` -> wait for guests to leave -> reboot -> `disable` [V]; or `shutdown_policy=migrate` [V] |
| Many nodes down at once | `shutdown_policy=failover` so services recover elsewhere if a node stays down [V] |
| Corosync or switch work (9.2+) | `ha-manager crm-command disarm-ha freeze` -> work -> `arm-ha` [V]; `ignore` if you must move guests by hand [V] |
| Upgrade packages | Keep HA armed or wait for migrations to finish; disable automatic rebalancing (9.2 known issue for upgrades from pve-ha-manager < 5.2.4, not enterprise repo) [V] |

Maintenance mode survives reboot and must be disabled explicitly [V]. While disarmed, nothing is recovered: keep the window short [V].

## CRS (Cluster Resource Scheduler)

- Modes: `basic` (guest count; default), `static` (configured CPU/RAM), `dynamic` (measured usage) [V]; set in Datacenter > Options > Cluster Resource Scheduling.
- 9.2: dynamic mode can automatically rebalance HA guests with tunable thresholds [V]; roadmap extends to non-HA guests [V].
- Opt a guest out of rebalancing with `auto-rebalance 0` [V].

## Replication with HA

- HA plus ZFS replication is allowed, but a failover starts the guest from the last replicated snapshot: data since then is lost [V].
- Replication jobs need `VM.Replicate` on `/vms/<vmid>` since 9.0 [V]; a separate replication network can be set in datacenter options since 9.0 [V].
- A failed job retries every 30 minutes [V].

## Guest stuck on a dead node

- **HA-managed guest: never move its config by hand.** HA fences the node and recovers the guest itself, with cluster-wide locking [V: pmxcfs guide, 2026-09-27]. If it does not, fix quorum or fencing (`ha-manager status`), do not bypass them.
- **Non-HA guest** (shared disks only, or ZFS-replicated): a manual config move bypasses Proxmox's locking, so two nodes could write one disk [V: pmxcfs guide, 2026-09-27]. Only with every check passed:
  1. Prove the dead node is **powered off or fenced** (IPMI/iDRAC power status, pulled power), not merely unreachable [V].
  2. `pvecm status` on the survivor shows quorum; `pvecm expected 1` only if quorum cannot be restored, and make no other cluster changes while it is set [V: pvesr guide].
  3. Confirm the guest has no local disk or device that exists only on the dead node (`qm config <vmid>`); a replicated guest needs a replica on the target, and loses data written since its last sync [V].
  4. Move only that guest's config, then start it: `mv /etc/pve/nodes/<dead>/qemu-server/<vmid>.conf /etc/pve/nodes/<alive>/qemu-server/` (containers: `lxc/`), `qm start <vmid>` [V].
- Guests with unreplicated local disks cannot be recovered this way: wait for the node or restore from backup [V].
