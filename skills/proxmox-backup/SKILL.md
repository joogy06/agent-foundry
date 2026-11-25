---
name: proxmox-backup
description: Proxmox VE backup and restore - vzdump modes (snapshot, suspend, stop) and consistency, fleecing, backup jobs and prune-backups retention (keep-last, keep-daily, keep-weekly), Proxmox Backup Server (PBS) datastores, dedup, client-side encryption keys, verify, prune and garbage collection (GC), sync jobs, namespaces, tape, S3, proxmox-backup-client host backups, qmrestore, pct restore, live-restore, file-level restore, backing up /etc/pve and the host, 3-2-1 off-site copies and restore testing. Use for backup failed, guest locked after backup, PBS fingerprint mismatch, datastore full, restore, or retention questions.
---

# Proxmox Backup

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Proxmox VE 9.2 released 2026-05-21 (arm64 2026-08-05), Debian 13 Trixie, kernel 7.0; 9.1 released 2025-11-19."
  - kind: external_fact
    subject: proxmox-backup-server-release
    source_url: https://pbs.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PBS 4.2 released 2026-04-29 (Debian 13.4, kernel 7.0, ZFS 2.4.1, S3 datastores officially supported, push-sync server-side encryption); 4.1 2025-11-26; 4.0 2025-08-06 (S3 as tech preview)."
  - kind: external_fact
    subject: vzdump-semantics
    source_url: https://pve.proxmox.com/pve-docs/chapter-vzdump.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Modes stop/suspend/snapshot; snapshot uses guest-agent fsfreeze; fleecing via --fleecing enabled=1,storage=X; prune-backups keep-last/hourly/daily/weekly/monthly/yearly; live-restore and file restore are PBS-only; /etc/pve and host config are not in guest backups."
-->

## Overview

A backup exists only when it is **off the disk it protects**, **restorable**, and **tested**. vzdump makes the archive; Proxmox Backup Server (PBS) makes it incremental, deduplicated, encrypted, verified and replicable.

Labels: **[V]** checked against the cited Proxmox docs on 2026-09-27; **[I]** inferred, re-verify. Current lines: **PVE 9.2** (2026-05-21) [V] and **PBS 4.2** (2026-04-29) [V], both on Debian 13 Trixie [V].

## When to use

- Choosing a vzdump mode, schedule or retention; a backup job failed or is slow.
- Designing or running PBS: datastore, encryption, verify, prune/GC, sync, tape, S3.
- Restoring a VM, container, single file, or a whole host.
- Proving recoverability: a 3-2-1 plan, off-site copy, restore drills.

**Not for:** storage backends and ZFS pools (`proxmox-storage`); storage replication and HA (`proxmox-cluster-ha`); guest creation (`proxmox-vm`, `proxmox-lxc`); shared-host guardrails and family routing (`proxmox-admin`). Follow the `proxmox-admin` guardrails: back up and restore only the guest IDs in scope, never `--all` on a shared host.

## Snapshots are not backups

| | Snapshot (`qm snapshot`, `pct snapshot`) | Backup (vzdump / PBS) |
|---|---|---|
| Stored | Same storage as the disk | A backup storage or PBS server |
| Survives disk, pool or host loss | No | Yes, if the target is off-host |
| Contents of a backup | n/a | Full guest config plus data; **no** snapshots inside [V] |

Delete snapshots after the risky change; long chains cost space and I/O.

## vzdump modes

| Mode | VM behaviour [V] | Container behaviour [V] | Choose when |
|---|---|---|---|
| `snapshot` | Live; lowest downtime, small inconsistency risk; guest agent `fsfreeze` if the agent is enabled | Suspend, temporary storage snapshot, tar it; every volume must support snapshots | Default for almost everything |
| `suspend` | Suspend then snapshot-style backup; longer downtime, **no** consistency gain | rsync to temp, suspend, second rsync; needs extra space | Legacy; rarely the right choice |
| `stop` | Clean shutdown, backup, restart; highest consistency, short downtime | Stop for the whole run | Databases without agent hooks, or a tiny maintenance window |

- Install and enable the **QEMU guest agent** (`--agent enabled=1`) so snapshot mode freezes filesystems [V]. Databases still want an app-level dump or pre-freeze hook [I].
- **Fleecing** (VMs; `--fleecing enabled=1,storage=<fast-local-thin>`) caches old blocks locally so a slow target does not stall guest writes [V].
- Exclude a disk: `backup=0` on the VM disk; container extra mount points are excluded unless `backup=1`; bind/device mounts are never backed up [V].
- Compression: `zstd` (multi-threaded, fastest) [V].

## Jobs and retention

- Jobs: Datacenter > Backup, stored in `/etc/pve/jobs.cfg`, systemd calendar-event schedules; `repeat-missed` runs jobs missed during downtime [V].
- Retention: `--prune-backups keep-last=3,keep-daily=7,keep-weekly=4,keep-monthly=6` [V]. Each rule covers only its own period, working outward from newest [V]. Job retention overrides storage retention [V].
- **Protected** backups skip pruning and do not count toward retention; cap with `max-protected-backups` [V].
- With PBS, prefer **prune jobs on the PBS side** and leave PVE retention unset, so one place owns deletion [I].
- Container backups to PBS: `--pbs-change-detection-mode metadata` skips unchanged files [V].
- Node defaults live in `/etc/vzdump.conf` [V]; a hook script (`--script`) can quiesce an app per phase [I]; route job results to a human through notification matchers (`type=vzdump`, see `proxmox-security-ops`) [V].

## PBS essentials

Detail and commands: [references/pbs.md](references/pbs.md).

| Topic | Rule |
|---|---|
| Placement | Separate hardware; PBS docs call same-host install "not recommended" [V]. A PBS VM/LXC is acceptable **only** with a sync or tape copy that leaves the host [I] |
| Storage | ext4, xfs or zfs; enterprise SSDs, or HDDs plus a ZFS metadata special vdev [V] |
| Encryption | Client-side (AES-256-GCM [I]) key made on PVE (`encryption-key autogen`); key lives at `/etc/pve/priv/storage/<ID>.enc` [V]. **Lose the key = lose the backups** [V]. Copy it off-host, print a `paperkey`, optionally add a master RSA key [V] |
| Prune | Removes snapshot metadata only; space returns at **GC** [V] |
| GC | Mark (atime touch) + sweep of chunks older than 24h5m or the oldest writer [V]. Run after prune, e.g. daily |
| Verify | Scheduled verify jobs; re-verify everything at least monthly for bit rot [V] |
| Sync | Pulls by default, so the off-site PBS runs the job with the primary as remote [V]; `encrypted-only`, `verified-only`, `group-filter` [V] |
| Namespaces | Up to 8 levels; separate clusters, tenants or retention classes in one datastore [V] |
| Off-host media | Tape (LTO-5+, best-effort LTO-4) [V]; S3-backed datastores (supported in 4.2, need a 64-128 GiB local cache) [V]; removable USB datastores, with `gc-on-unmount` (GC is skipped while detached) [V] |

## Restores

Restore procedures, host recovery and the test routine: [references/restore-and-dr.md](references/restore-and-dr.md). Failed jobs (guest left locked, fingerprint changed, datastore full, `qmp command 'backup' failed`): [references/troubleshooting.md](references/troubleshooting.md).

- VM: `qmrestore <archive> <new-vmid> --storage <s>`; container: `pct restore <new-ctid> <archive> --storage <s>` [V]. Restore to a **new** ID, check it, then swap.
- **Live-restore** (`qmrestore ... --live-restore 1`) boots the VM while data streams in; PBS only; a failed live-restore leaves the VM undefined [V].
- **File restore**: storage > Backups > File Restore on a PBS-backed storage; VM images open in a temporary sandbox VM [V].

## The host is not in the guest backups

vzdump skips host config and `/etc/pve` [V]. Back up a consistent copy of `/var/lib/pve-cluster/config.db` (the pmxcfs database behind `/etc/pve`; `sqlite3 .backup`, not the live file) [V], plus `/etc`, the PBS key files and `/root` [I]; on the PBS box, `/etc/proxmox-backup/` [I]. Nightly recipe: [references/pbs.md](references/pbs.md#host-backups-with-proxmox-backup-client). Recovery steps: [references/restore-and-dr.md](references/restore-and-dr.md#rebuilding-a-lost-host).

## 3-2-1 and restore drills

- **3** copies, **2** media, **1** off-site; keep one copy the PVE host **cannot delete** (pull sync run by the off-site PBS, or WORM tape); PBS S3 datastores have no Object Lock [V, 2026-09-27].
- Drill monthly or quarterly: restore one VM and one CT to scratch IDs on an isolated bridge, boot, check the app, record time-to-restore [I]. Routine and shapes by scale: [references/restore-and-dr.md](references/restore-and-dr.md#restore-testing-routine).

## Anti-patterns

| Don't | Why |
|---|---|
| Treat snapshots or a same-pool copy as the backup | They die with the disk or pool |
| Run PBS as a VM on the only host with no sync off it | Host loss takes the backups too |
| Enable encryption without exporting the key | Unrestorable after a host rebuild |
| Retention in both PVE jobs and PBS prune jobs | Two deleters; surprises on what survives |
| Prune without GC (or GC never scheduled) | Datastore never frees space |
| Skip verify jobs | Bit rot surfaces only on the day you restore |
| Restore over the live VMID | A bad archive leaves nothing to fall back on |
| `stop` mode everywhere "for safety" | Daily downtime; snapshot + agent is the normal choice |
| Assume `/etc/pve` is in guest backups | It is not; a rebuilt host loses storage, users and jobs |
| Never test a restore | An untested backup is a hope, not a backup |
| `vzdump --all` on a shared host | Touches other people's guests; scope by ID |
