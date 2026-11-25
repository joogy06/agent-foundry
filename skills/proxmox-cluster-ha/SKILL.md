---
name: proxmox-cluster-ha
description: Proxmox VE clustering and high availability - pvecm create/add, corosync links (link0/link1, knet) and redundancy, quorum, the 2-node problem and QDevice (corosync-qnetd), pvecm expected, ha-manager resources and HA rules (node affinity and resource affinity replacing HA groups in PVE 9), fencing via watchdog (softdog), disarm-ha/arm-ha, maintenance mode and shutdown policy, CRS load balancing, live vs offline migration, ZFS storage replication (pvesr), removing a node (pvecm delnode), and split-brain or lost-quorum recovery. Use when building, changing or repairing a Proxmox cluster or HA setup.
---

# Proxmox Cluster and HA

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release-ha
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.0 (2025-08-05): HA rules (node affinity, resource affinity); HA groups deprecated and auto-migrated once all nodes run 9; nofailback replaced by per-resource failback; VM.Replicate privilege; dedicated replication network. PVE 9.2 (2026-05-21): dynamic CRS load balancing, disarm-ha/arm-ha, token_coefficient 125 ms for new clusters."
  - kind: external_fact
    subject: pve-cluster-ha-docs
    source_url: https://pve.proxmox.com/pve-docs/chapter-ha-manager.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Admin guide 9.2.12: ha-manager rules add node-affinity|resource-affinity; node affinity non-strict by default, resource affinity strict; watchdog self-fence after 60 s; failover ~2 min; QDevice supported for even node counts, discouraged for odd; corosync needs <5 ms latency; pvecm delnode only after the node is powered off for good."
-->

## Overview

A cluster shares config through `/etc/pve` (pmxcfs) and is only writable **with quorum** (more than half the votes). HA adds automatic recovery, and it recovers by **fencing**: a node that loses quorum with active HA resources resets itself via watchdog so another node can safely start its guests. Treat quorum and the corosync network as the thing everything else rests on.

Labels: **[V]** checked against the Proxmox admin guide 9.2.12 or roadmap on 2026-09-27; **[I]** inferred, re-verify. Current release **PVE 9.2** [V].

## When to use

- Creating or joining a cluster; adding corosync links; adding a QDevice.
- Making guests HA, writing HA rules, planning maintenance, choosing a shutdown policy.
- Migrating guests; setting up ZFS replication.
- Removing a node; recovering from lost quorum or split brain.
- Symptoms: `cluster not ready - no quorum?`, `/etc/pve` read-only, a node shown offline, `pvecm add` fails, an HA resource in `error`.

**Not for:** corosync/migration NIC and bond config (`proxmox-networking`); shared-storage choice and Ceph sizing (`proxmox-storage`); backup jobs (`proxmox-backup`); upgrade procedures such as `pve8to9` (`proxmox-security-ops`). Guardrails from `proxmox-admin` apply.

## Hard rules

1. **Never run a 2-node cluster without a QDevice.** With 2 votes, one node down means no quorum: `/etc/pve` goes read-only and HA cannot recover anything [V]. A QDevice (a small external host running `corosync-qnetd`) adds the third vote [V].
2. HA needs **3+ votes** (3 nodes, or 2 nodes + QDevice) [V].
3. Corosync gets its **own physical NIC**, latency under 5 ms, and a second link [V].
4. Hostname and IP are fixed once a node joins [V]; set them before `pvecm add`.
5. A removed node must **never** come back on the cluster network with its old config [V]: reinstall it.
6. Before corosync or network maintenance on an HA cluster: `ha-manager crm-command disarm-ha freeze` and confirm `ha-manager status` shows disarmed (it waits for running fencing, recovery or migration) [V]; while disarmed a real node failure is not handled; `arm-ha` only on a healthy cluster (9.2+).

## Cluster lifecycle [V]

```bash
pvecm create <name> --link0 10.10.10.1 [--link1 10.20.20.1]   # first node
pvecm add <existing-node-ip> --link0 <local-ip> [--link1 <ip>] # on each joiner (empty node, no guests) [I: empty]
pvecm status          # quorum, votes, links
pvecm nodes
corosync-cfgtool -s   # per-link status [I]
```

- Links: up to 8 knet links; higher `priority` is preferred [V: priority example]. Use a different switch for link1.
- Votes: each node 1; quorum = floor(votes/2)+1 [I].
- QDevice [V]: `apt install corosync-qnetd` on the external host; `apt install corosync-qdevice` on all nodes; `pvecm qdevice setup <qdevice-ip>`; remove with `pvecm qdevice remove` (required before removing a node). For odd node counts the QDevice gets N-1 votes and becomes a near single point of failure: discouraged [V].

Detail and recovery: [references/cluster-ops.md](references/cluster-ops.md).

## HA in PVE 9: resources and rules (detail: [references/ha.md](references/ha.md))

- Resource: `ha-manager add vm:100 --state started [--max_restart 1 --max_relocate 1]` [V].
- **HA groups are deprecated**; they auto-migrate to **node affinity rules** once every node runs 9.x [V]. `nofailback` became the per-resource `failback` flag [V].

| Rule | Purpose | Default strictness | Example [V] |
|---|---|---|---|
| node-affinity | Prefer or restrict resources to nodes, with priorities | non-strict (prefers) | `ha-manager rules add node-affinity r1 --resources vm:100 --nodes "node1:2,node2:1" [--strict 1]` |
| resource-affinity positive | Keep resources together | strict | `ha-manager rules add resource-affinity keep --affinity positive --resources vm:100,vm:200` |
| resource-affinity negative | Keep resources apart | strict | `... --affinity negative --resources vm:200,ct:300` |

Rules live in `/etc/pve/ha/rules.cfg` [V]. Use a **strict** node rule when a guest depends on local storage, a local NIC or passthrough hardware present only on some nodes [V].

## Fencing and requirements

- Watchdog: hardware (IPMI etc.) if configured, else Linux `softdog` [V]. A node without quorum and with active HA services self-resets after about 60 s [V]; typical failover is about 2 minutes [V].
- HA guests must use **shared storage** (Ceph, NFS, iSCSI/LVM) or ZFS replication (accepting loss since the last sync) [V], and only bridges and devices present on all eligible nodes [V].

## Maintenance

| Goal | Command / setting |
|---|---|
| Drain one node for reboot | `ha-manager crm-command node-maintenance enable <node>`; `disable` after [V] |
| Reboot behaviour | `datacenter.cfg` `ha: shutdown_policy=migrate` (default `conditional`) [V] |
| Cluster-wide network/corosync work | `disarm-ha freeze` (or `ignore` to move guests by hand), then `arm-ha` [V] |
| Balance load | CRS mode basic/static/dynamic; 9.2 dynamic mode can auto-migrate HA guests [V] |

Known 9.2 issue [V]: upgrading from pve-ha-manager before 5.2.4 (not enterprise repo) can stall if HA is disarmed mid-migration; keep HA armed during upgrades, re-arm to clear it. HA resource in `error`: `ha-manager set vm:<id> --state disabled`, fix the cause, then `--state started` [I].

## Migration and replication

| Kind | How | Needs |
|---|---|---|
| Live (VM) | `qm migrate <vmid> <node> --online` [V] | Shared storage, or `--with-local-disks` (copies disks) [I]; same CPU vendor, a CPU type both nodes support [V] |
| Restart (CT) | `pct migrate <ctid> <node> --restart` [I] | Containers do not live-migrate [I] |
| Offline | stop, then `qm migrate` | Copies local disks over the migration network |
| Replicated | `pvesr create-local-job 100-0 <node> --schedule "*/15"` [I] | ZFS local storage with the same storage ID on both nodes [V]; 1 min to 1 week intervals [V]; migrate sends only the delta and flips direction [V] |

## Anti-patterns

| Don't | Why |
|---|---|
| Two nodes without a QDevice | One failure freezes `/etc/pve` and HA; `expected 1` hacks invite split brain |
| QDevice on one of the cluster nodes or a guest on the cluster | It fails with the node it should arbitrate |
| Corosync on a busy storage/guest network or over a WAN | Jitter causes quorum loss and fencing reboots |
| HA-manage a guest on local-only storage without replication or a strict node rule | Recovery starts it on a node without its disk |
| Keep writing HA groups in PVE 9 | Deprecated; migrate to node affinity rules |
| `pvecm expected 1` on a partition while the other side may be alive | Two writable halves: split brain |
| Power on a removed node unchanged | Corrupts cluster state |
| Remove a node that still has replication jobs or is the QDevice's peer | Jobs become irremovable; QDevice config breaks |
| Rewire corosync on an armed HA cluster | Nodes self-fence mid-change |
| Change a node's hostname or IP after joining | Unsupported; breaks cluster config |
