---
name: proxmox-admin
description: Proxmox VE (PVE) hypervisor administration and family router - release line (PVE 9.x on Debian 13 Trixie), web UI vs CLI tools (qm, pct, pvesm, pvecm, ha-manager, pvesh, vzdump, proxmox-backup-client), /etc/pve pmxcfs config layout, and the shared-host guardrails every Proxmox change follows (read-only listing first, never touch other guests, a restorable backup before disk or storage changes, confirm the node). Routes VMs, LXC containers, storage, networking, clusters and HA, backups and PBS, GPU passthrough, and security or upgrades to the proxmox-* child skills.
---

# Proxmox Admin (family router)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Proxmox VE 9.2 released 2026-05-21 on Debian 13.5 Trixie, kernel 7.0, QEMU 11.0, LXC 7.0; 9.1 released 2025-11-19 (Debian 13.2)."
  - kind: external_fact
    subject: pve-cli-tools
    source_url: https://pve.proxmox.com/pve-docs/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "qm (VMs), pct (containers), pveam (templates), pvesm (storage), pvecm (cluster), ha-manager (HA), pvesh (API shell), vzdump (backup); cluster config lives in /etc/pve (pmxcfs)."
-->

## Overview

Proxmox VE is a Debian-based hypervisor for KVM VMs and LXC containers, driven by a web UI and a REST API that the CLI tools wrap. A host is often **shared**: the main risk is an action that touches **another** guest, the host, or the cluster. This skill holds the rules every Proxmox task follows and routes detail to a child skill.

Labels: **[V]** checked against the cited source on 2026-09-27; **[I]** inferred or from memory, re-verify before relying on it.

## When to use

- Any Proxmox VE task: apply the guardrails below, then route to the child skill.
- Orientation: which tool does what, where a setting lives, which release a host runs.

**Not for:** what runs inside a guest (the guest's own skill, e.g. `home-assistant`); switch/VLAN/router config (`unifi-network`); generic Debian host admin (`ubuntu-server-admin` patterns apply).

## Routing table

| Task | Skill |
|---|---|
| VMs with `qm`: create (ISO, qcow2, cloud-init), templates and clones, CPU/disk/BIOS options, resize or move disks, USB/PCI basics, live migration, import from VMware ESXi or Hyper-V | `proxmox-vm` |
| Containers with `pct`: templates (`pveam`), unprivileged vs privileged, idmap and bind mounts, Docker-in-LXC, device passthrough, OCI images, LXC vs VM choice | `proxmox-lxc` |
| Storage with `pvesm`: ZFS, LVM/LVM-thin, directory, NFS/CIFS, Ceph, content types, thin provisioning | `proxmox-storage` |
| Networking: Linux bridges (vmbr), VLAN-aware bridges, bonds, SDN | `proxmox-networking` |
| Clusters with `pvecm`, quorum, corosync, QDevice, HA with `ha-manager`, replication | `proxmox-cluster-ha` |
| Backups: `vzdump`, backup jobs, Proxmox Backup Server (PBS), `proxmox-backup-client`, restores, **snapshots vs backups** (a snapshot dies with its disk; only an off-host backup survives) | `proxmox-backup` |
| GPU and PCIe passthrough: IOMMU, vfio, iGPU/dGPU, SR-IOV, vGPU | `proxmox-gpu-passthrough` |
| Security and operations: users, roles and API tokens, 2FA, PVE firewall, certificates, updates and major upgrades (`pve8to9`), repositories, monitoring | `proxmox-security-ops` |

When a task spans two rows (e.g. passing an iGPU into an LXC), start with the skill that owns the guest type and follow its pointer to the other.

## Shared-host guardrails (the family's common core)

1. **Confirm the node.** Run `hostname`, `pvesh get /nodes` [I] and, on a cluster, `pvecm status`; state which node you are on before any change. `qm`/`pct` act on the local node; "unable to find configuration file" usually means the guest lives on another node.
2. **Read before write.** List first and show the output: `qm list`, `pct list`, `pvesm status`, `pvesh get /cluster/resources --type vm` [I], `pvesh get /cluster/nextid` [I], and `ha-manager status`. Record which guests exist, their states, and which are HA-managed: drive HA guests through `ha-manager` (`proxmox-cluster-ha`), because on an HA guest `qm`/`pct` start/stop set the HA requested state, which HA then enforces [V 2026-09-27].
3. **One named target.** Every mutating command carries an explicit VMID/CTID that you created or were given. No `--all`, pool-wide or wildcard actions on a shared host.
4. **Never touch other guests**: no stop, start, migrate, resize, snapshot, backup or restore of an ID outside your scope.
5. **Back up before destructive change.** Before disk or storage work that can lose a volume, take a `vzdump` of **your** guest to another storage or PBS and confirm it is listed and restorable. A snapshot is no substitute: it needs storage snapshot support [V: pve-storage docs, 2026-09-27] and dies with that storage; use it only as a quick rollback point for config or in-guest changes. Detail: `proxmox-backup`.
6. **Ask before host-level changes**: rebooting the node, editing `/etc/network/interfaces` or bridges, adding/removing storage, kernel or bootloader parameters, installing host packages, changing cluster or HA config.
7. **Tag and protect what you own**: `--tags <owner-tag>` [I] so listings show ownership; `--protection 1` [I] blocks accidental removal of long-lived guests.
8. **Destructive verbs need explicit confirmation**, naming the ID, even inside your scope: `qm|pct destroy` (with `--purge` or `--destroy-unreferenced-disks`, which removes every disk carrying that ID on all enabled storages [I]), `qm rollback`/`pct rollback`, `qm disk move --delete 1`, `qm stop` (a hard power-off; prefer `qm shutdown`), `qm shutdown --forceStop 1` and `pct migrate --restart` (both force-kill after a timeout [V]), and `qm disk rescan` without `--vmid` (rewrites every VM's config) [I].
9. **Never unlock blindly.** A "VM is locked (backup|snapshot|migrate)" lock belongs to a task; run `qm unlock`/`pct unlock` only after the Tasks log shows no such task running.
10. **Check capacity** (`pvesm status`, `free -h`) before allocating; over-committing RAM or disk starves the neighbours.
11. **Show the plan**, as the exact commands, before running a mutating batch.

## Orientation

| Surface | Use for |
|---|---|
| Web UI, `https://<node>:8006` [I] | Discovery, one-off changes, wizards |
| `pvesh get|create|set|delete <api-path>` | API calls from the shell; `pvesh get` is read-only [I] |
| REST API `/api2/json/...` with an API token | Automation |

CLI tools per scope (`qm`, `pct`, `pvesm`, `pvecm`, `ha-manager`, `vzdump`, `proxmox-backup-client`, `pveversion -v`): [references/orientation.md](references/orientation.md).

**Config** lives in `/etc/pve` (**pmxcfs**), replicated to every node [V]; files that sit outside it (e.g. `/etc/subuid`, `/etc/network/interfaces`) are node-local [I]. Prefer `qm set`/`pct set`/`pvesh` over hand-editing; copy a file before editing it, and never edit without quorum (it goes read-only). Paths: [references/orientation.md](references/orientation.md).

More orientation (CLI tools, config paths, repositories, logs): [references/orientation.md](references/orientation.md).

## Release line (verified 2026-09-27)

- Current: **PVE 9.2**, released 2026-05-21, Debian 13.5 Trixie base, kernel 7.0, QEMU 11.0, LXC 7.0 [V: pve.proxmox.com/wiki/Roadmap].
- **arm64**: PVE 9.2 for arm64 released 2026-08-05; x86 recipes (SeaBIOS, `q35`, `x86-64-v*` CPUs) do not apply there [V: Roadmap, fetched 2026-09-27]. Check `dpkg --print-architecture` [I].
- Previous: 9.1 (2025-11-19, Debian 13.2) [V]. The 9.x line is Debian 13; 8.x was Debian 12 Bookworm [I].
- Always read the host's actual version with `pveversion` before applying version-specific advice.

## Anti-patterns

| Don't | Why |
|---|---|
| Act before listing guests and naming the node | Wrong node or colliding ID changes someone else's guest |
| `--all`, pool-wide or wildcard actions on a shared host | Touches guests outside your scope |
| Disk or storage work with only a snapshot, or none | A snapshot dies with its storage; only a restorable backup elsewhere brings the guest back |
| Hand-edit `/etc/pve` files without a copy | pmxcfs replicates the mistake to every node at once |
| Reboot a node to fix one guest | Takes every guest on it down; ask first |
| Apply 8.x (Bookworm) advice to a 9.x (Trixie) host unchecked | Package names, repos and defaults changed; check `pveversion` |
| `qm unlock` a guest whose backup or migration is still running | Breaks that task and can corrupt its state |
| `qm stop`/`qm start` an HA-managed guest expecting a one-off action | They set the HA requested state (`stopped`/`started`) that HA then enforces; use `ha-manager set` to make it explicit [V 2026-09-27] |
