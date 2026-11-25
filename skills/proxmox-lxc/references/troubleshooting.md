# Container troubleshooting (pct)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pct-troubleshooting
    source_url: https://pve.proxmox.com/pve-docs/pct.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "pct start --debug, pct unlock, pct fsck, pct mount/unmount, pct enter, pct migrate --restart exist; restart migration shuts down, kills the CT after --timeout (default 180 s), then migrates offline; FUSE in containers is advised against (chapter-pct)."
-->

Labels: [V] from the pct man page or pct chapter, fetched 2026-09-27; [I] inferred or field experience, re-verify. Apply the `proxmox-admin` guardrails: one named CTID you own, a restorable backup before repairs that touch disks.

| Symptom / message | Likely cause | Fix |
|---|---|---|
| Start fails with `mount_setattr: Invalid argument` | Per-mount `idmap=` on an NFS/CIFS bind source [I: Proxmox forum, 2026-09-27] | Remove `idmap=` from that `mpN`; fix ownership on the NFS server instead ([mounts-idmap-devices.md](mounts-idmap-devices.md)) |
| `startup for container '<ctid>' failed` | Many causes; the task log is terse [I] | `pct start <ctid> --debug` [V], or `lxc-start -n <ctid> -F -l DEBUG -o /tmp/lxc-<ctid>.log` and read the log [I] |
| `CT is locked (backup)` / `(snapshot)` / `(mounted)` | A task holds the lock, or `pct mount` was left open [I] | Check the Tasks log; `pct unmount <ctid>` if mounted; `pct unlock <ctid>` [V] only when no task runs |
| Old distro (e.g. CentOS 7, Ubuntu 16.04 era) starts but systemd fails or no network | 9.x hosts are cgroup-v2 only; old systemd cannot run there [I] | Move the workload to a newer template or into a VM |
| Files on a bind mount show `nobody:nogroup`, writes fail | Unprivileged UID shift [I] | Map the IDs: [mounts-idmap-devices.md](mounts-idmap-devices.md); do not go privileged |
| `newuidmap` / "idmap" errors after editing `lxc.idmap` | Ranges do not cover 0-65535 exactly, or `/etc/subuid`/`/etc/subgid` lacks the entry [I] | Recount the ranges; add `root:<hostid>:<count>` to both files on **every node the CT may run on** (they are node-local; the CT config replicates) [I]. Host-level change: ask first |
| Docker inside fails with keyring or overlay errors | Missing `keyctl=1`/`nesting=1`, or overlay on old ZFS [I] | Set the features; check `docker info`; see [docker-in-lxc.md](docker-in-lxc.md) |
| AppArmor `DENIED` lines on the host journal | Container action blocked by the LXC profile [I] | Adjust the `nesting` feature rather than setting `unconfined` on a shared host; do not add `mount=nfs` as a workaround, it can block host I/O and reboot [V: pct.conf `mount`] |
| Snapshot-mode backup hangs | FUSE mount inside the container blocks freezing [V: FUSE advised against] | Remove the FUSE use or use `stop` mode; see `proxmox-backup` |
| Rootfs corruption suspected | Unclean host shutdown [I] | Stop the CT, `pct fsck <ctid>` [V]; `pct mount <ctid>` to inspect files from the host, then `pct unmount` |
| `/dev/dri` present but app gets permission denied | GID in `devN` does not match the container's `render` group [I] | `pct set <ctid> --dev0 /dev/dri/renderD128,gid=<render-gid>,mode=0660` [V syntax] |
| Migration refuses a running CT | Containers cannot live-migrate [V] | `pct migrate <ctid> <node> --restart` [V] shuts the CT down, **kills it if it has not stopped within `--timeout` (default 180 s)**, copies it like an offline migration, then starts it on the target [V]. The outage is the shutdown plus the copy of any local volumes, not a fixed short window [I]. For stateful workloads (databases, queues): `pct shutdown <ctid>` cleanly, check target storage space (`--target-storage`) and that bind-mount sources and idmap entries exist on the target, then migrate offline [V options; I procedure] |
| Container disk full | Rootfs sized too small [I] | `pct resize <ctid> rootfs +<N>G` [V]; grows online |
| Thin pool shows more used than the CT uses | Deleted blocks not returned [I] | `pct fstrim <ctid>` [V] |
