# Docker inside an LXC container: setup and caveats

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-docker-guidance
    source_url: https://pve.proxmox.com/pve-docs/chapter-pct.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "For maximum isolation and live migration Proxmox recommends nesting containers inside a QEMU VM; FUSE inside containers is strongly advised against; nesting exposes procfs and sysfs."
-->

Labels: [V] from the pct chapter, fetched 2026-09-27; [I] inferred or community practice, re-verify.

## Decide first

| Signal | Put Docker in |
|---|---|
| Untrusted images, multi-tenant, internet-exposed admin panels | VM [V: isolation] |
| Needs live migration or HA with no restart | VM [V] |
| Needs kernel modules, custom sysctls, eBPF, WireGuard kernel-side config | VM [I] |
| Kubernetes (k3s, kubeadm) | VM [I] |
| Few trusted homelab services, want low RAM overhead or shared iGPU | Unprivileged LXC with nesting [I] |

## Setup in an unprivileged container [I unless marked]

```bash
pct create <ctid> <storage>:vztmpl/<debian-template> --hostname <name> \
  --unprivileged 1 --features nesting=1,keyctl=1 \
  --cores 2 --memory 2048 --swap 512 --rootfs <storage>:16 \
  --net0 name=eth0,bridge=<bridge>,ip=dhcp --tags <owner-tag>
pct start <ctid>
pct enter <ctid>     # then install Docker from the distro or Docker's apt repo
```

- `nesting=1` [V: exposes procfs/sysfs] and `keyctl=1` are the usual pair.
- Keep Docker data on the container rootfs or a volume mount point with `backup=1`, not on a bind mount, so vzdump captures it [V: bind mounts are not backed up].

## Known caveats [I]

| Caveat | Effect | Mitigation |
|---|---|---|
| Storage driver on ZFS-backed rootfs | overlay2 on ZFS needs ZFS 2.2+ (native overlay support); older setups fell back to `vfs` (huge, slow) | Check `docker info` for the driver; use ext4/LVM-thin rootfs if in doubt |
| Host kernel upgrade | Changes cgroup, AppArmor or netfilter behaviour under the container | Test one container after a host upgrade before trusting the rest |
| AppArmor | Denials look like generic permission errors | Read `journalctl -k | grep apparmor` on the host; do not set `lxc.apparmor.profile: unconfined` on shared hosts |
| No live migration | Migration is stop-and-start | Plan maintenance windows or use a VM |
| Snapshot-mode backups | Freezing a busy Docker container can stall | Use `stop` mode for consistency or back up the app data at the application level |
| FUSE-based tools (fuse-overlayfs, rclone mount) | Need `fuse=1`, which Proxmox strongly advises against [V] | Prefer a VM |
| Privileged container "to make Docker work" | Container root is host root | Stay unprivileged; if it only works privileged, use a VM |

## OCI images as an alternative (PVE 9.1+)

PVE 9.1 can create a container straight from an OCI image, and application-container mode is a technology preview [V: Roadmap]. It suits a single image with an entrypoint and env vars; it does not replace compose stacks, image update tooling or registries with auth workflows [I].
