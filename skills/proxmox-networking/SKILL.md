---
name: proxmox-networking
description: Proxmox VE host networking - Linux bridges (vmbr) vs Open vSwitch, VLAN-aware bridges and VLAN tags or trunks on guest NICs, bonds (LACP 802.3ad vs active-backup), MTU and jumbo frames, /etc/network/interfaces with ifupdown2 (interfaces.new, Apply Configuration, ifreload -a), NIC name changes and pve-network-interface-pinning, separate corosync, Ceph and migration networks, SDN zones (Simple, VLAN, QinQ, VXLAN, EVPN), VNets, fabrics, IPAM and DHCP, and safe remote changes without losing access. Use when changing or debugging Proxmox networking.
---

# Proxmox Networking

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release-network
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.0 (2025-08-05): SDN fabrics (OpenFabric, OSPF), pve-network-interface-pinning, VirtIO vNIC MTU unset now inherits bridge MTU, NIC renames possible on upgrade. PVE 9.2 (2026-05-21): WireGuard and BGP fabrics, route maps/prefix lists, IPv6 EVPN underlay, SDN dry-run."
  - kind: external_fact
    subject: pve-sdn-support-status
    source_url: https://pve.proxmox.com/pve-docs/chapter-pvesdn.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Admin guide 9.2.12: core SDN (zones, VNets) fully supported; IPAM incl. DHCP (dnsmasq) and FRR-based routing/controllers (EVPN) are tech preview; config in /etc/pve/sdn, applied as pending changes; needs 'source /etc/network/interfaces.d/*'."
-->

## Overview

A Proxmox node's network is **how you reach it**: a bad bridge edit on a remote node locks you out and, in a cluster, can drop quorum and fence the node. Stage the change, keep a console, and separate traffic classes (management, corosync, storage, migration, guests).

Labels: **[V]** checked against the Proxmox admin guide 9.2.12 or roadmap on 2026-09-27; **[I]** inferred, re-verify. Current release **PVE 9.2** [V].

## When to use

- Adding a bridge, VLAN, bond or MTU change on a node; tagging a guest NIC.
- Planning networks for corosync, Ceph, migration or replication.
- Symptoms: node unreachable after a reboot or upgrade, VLAN not passing, no network in a guest.
- SDN: zones, VNets, subnets, DHCP/IPAM, fabrics.
- A node or guest lost connectivity after an edit, an upgrade (NIC renamed) or a switch change.

**Not for:** any firewall work, host, VNet or guest-side (`proxmox-security-ops`); corosync link and quorum tuning (`proxmox-cluster-ha`); Ceph pool sizing (`proxmox-storage`); switch/router config (`unifi-network` or the vendor's skill). Guardrails from `proxmox-admin` apply.

## Safe remote change procedure

1. **Console first**: confirm out-of-band access (IPMI/iDRAC/iLO/KVM, or physical) or a second path on another NIC before touching the management bridge.
2. **Read**: `cat /etc/network/interfaces`, `ip -br a`, `ip -d link show`, `bridge vlan show` [I]. Save a copy and keep its path in the same shell: `B=/root/interfaces.bak.$(date +%F-%H%M); cp /etc/network/interfaces "$B"`.
3. **Stage**: GUI edits go to `/etc/network/interfaces.new` and are not live until applied [V]. Review with `diff -y /etc/network/interfaces /etc/network/interfaces.new` [V].
4. **Dead-man switch** (no built-in rollback exists) [I]: before applying, schedule a revert, with the double quotes resolving `$B` now: `systemd-run --unit=net-revert --on-active=5min /bin/sh -c "cp '$B' /etc/network/interfaces && rm -f /etc/network/interfaces.new && ifreload -a"`. **Check it before applying**: `systemctl list-timers net-revert.timer` shows it armed and `systemctl cat net-revert.service` shows the real backup path; if not, stop and fix it [I 2026-09-27]. Cancel with `systemctl stop net-revert.timer` once you are back in. Removing `interfaces.new` stops a later reboot re-applying the bad config [V: pvenetcommit].
5. **Apply** (two separate paths) [V 2026-09-27]: GUI edits staged in `interfaces.new` -> **Apply Configuration**, which moves `.new` into place and reloads; direct edits to `/etc/network/interfaces` -> `ifreload -a` (ifupdown2, default since PVE 7). `ifreload -a` does not commit `interfaces.new`. Rebooting also applies `interfaces.new` via `pvenetcommit` [V].
6. **Verify** from outside: ping the node, open the GUI, `pvecm status` in a cluster.
7. In a cluster with HA, disarm HA around changes to corosync links (`proxmox-cluster-ha`).

## Bridges: Linux vs OVS

| | Linux bridge (default) | Open vSwitch |
|---|---|---|
| Install | built in | `apt install openvswitch-switch` [V] |
| VLANs | `bridge-vlan-aware yes` | native OVS VLANs [V] |
| Use when | Nearly always; SDN VLAN zones use it [V] | You need OVS-specific features (RSTP, OVS bonds, existing OVS tooling) [I] |

Prefer **VLAN-aware** Linux bridges over "traditional" per-VLAN bridges (`vmbr0v5` + `eno1.5`) [V]:

```
auto vmbr0
iface vmbr0 inet manual
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094

# host management on VLAN 10
auto vmbr0.10
iface vmbr0.10 inet static
    address 192.0.2.10/24
    gateway 192.0.2.1
```

Guest NIC: `qm set <vmid> --net0 virtio,bridge=vmbr0,tag=20` (access) or `trunks=20;30` (trunk) [V]; containers use `pct set <ctid> --net0 name=eth0,bridge=vmbr0,tag=20,ip=dhcp` [I]. The switch port must trunk those VLANs.

## Bonds

| Mode | Use | Switch |
|---|---|---|
| `802.3ad` (LACP) | Recommended when the switch supports LACP [V]; `bond-xmit-hash-policy layer2+3` (or `layer3+4`) | LACP on a port-channel/LAG, across MLAG stacks only if supported |
| `active-backup` | Default otherwise [V]; two unmanaged switches | none |
| `balance-alb`/`balance-tlb` | **Not** with a bridge carrying guests [V] | - |

For corosync, use a dedicated NIC plus a second corosync **link** rather than a bond; if LACP carries corosync, set `bond-lacp-rate fast` on both ends [V].

## MTU and jumbo frames

- Set MTU on the physical NIC, the bond and the bridge together, and on every switch hop; test with `ping -M do -s 8972 <peer>` for 9000 [I].
- Since PVE 9, a VirtIO vNIC with MTU unset **inherits the bridge MTU** (previously 1500) [V]; set `mtu=1500` on guests that must stay at 1500.
- Overlays: VXLAN needs 50 bytes less than the underlay; QinQ needs 4 bytes [V].
- Use jumbo frames on storage/migration networks only when every hop supports them [I]; keep management and corosync at 1500.

## Traffic separation

| Network | Where set | Notes |
|---|---|---|
| Corosync | `pvecm create/add --link0/--link1` | Own physical NIC, low latency (<5 ms), no storage traffic [V] |
| Ceph public/cluster | `pveceph init --network / --cluster-network`, **initial setup only**: re-running it on an existing cluster silently ignores most options [V 2026-09-27] | 10 Gbps+ dedicated [V]; moving an existing cluster's networks is a planned MON/OSD migration, not a re-init [I] |
| Migration | `/etc/pve/datacenter.cfg`: `migration: secure,network=10.1.2.0/24` | CIDR with exactly one IP per node [V]; also carries offline disk data [V] |
| Replication | datacenter option since 9.0 (was the migration network) [V] | ZFS replication traffic |

## NIC names and upgrades

Kernel updates can rename NICs (e.g. 8 to 9 upgrade) [V]. PVE 9 accepts alternative names in config [V]; pin permanent names first with `pve-network-interface-pinning generate [--interface enp1s0 --target-name <name>]`; pinning takes effect after a reboot [V]. After any kernel upgrade on a remote node, check `ip -br link` before the reboot window closes.

## SDN (detail: [references/sdn.md](references/sdn.md))

- Status in the 9.2 admin guide [V]: **core SDN (zones, VNets) fully supported**; **IPAM/DHCP and FRR routing/EVPN controllers are tech preview**.
- Zones: Simple (isolated/NAT), VLAN, QinQ, VXLAN, EVPN [V]. Fabrics (OpenFabric, OSPF in 9.0; WireGuard, BGP in 9.2) build routed underlays, e.g. a Ceph full mesh [V].
- Changes are **pending** until applied cluster-wide (Datacenter > SDN > Apply); 9.2 adds dry-run [V].

## Anti-patterns

| Don't | Why |
|---|---|
| Edit the management bridge remotely with no console or revert timer | One typo locks you out |
| `ifdown`/`ifup vmbr0` (or `systemctl restart networking` [I]) on a live node | Guests on the bridge are detached and not reattached [V] |
| Corosync on the storage or guest network | Latency spikes break quorum and trigger fencing |
| `balance-alb`/`balance-rr` bonds under a guest bridge | MAC flapping, dropped guest traffic |
| LACP on the host without a matching switch LAG | Link flaps or half the traffic lost |
| Jumbo frames on one side only | Silent drops of large packets |
| Trusting unencrypted VXLAN across sites | VXLAN has no encryption [V]; use a VPN or the WireGuard fabric |
| Hand-editing `/etc/network/interfaces.d/sdn` | SDN regenerates it; edit via SDN config |
| Leaving vNIC MTU unset on a jumbo bridge for guests expecting 1500 | 9.x now inherits the bridge MTU |
| Upgrading kernels remotely without pinning NIC names | Renamed NICs leave the node offline |
