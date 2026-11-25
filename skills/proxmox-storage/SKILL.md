---
name: proxmox-storage
description: Proxmox VE storage with pvesm and /etc/pve/storage.cfg - choosing local, directory, LVM, LVM-thin, ZFS, NFS/CIFS, iSCSI, Ceph RBD or CephFS; snapshot and thin-provisioning support per type, content types (images, rootdir, iso, vztmpl, backup, snippets); ZFS pool layout, ashift, volblocksize, ARC sizing, special vdev; hyperconverged Ceph sizing (3+ nodes, OSD per disk, networks); SMART disk health, replacing a failed ZFS disk (zpool replace, proxmox-boot-tool), trim/discard, consumer SSD wear. Use when adding, sizing or repairing Proxmox storage.
---

# Proxmox Storage

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release-storage
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.2 (2026-05-21): ZFS 2.4, Ceph Squid 19.2.3 and Tentacle 20.2.1, Tentacle the default for new Ceph installs. PVE 9.0 (2025-08-05): snapshots as volume chains (tech preview) on thick LVM and Directory/NFS/CIFS; GlusterFS dropped."
  - kind: external_fact
    subject: pve-storage-type-matrix
    source_url: https://pve.proxmox.com/pve-docs/chapter-pvesm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Admin guide 9.2.12 (2026-09-18): storage type table (level/shared/snapshots/stable) and per-backend content types; BTRFS tech preview; ZFS ARC default 10% of RAM capped at 16 GiB since 8.1; Ceph needs 3+ nodes, one OSD per disk, 10 Gbps+ dedicated network."
-->

## Overview

Pick storage by three questions: **does it need to be shared** (live migration and HA without copying disks), **does it need snapshots**, and **what content goes on it**. Storage is defined cluster-wide in `/etc/pve/storage.cfg`; every node must be able to reach anything marked shared.

Labels: **[V]** checked against the Proxmox admin guide 9.2.12 or roadmap on 2026-09-27; **[I]** inferred or from memory, re-verify. Current: **PVE 9.2**, ZFS 2.4, Ceph Squid 19.2.3 and **Tentacle 20.2.1** (default for new Ceph installs) [V 2026-09-27].

## When to use

- Adding or choosing a storage backend; explaining why a snapshot, clone or content type is refused.
- Sizing a ZFS pool or a hyperconverged Ceph cluster.
- A disk is failing: SMART errors, a `DEGRADED` pool, a Ceph `HEALTH_WARN` for an OSD.
- Storage full: guests paused with I/O errors, LVM-thin data or metadata full, Ceph `nearfull`/`full` OSDs.

**Not for:** backup jobs and PBS (`proxmox-backup`); storage and Ceph networks (`proxmox-networking`); ZFS replication jobs and HA shared-storage rules (`proxmox-cluster-ha`); per-VM disk options (`proxmox-vm`). Shared-host guardrails come from `proxmox-admin`.

## Storage type matrix [V 2026-09-27]

| Type (`pvesm` plugin) | Level | Shared | Snapshots | Thin | Content |
|---|---|---|---|---|---|
| ZFS local (`zfspool`) | both | no | yes | yes (`sparse 1`) | images, rootdir |
| Directory (`dir`) | file | no | qcow2 only | qcow2 | all: images, rootdir, iso, vztmpl, backup, snippets, import |
| LVM (`lvm`) | block | yes on a shared LUN | volume chain (VMs, tech preview, 9.0+; thick snapshot LVs) | no | images, rootdir |
| LVM-thin (`lvmthin`) | block | no | yes | yes | images, rootdir |
| NFS / CIFS | file | yes | qcow2 | qcow2 | all |
| iSCSI (`iscsi`, `iscsidirect`), FC/SAS | block | yes | via LVM on the LUN + volume chain | no | images |
| Ceph RBD (`rbd`) | block | yes | yes | yes | images, rootdir |
| CephFS (`cephfs`) | file | yes | yes (not guaranteed stable) | n/a | iso, vztmpl, backup, snippets |
| ZFS over iSCSI (`zfs`) | block | yes | yes | yes | images |
| BTRFS | file | no | yes | yes | tech preview |
| PBS (`pbs`) | both | yes | n/a | n/a | backup |

- **GlusterFS is gone** in PVE 9 [V]: migrate off it before upgrading.
- qcow2 internal snapshots on NFS/CIFS block the running VM and can take minutes to hours on large disks [V]; snapshot those VMs while stopped. Volume chains apply only to disks created after the flag is set, and on LVM each snapshot is a thick LV that can use the full disk size [V]: watch free space on a shared LUN.

## Which storage for which job

| Need | Choose | Why |
|---|---|---|
| Single node, snapshots, integrity | ZFS mirror(s) | Checksums, snapshots, replication; mirrors suit VM I/O [V] |
| Single node, simple, low RAM | LVM-thin | Snapshots and thin provisioning without ZFS RAM cost |
| ISOs, templates, backups | Directory, NFS, CIFS or CephFS | Block storage cannot hold files |
| Shared disks, 3+ nodes, fast network | Ceph RBD | Synchronous, self-healing, live migration and HA |
| Existing SAN (iSCSI/FC) | LVM on the LUN, `shared 1`, multipath | Thick; volume-chain snapshots since 9.0 (tech preview) |

## ZFS essentials (detail: [references/zfs.md](references/zfs.md))

- `ashift=12` for 4K-sector and virtually all SSDs; it is fixed at pool creation [V].
- Mirrors (RAID10) for VM workloads; RAIDZ wastes space on small zvol blocks through parity padding [V]. A 4-disk RAIDZ2 has the space of 2 mirrors with worse speed [V].
- `volblocksize` is set only when a zvol is created; change the storage `blocksize` for new disks [V]. Default 16k in current OpenZFS/PVE [I].
- ARC default **10% of RAM, capped at 16 GiB** for installs since PVE 8.1, in `/etc/modprobe.d/zfs.conf` [V]. If lowering `zfs_arc_max` to or below `zfs_arc_min`, lower `zfs_arc_min` too [V].
- A special vdev (metadata, optional small blocks) must match the pool's redundancy: losing it loses the pool, and adding one cannot be undone [V].
- Always name disks by `/dev/disk/by-id/`, never `/dev/sdX` [I].

## Ceph essentials (detail: [references/ceph.md](references/ceph.md))

- **At least 3 nodes** (preferably identical), 3 monitors, **one OSD per physical disk**, no hardware RAID [V].
- Recommended: at least 3 nodes and 12 OSDs spread evenly [V]; 8 GiB RAM per OSD for good performance (4 GiB default target) [V]; one CPU thread per Ceph service, 4-6 per fast NVMe OSD [V].
- Network: 10 Gbps+ **dedicated** to Ceph; 25 Gbps+ for NVMe; a full mesh works for 3-5 nodes [V]. Never share it with corosync.
- Pools: `size 3`, `min_size 2`; **never `min_size 1`** [V].

## Disk health, trim, SSD wear

- `smartctl -a /dev/<disk>` [V]; `smartd` runs by default and mails root [V]. `zpool status -x`, `ceph -s` and `ceph health detail` for pool health.
- Replace a failed ZFS disk: `zpool replace <pool> <old> <new>` onto a checked-blank disk, no `-f` [V 2026-09-27]; on a **boot** pool copy the partition table (`sgdisk <healthy> -R <new>`, `sgdisk -G <new>`), replace partition 3, then `proxmox-boot-tool format`/`init` on the new ESP [V]. Full steps in `references/zfs.md`.
- Trim: enable **Discard** on the VM disk (VirtIO SCSI; SSD emulation for Windows) so guest TRIM reaches thin storage [V]; run `zpool trim` on a schedule or set `autotrim=on` [I]; `fstrim` inside guests and `pct fstrim <ctid>` for containers [I].
- **Consumer SSDs**: ZFS sync writes and Ceph journaling wear them fast and they lack power-loss protection, so sync-write latency is poor [I]. Use enterprise SSDs with PLP for ZFS SLOG, special vdevs and Ceph OSDs [V: PLP advised for SLOG]; watch wear (`smartctl` Percentage Used / Wear_Leveling_Count) [I].

## pvesm

Read-only first: `pvesm status`, `pvesm list <storage>`. Add, scan, set and remove commands: [references/pvesm.md](references/pvesm.md) [V].

## Anti-patterns

| Don't | Why |
|---|---|
| Put ZFS on a hardware RAID controller or Ceph OSDs on RAID volumes | Hides disks from ZFS/Ceph; breaks self-healing and SMART |
| RAIDZ for a busy VM pool by default | Parity padding and poor random IOPS; use mirrors |
| Guess `ashift` or accept 9 on 4K disks | Fixed forever; bad performance |
| Ceph on 2 nodes, 1 GbE, or `min_size 1` | No quorum/replica safety; data loss on a single failure |
| Share one NIC between Ceph and corosync | Recovery traffic breaks cluster quorum |
| Consumer QLC SSDs as ZFS SLOG, special vdev or Ceph OSD | Rapid wear, no PLP, latency spikes |
| A special vdev with less redundancy than the pool | It is a single point of failure for the pool |
| Mark local storage `shared 1` | PVE assumes every node sees the same data; migrations corrupt state |
| `pvesm remove` then expect data gone, or `zpool destroy` to "clean up" | Definition vs data are separate; destroy is irreversible |
| Plan a PVE 9 upgrade with GlusterFS storage | Support removed in 9.0 |
