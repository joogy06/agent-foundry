# Bind mounts, idmap and device passthrough for unprivileged containers

<!-- FRESHNESS:v1
volatility: low
anchors:
  - kind: external_fact
    subject: pct-mount-dev-syntax
    source_url: https://pve.proxmox.com/pve-docs/pct.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "--mpN [volume=]<vol>,mp=<path>[,backup][,idmap=<type:container:disk:range-size;...>][,ro][,shared]; --devN [path=]<path>[,deny-write][,gid][,mode][,uid]; bind mount sources must not contain symlinks; bind/device mounts not backed up."
  - kind: external_fact
    subject: pct-mount-safety
    source_url: https://github.com/proxmox/pve-docs/blob/master/pct.adoc
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Bind mounts only from directories reserved for the purpose (e.g. /mnt/bindmounts); never bind mount /, /var or /etc (great security risk); features mount=nfs can block the host's I/O completely and prevent reboot; per-mount idmap= added in PVE 9.2 (LXC 7.0), unprivileged only."
-->

Labels: [V] from the pct man page / pct chapter, fetched 2026-09-27; [I] inferred, re-verify. Back up the container before editing its config, and treat every change to host files (`/etc/subuid`, `/etc/subgid`, bind-mount sources, host mounts) as a host-level change that needs the owner's approval first (`proxmox-admin` guardrails).

## Why "nobody:nogroup" appears

An unprivileged container maps container IDs 0-65535 to host IDs 100000-165535 [I: the usual `/etc/subuid` range `root:100000:65536`]. A host file owned by UID 1000 is outside the container's mapped range, so the container shows it as `nobody` and cannot write it.

Three fixes, cheapest first:

| Fix | When |
|---|---|
| Change host ownership to the shifted ID (`chown 101000:101000 /mnt/bindmounts/<name>` for container UID 1000) [I] | The dedicated path is only used by this container |
| Per-mount `idmap=` on the mount point [V option] | PVE 9.2+ and unprivileged containers only [V: Roadmap 9.2, fetched 2026-09-27]; local filesystems, not NFS/CIFS sources (see below) |
| Full `lxc.idmap` in the container config | Several mounts or the host and container must share the same UID |

## Worked example: map container UID/GID 1000 to a dedicated host ID [I]

Before you start:

- **Use a dedicated host ID**, not an existing login account. Mapping container UID 1000 onto host UID 1000 gives the container that host user's file access everywhere the mount reaches. Create a system account for the share (e.g. `useradd --system --no-create-home ct-<name>`, which picks an ID; call it `<hid>`) and own the dedicated source directory with it. Review who else can read or write that directory [I].
- **`/etc/subuid` and `/etc/subgid` are node-local**, but `/etc/pve/lxc/<ctid>.conf` replicates to every cluster node [V: /etc/pve replication, pct chapter; I: subuid is node-local]. Add the same entries, the same `<hid>` and the same source path on **every node the container may run on** (migration, HA) before relying on them; otherwise the container fails to start after a migration [I].
- These are host-level edits: ask first (`proxmox-admin` guardrail 6).

Host `/etc/subuid` and `/etc/subgid` must allow root to map `<hid>` (add alongside the existing line; `1500` below stands for `<hid>`):

```
root:100000:65536
root:1500:1
```

`/etc/pve/lxc/<ctid>.conf` (stop the container first):

```
mp0: /mnt/bindmounts/<name>,mp=/data
lxc.idmap: u 0 100000 1000
lxc.idmap: g 0 100000 1000
lxc.idmap: u 1000 1500 1
lxc.idmap: g 1000 1500 1
lxc.idmap: u 1001 101001 64535
lxc.idmap: g 1001 101001 64535
```

The three ranges must cover 0-65535 with no gaps or overlaps: 1000 + 1 + 64535 = 65536. Existing files in the rootfs owned by container UID 1000 were stored as host 101000 and now look unowned; fix them inside the container after the change.

Before any migration or HA placement, check every permitted node: `grep '^root:' /etc/subuid /etc/subgid` shows the same `<hid>` lines, `id <hid>` resolves, and the source path exists [I].

Per-mount variant (format `type:container:disk:range-size`; overrides `lxc.idmap` for this mount only, unmapped IDs fall back to it) [V: pct mount point options]:

```
mp0: /mnt/bindmounts/<name>,mp=/data,idmap=u:1000:1500:1;g:1000:1500:1
```

Gate it before changing the container:

1. `pveversion`: the option exists from **PVE 9.2** (LXC 7.0) [V: Roadmap 9.2, fetched 2026-09-27]; it only applies to **unprivileged** containers [V].
2. `findmnt -no FSTYPE -T <source>` on the host [I]. The per-mount map uses an idmapped mount, a different kernel feature from the user-namespace default map [I: Proxmox staff, forum thread "9.2 idmap problem", fetched 2026-09-27]. On an **NFS or CIFS** source it fails and the container will not start (`mount_setattr: Invalid argument`) [I: same thread]. Use it on local filesystems only (ext4, xfs, ZFS [I]).
3. For an NFS share: set ownership on the NFS server instead, e.g. export with `all_squash,anonuid=<shifted-id>,anongid=<shifted-id>` or chown the export to the shifted ID (container UID 1000 = host 101000 with the default map) [I], and keep `ro=1` if the container only reads.

## Bind mount rules

- Source must be a directory **reserved for this purpose**, e.g. under `/mnt/bindmounts` [V]. Never bind-mount `/`, `/var`, `/etc` or another system directory, which Proxmox calls a great security risk [V], and never another guest's storage (`/var/lib/vz`, `/mnt/pve/<storage>/images`, guest ZFS datasets) [I].
- Source path must exist on the host and contain no symlinks [V].
- `ro=1` unless the container must write [V option]. `shared=1` only if the same path exists on every cluster node [V], otherwise migration breaks.
- Bind and device mounts are **not** in vzdump backups [V]; back them up at the source.
- **Never enable `mount=nfs` inside a container on a shared host**: Proxmox warns an NFS mount there can block the host's I/O completely and prevent it from rebooting [V: pct.conf `features` `mount`, fetched 2026-09-27]. Mount the share on the host (a host-level change: ask first) and bind-mount a dedicated subdirectory.

## /dev/dri for iGPU (Intel QSV / VA-API, AMD VA-API) [I unless marked]

1. On the host, confirm the render node: `ls -l /dev/dri` (e.g. `card0`, `renderD128`).
2. Inside the container, read the GIDs: `getent group render video`.
3. Add the devices (the `devN` syntax is [V]):
   ```bash
   pct set <ctid> --dev0 /dev/dri/renderD128,gid=<render-gid>,mode=0660
   pct set <ctid> --dev1 /dev/dri/card0,gid=<video-gid>,mode=0660     # only if the app needs it
   ```
4. Restart the container; inside it install VA-API/QSV userspace (e.g. `intel-media-va-driver`, `vainfo`) and run `vainfo`.
5. Add the app's user to the `render` group inside the container.

The PVE UI exposes `devN` as Resources > Add > Device Passthrough [I]. USB serial devices work the same way: `--dev0 /dev/serial/by-id/<id>` [I]. A device passed to a container stays usable by the host and other containers at the same time, unlike VM passthrough [I]. Kernel driver choice, firmware and dGPU cases: `proxmox-gpu-passthrough`.

## Legacy recipe (pre-devN) [I]

Older guides add `lxc.cgroup2.devices.allow: c 226:* rwm` and `lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir`. Prefer `devN`: it is managed, survives UI edits and sets ownership.
