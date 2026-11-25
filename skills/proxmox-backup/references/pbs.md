# Proxmox Backup Server (PBS) reference

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-backup-server-release
    source_url: https://pbs.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PBS 4.2 (2026-04-29) is the current 4.x release; S3 datastores officially supported in 4.2, tech preview in 4.0."
  - kind: external_fact
    subject: pbs-maintenance-and-sync
    source_url: https://pbs.proxmox.com/docs/maintenance.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Prune removes metadata only; GC mark/sweep with 24h5m cutoff; verify at least monthly; sync pull default, push supported; namespaces max depth 8; tape LTO-5+ (LTO-4 best effort)."
-->

Labels: **[V]** checked against pbs.proxmox.com docs or the PVE PBS storage wiki on 2026-09-27; **[I]** inferred, so re-verify.

## Deployment choices

| Option | Verdict |
|---|---|
| Dedicated hardware (ISO install) | Recommended; the backups survive a hypervisor failure [V] |
| PBS packages on a PVE host | Supported, but its docs say "not recommended" [V] |
| PBS as a VM or LXC on the PVE host it protects | Workable for a small or home lab only if a sync job, removable datastore or tape takes a copy **off** that host [I]. Datastore disk passed through or on its own pool, never on the pool it backs up [I] |
| PBS on a second PVE node in a cluster | Better than same-host; still share-fate on site power or theft; add off-site [I] |

Sizing: 4 GB RAM for the OS plus 1 GB per TB of backup storage; 4+ cores; OS on 32 GB+ redundant storage; enterprise SSDs, or HDDs plus a ZFS metadata special device [V].

## Datastore

```bash
proxmox-backup-manager datastore create store1 /mnt/datastore/store1          # [V]
proxmox-backup-manager datastore update store1 --gc-schedule 'daily'           # [V] calendar event
proxmox-backup-manager datastore update store1 --tuning 'sync-level=filesystem'  # [V]
```

- Filesystem must allow 65538+ subdirectories per directory: ext4, xfs, zfs [V]. NFS/CIFS-backed datastores work poorly for GC and verify [I].
- **S3 backend**: first `proxmox-backup-manager s3 endpoint create <endpoint-id> ...`, then `datastore create <name> <cache-path> --backend type=s3,client=<endpoint-id>,bucket=<bucket>`; needs a persistent local cache of 64-128 GiB; watch request costs [V].
- **Removable datastore**: ext4/xfs partition identified by its filesystem UUID as the backing device; the path is relative on the device, mounted under `/mnt/datastore/<name>` [V, PBS 4.2 docs, 2026-09-27]:
  ```bash
  proxmox-backup-manager datastore create usb1 usb1 --backing-device <fs-uuid> --gc-on-unmount true   # [V]
  proxmox-backup-manager sync-job create to-usb --remote-store store1 --store usb1 \
    --run-on-mount true --unmount-on-done true      # [V] options; [I] no --remote = local pull store1 -> usb1 (check `sync-job create --help`)
  proxmox-backup-manager datastore unmount usb1                                                      # [V]
  ```
  Prune, verify and GC jobs are **skipped** while the disk is detached, so with `unmount-on-done` pruned chunks pile up until the disk fills [V]. Set `gc-on-unmount` (GC runs before each unmount) or keep a deliberate mounted window for GC [V]. A single datastore on the device auto-mounts [V].
- **Maintenance mode**: `read-only` or `offline` before disk work [V].
- **Namespaces**: up to 8 levels; per-namespace ACLs; move groups with `proxmox-backup-client group move` [V]. PVE picks one with the storage `namespace` option [I].

## Connect PVE to PBS

```bash
pvesm add pbs pbs1 --server <pbs-host> --datastore store1 \
  --username backup@pbs --fingerprint <sha256> --password          # [V]
pvesm set pbs1 --encryption-key autogen                             # [V] key -> /etc/pve/priv/storage/pbs1.enc
```

- Use a dedicated PBS user or API token with `DatastoreBackup` on the datastore/namespace, not `root@pam` [I]. A backup-only role cannot prune, so a compromised PVE host cannot erase history [I]; PVE-side `prune-backups` then fails for lack of `Datastore.Prune`, which is why retention belongs in PBS prune jobs [I].
- Fingerprint from `proxmox-backup-manager cert info` on PBS [V].

## Encryption keys (the part people lose)

- `autogen` runs `proxmox-backup-client key create --kdf none` and stores the key root-only on pmxcfs [V].
- Without it the backups are unreadable; Proxmox recommends a password manager, a separate USB drive and a paper copy [V]: `proxmox-backup-client key paperkey <keyfile> --output-format text` [V].
- **Master key**: `proxmox-backup-client key create-master-key` makes an RSA pair; put the **public** part in the PVE storage (`master-pubkey`), keep the private key offline; each backup then carries its key wrapped by the master key [V].
- Key storage checklist [I]: copy off-host on day one; a second copy off-site; test a restore on a machine that never had the key; rotate by adding a new key and keeping the old until its backups age out.
- Encrypted backups dedup only against backups made with the same key [I].

## Prune, GC, verify

| Task | What it does | Schedule [I] |
|---|---|---|
| Prune job (`proxmox-backup-manager prune-job`, `/etc/proxmox-backup/prune.cfg`) | Drops snapshot manifests by keep-* rules; `--dry-run` or the Prune Simulator first [V] | After backups, daily |
| Garbage collection | Mark phase touches atime on every referenced chunk; sweep deletes chunks older than 24h5m or the oldest active writer [V] | Daily or weekly, after prune |
| Verify job | Re-reads and checksums chunks; can skip already-verified snapshots and re-verify after N days [V] | Daily for new, full re-verify at least monthly [V] |

- `gc-atime-safety-check` (default on) guards filesystems that do not update atime; keep it on [V].
- Space does not come back until GC runs; a full datastore needs prune **and** GC [V].

## Sync and off-site

Sync jobs **pull** by default (`--sync-direction pull`): the job copies *from* the remote *into* the local datastore [V, PBS 4.2 docs, 2026-09-27]. For an off-site copy, run these **on the off-site PBS**, with the remote pointing at the primary:

```bash
# on pbs-offsite: "primary" is the remote to read from
proxmox-backup-manager remote create primary --host pbs1.example --auth-id sync@pbs \
  --password 'SECRET' --fingerprint <primary-sha256>          # [V] --auth-id (PBS 4.2 CLI, 2026-09-27)
proxmox-backup-manager sync-job create offsite --remote primary --remote-store store1 \
  --store offsite1 --schedule 'Wed 02:30'                     # [V] local store = offsite1
proxmox-backup-manager sync-job run offsite                  # [I] first run by hand; then list snapshots on offsite1
```

- The same job created on the primary would copy the off-site data back **into** the primary; check which box you are on before creating it [V: pull semantics].
- `sync@pbs` on the primary needs only read access (`DatastoreReader`) to the source store [I]; a pull reads only what that user can see [V].
- **Pull** from the off-site box is safer than push: the primary holds no credentials that can delete off-site data [I]. Push needs one dedicated remote per push job [V].
- Test the copy: restore one guest from `offsite1` [I].
- Options: `remove-vanished`, `verified-only`, `encrypted-only`, `group-filter` (type, group, regex, exclude), `rate-in`/`rate-out`, `worker-threads`, `resync-corrupt`, namespace mapping via `remote-ns`/`ns`/`max-depth` [V].
- PBS 4.2 push sync can encrypt unencrypted snapshots server-side [V] (docs example option `--active-encryption-key <key>` [I: check `sync-job update --help`]).
- Leave `remove-vanished` **off** on the off-site copy if it is your ransomware fallback [I].

## Tape

- LTO-5 or later, best-effort LTO-4; changers via SCSI medium changer [V]. New LTO-9 media need a 40-120 min optimisation pass [V].
- Media pools, media sets, allocation (`continue`, `always`, calendar) and retention (overwrite, protect for a period, never) [V].
- `proxmox-tape backup-job create <job> --store <ds> --pool <pool> --drive <drive> --schedule <cal>`; tape encryption keys with `proxmox-tape key create`, recoverable from media with the password [V].
- Restore is per media set: catalog, then `proxmox-tape restore <media-set-uuid> <datastore>` [V].

## Host backups with proxmox-backup-client

```bash
export PBS_REPOSITORY='backup@pbs@pbs1:store1'   PBS_FINGERPRINT='<sha256>'  # [V]
# consistent copy of the pmxcfs database behind /etc/pve (needed by host recovery)
mkdir -p /root/pve-cluster-backup
sqlite3 /var/lib/pve-cluster/config.db ".backup '/root/pve-cluster-backup/config.db'"  # [I] needs the sqlite3 package
proxmox-backup-client backup etc.pxar:/etc root.pxar:/root --keyfile /root/pbs.key   # [V] syntax; /root carries the config.db copy
proxmox-backup-client snapshot list                                               # [V]
proxmox-backup-client catalog shell host/<name>/<time> etc.pxar                   # [V]
```

- Use `PBS_PASSWORD_FILE` or an API token secret, not a password on the command line [V option, I advice].
- `--change-detection-mode=metadata` avoids re-reading unchanged files [V]; `--ns` targets a namespace [V].
- Schedule with a systemd timer on the host that runs the `sqlite3 .backup` **and** the backup, in that order [I]. Copying the live `config.db` with `cp` can catch a half-written database [I].
- Test it: restore `root.pxar` to a scratch dir and run `sqlite3 <copy> 'PRAGMA integrity_check;'` (expect `ok`) [I].
