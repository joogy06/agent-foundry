---
name: proxmox-lxc
description: Proxmox VE LXC containers with pct - container templates (pveam), unprivileged vs privileged containers, idmap (lxc.idmap, /etc/subuid, /etc/subgid) for bind mounts and permission errors, nesting and keyctl features for Docker-in-LXC and its caveats vs a VM, mount points (mpN, backup flag), container backups and restore, CPU and memory limits, device passthrough (devN, /dev/dri for iGPU transcoding), OCI images and application containers (PVE 9.1+ technology preview), and choosing LXC vs VM. Part of the proxmox-admin family.
---

# Proxmox LXC (pct)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pct-cli-syntax
    source_url: https://pve.proxmox.com/pve-docs/pct.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "--features force_rw_sys,fuse,keyctl,mknod,mount=,nesting; --devN path,gid,uid,mode,deny-write; --mpN volume,mp,backup,idmap,ro,shared,replicate; --unprivileged default 1 on create; --entrypoint (default /sbin/init) and --env for application containers; pct move-volume, resize, fstrim, enter, push/pull."
-->

## Overview

An LXC container shares the host kernel: lighter and faster than a VM, but weaker isolation and host-kernel coupling. `pct` manages containers; `pveam` manages the Proxmox template catalogue. Default to **unprivileged** containers and move to a VM whenever a workload needs its own kernel, strong isolation, or live migration.

Labels: **[V]** checked against the cited Proxmox page on 2026-09-27; **[I]** inferred or from memory, re-verify.

**Apply the family guardrails from `proxmox-admin` first**: confirm the node, list guests (`pct list`, `qm list`), one named CTID, never touch other guests, a restorable backup before disk or storage work.

## When to use

- Create or change a container: templates, rootfs, mount points, limits, features.
- Fix permission errors on bind mounts in unprivileged containers (idmap).
- Run Docker inside a container, or decide it belongs in a VM.
- Pass `/dev/dri` or other devices into a container.
- Try OCI images as container templates.

**Not for:** VMs (`proxmox-vm`); GPU driver/IOMMU depth and dGPU passthrough (`proxmox-gpu-passthrough`); storage pools (`proxmox-storage`); backup jobs and PBS (`proxmox-backup`); bridges (`proxmox-networking`); host hardening and AppArmor policy (`proxmox-security-ops`).

## LXC or VM?

| Need | Choose |
|---|---|
| Linux service, low overhead, dense packing | LXC |
| Different kernel, kernel modules, Windows, BSD, appliance OS | VM |
| Strong isolation, untrusted or multi-tenant code | VM |
| Live migration (no downtime) | VM; a running container migrates only by restart, which can kill it and copy its data first (see troubleshooting) [V] |
| Docker / Kubernetes as the main workload | VM recommended by Proxmox for isolation and live migration [V]; LXC works with caveats (below) |
| Shared iGPU across several guests (transcoding) | LXC with `/dev/dri` passthrough [I] |
| Direct host directory access with low overhead | LXC bind mount |

## Templates and creation

```bash
pveam update                                  # refresh the catalogue [V]
pveam available --section system              # list distro templates [V]
pveam download <storage> <template-name>      # to a storage with vztmpl content [V]
pveam list <storage>                          # downloaded templates [V]

pct create <ctid> <storage>:vztmpl/<template> --hostname <name> \
  --unprivileged 1 --cores 2 --memory 1024 --swap 512 \
  --rootfs <storage>:8 --net0 name=eth0,bridge=<bridge>,ip=dhcp \
  --features nesting=1 --ssh-public-keys <file> --tags <owner-tag>
pct start <ctid>; pct enter <ctid>
```

`--unprivileged` defaults to 1 on create [V]; on restore it follows the backup [V]. Resize: `pct resize <ctid> rootfs +4G` [V] (grow only [I]). Move: `pct move-volume <ctid> rootfs <storage>` [V].

## Unprivileged vs privileged

- **Unprivileged** (default): container root maps to a high host UID (typically 100000) through user namespaces; LXC calls this "safe by design" [V; offset I].
- **Privileged**: container root is host root; use only for trusted workloads in trusted environments [V]. Converting later means backup and restore with the other flag [I].
- Most "needs privileged" requests are solved by an idmap, a device entry or a feature flag instead.

## Mount points, bind mounts and idmap

- Volume mount point: `--mp0 <storage>:<size>,mp=/data[,backup=1]` [V syntax]; managed by PVE, can be included in backups.
- Bind mount: `--mp0 /mnt/bindmounts/<name>,mp=/data,ro=1` [V: pct chapter]. The source must be a **dedicated directory reserved for this container**; never `/`, `/var`, `/etc` or another system directory [V], and never another guest's storage (`/var/lib/vz`, `/mnt/pve/<storage>`, guest ZFS datasets) [I]. Drop `ro=1` only when the container must write. Creating the source is a host change: ask first. No symlinks in the path [V]; **not** backed up by vzdump [V]; `shared=1` only when the path exists on every node [V].
- In an unprivileged container, host files owned by UID 1000 appear as `nobody` [I]. Fix by **mapping** IDs, not `chmod 777`. Options (detail and checks: [references/mounts-idmap-devices.md](references/mounts-idmap-devices.md)): `lxc.idmap` lines plus `/etc/subuid`/`/etc/subgid` entries, which are node-local host changes needed on every node the container may run on [I]; or per-mount `idmap=`, PVE 9.2+ and unprivileged only [V: Roadmap, 2026-09-27], which fails on NFS/CIFS sources [I: Proxmox staff, forum, 2026-09-27].

## Features and Docker-in-LXC

`--features nesting=1,keyctl=1` [V syntax].

| Feature | Purpose | Caution |
|---|---|---|
| `nesting` | Exposes procfs/sysfs for nested containers (Docker, systemd features) [V] | Weakens isolation slightly [I] |
| `keyctl` | Keyring syscalls Docker needs in unprivileged containers [V] | Unprivileged only [I] |
| `fuse` | FUSE mounts inside the container | Proxmox strongly advises against: breaks freezer, snapshot backups can hang [V] |
| `mount=<fstype>` | Allow NFS/CIFS mounts inside | **Not on a shared host**: an in-container NFS mount can block the host's I/O completely and prevent reboot [V]. Mount on the host (host change, ask first) and bind-mount |

Docker in unprivileged LXC with `nesting=1,keyctl=1` works for many homelab workloads [I], but host kernel upgrades can break it [I], there is no live migration, and AppArmor denials are opaque [I]. Proxmox recommends a VM for isolation and live migration [V]. Detail: [references/docker-in-lxc.md](references/docker-in-lxc.md).

## Limits, devices and OCI images

- Limits: `--cores`, `--cpulimit`, `--cpuunits`, `--memory`/`--swap` [V]; table: [references/limits-and-oci.md](references/limits-and-oci.md).
- Devices: `--dev0 /dev/dri/renderD128,gid=<render-gid-in-ct>,mode=0660` [V syntax], replacing the older `lxc.cgroup2.devices.allow` recipe [I]; read the container's `render` GID first. Steps, USB serial and legacy recipe: [references/mounts-idmap-devices.md](references/mounts-idmap-devices.md); driver depth: `proxmox-gpu-passthrough`.
- OCI images (PVE 9.1+): pull or upload an image as a CT template [V]; **application containers** (`--entrypoint`, `--env`) are a **technology preview** [V]. Not a Docker replacement: keep complex stacks in Docker in a VM. Detail: [references/limits-and-oci.md](references/limits-and-oci.md).

## Backups and troubleshooting

- vzdump includes volume mount points only with `backup=1`; bind and device mounts never [V]. Back those up at the source. Modes, jobs, PBS and restores: `proxmox-backup`.
- Container will not start, locked, "nobody" files, old distro fails on 9.x: [references/troubleshooting.md](references/troubleshooting.md).

## Anti-patterns

| Don't | Why |
|---|---|
| Make a container privileged to fix a permission error | Container root becomes host root; use idmap or a device entry [V] |
| `chmod -R 777` on a bind-mount source | Hides the mapping problem and exposes the data to everyone |
| Enable `fuse` casually | Breaks freezing; snapshot backups can hang [V] |
| Assume bind mounts are in the backup | vzdump skips bind and device mounts [V] |
| Run untrusted or multi-tenant Docker in LXC | Shared kernel; a VM isolates [V] |
| Expect live migration of a container | Restart migration kills the CT after a 180 s shutdown timeout and copies local data offline [V] |
| `mount=nfs` feature on a shared host | Can hang host I/O and block reboot for every guest [V] |
| Bind-mount `/`, `/etc`, `/var` or another guest's storage | Great security risk to the host and neighbours [V] |
| Pass `/dev/dri` without the right GID mapping | The app gets permission denied on the render node |
| Treat OCI application containers as production-ready | Technology preview in 9.x [V] |
| Upgrade the host kernel without testing Docker-in-LXC guests | Kernel-coupled workloads break silently |
