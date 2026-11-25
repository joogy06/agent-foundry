# Restores, host recovery and restore testing

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-restore-commands
    source_url: https://pve.proxmox.com/pve-docs/chapter-vzdump.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "qmrestore <archive> <vmid> [--live-restore] [--bwlimit]; pct restore <vmid> <archive> --storage; live-restore and file restore PBS-only; /var/lib/pve-cluster/config.db backs /etc/pve."
  - kind: external_fact
    subject: pbs-s3-object-lock
    source_url: https://forum.proxmox.com/threads/immutable-backups-on-s3-object-storage.169404/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Object locking is not part of the PBS S3 implementation (Proxmox staff, 2025-08-08); PBS 4.2 storage docs do not mention Object Lock."
-->

Labels: **[V]** checked against pve.proxmox.com docs on 2026-09-27; **[I]** inferred, so re-verify.

## Before any restore

1. List what exists: `qm list`, `pct list`, `pvesm list <backup-storage>` [I]. Confirm the target ID is free.
2. Pick the archive by time **and** by verify state (PBS shows it) [I].
3. Restore to a **new** ID, not over the running guest.
4. Put the restored guest on an isolated bridge or with its NIC down until checked: two guests with the same MAC and IP on one LAN break both [I].

## VM restore

```bash
qmrestore <archive-or-pbs-volid> <new-vmid> --storage <target-storage> [--unique 1]   # [V] --unique: new MACs [I]
qmrestore <pbs-volid> <new-vmid> --live-restore 1                                     # [V] PBS only
qmrestore <archive> <new-vmid> --bwlimit 51200                                        # [V] KiB/s
```

- **Live-restore**: the VM starts immediately; chunks the guest reads are fetched first. Reads are slow during restore, and a failure leaves the VM in an undefined state, so use it for fast recovery of a service, not as a routine restore [V].
- Restoring over an existing ID needs `--force` and destroys the current disks [I].

## Container restore

```bash
pct restore <new-ctid> <archive-or-pbs-volid> --storage <target-storage>            # [V]
pct restore <new-ctid> <archive> --storage <s> --unprivileged 1                     # [V] option
```

- A privileged-to-unprivileged conversion on restore changes file ownership mapping; test the app [I].
- Mount points excluded with `backup=0` are not in the archive, so their data is not restored from it; plan a separate restore for them [I].

## File-level restore

- GUI: storage > Backups > select > **File Restore**, download files or a directory as zip [V]. PBS-backed storage only [V].
- VM images are opened in a temporary restore VM so untrusted guest filesystems never mount on the host [V]. LVM, ZFS inside the guest and Windows NTFS are supported by the restore VM; exotic layouts may not be [I].
- CLI for host/file backups: `proxmox-backup-client restore <snapshot> <archive> <target>`, `mount`, `catalog shell` [V].

## Rebuilding a lost host

1. Reinstall the same PVE major version with the same hostname and IP [I].
2. Restore host files from the host backup: `/etc/network/interfaces`, `/etc/hosts`, modprobe and kernel cmdline files [I].
3. Recover pmxcfs from the host backup's `config.db` copy (see [pbs.md](pbs.md#host-backups-with-proxmox-backup-client)): with no guests running, stop `pve-cluster`, replace `/var/lib/pve-cluster/config.db` (mode `0600`), check `/etc/hostname` and `/etc/hosts` match the lost host, then reboot [V: pmxcfs docs, 2026-09-27]. On a cluster member, rejoin instead and let the cluster copy win (route to `proxmox-cluster-ha`) [I].
4. Re-add the PBS storage **with the saved encryption key** [V: key needed].
5. Restore guests, highest priority first; live-restore for the ones users are waiting on [I].

## Restore testing routine

| Cadence [I] | Test | Pass criteria |
|---|---|---|
| Automatic, daily | PBS verify job on new snapshots | No failed chunks |
| Monthly | Restore one VM and one CT to scratch IDs on an isolated bridge | Boots, app starts, data is from the expected time |
| Quarterly | File restore of a known file; host config restore on a spare or nested PVE | File matches; config applies |
| Yearly or after a key change | Restore from the **off-site** copy using only the offline key copy | Success without touching the primary site |

Record for each: date, archive, time to restore, problems. Delete scratch guests afterwards. A failed drill is a finding to fix, not a note.

## 3-2-1 shapes

| Scale | Shape [I] |
|---|---|
| Single node, home lab | PBS VM/LXC on its own disk + removable datastore or remote PBS/S3 pulled weekly |
| Small business | Dedicated PBS box + off-site PBS pulling nightly + monthly tape or removable disk offline |
| Cluster | Dedicated PBS (or two) + off-site sync + verify + restore drill per quarter |

The off-site copy should be one the primary cannot delete: an off-site PBS that **pulls** from the primary (the primary holds no credentials for it) with `remove-vanished` off and its own prune schedule, or offline/WORM tape with protected retention [I].

S3 Object Lock is **not** part of PBS's S3 datastore feature set (Proxmox staff, forum, 2025-08-08) [V, checked 2026-09-27]; the PBS 4.2 storage docs do not mention it [V]. Do not describe a PBS S3 datastore as immutable. A separate object-locked archive (for example, exported tape images or files written by another tool) is a distinct workflow that needs its own restore test [I].
