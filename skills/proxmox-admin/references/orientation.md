# Proxmox VE orientation

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.2 arm64 (2026-08-05): Debian 13.6, first arm64 release. PVE 9.2 (2026-05-21): Debian 13.5, kernel 7.0, QEMU 11.0, LXC 7.0; custom CPU models in the web UI; OCI-based LXC creation, application containers a technology preview. PVE 9.1 (2025-11-19): Debian 13.2, kernel 6.17, QEMU 10.1, LXC 6.0.5."
-->

Labels: [V] fetched from the cited page on 2026-09-27; [I] inferred or from memory, re-verify.

## Release notes worth knowing (source: https://pve.proxmox.com/wiki/Roadmap, fetched 2026-09-27)

| Release | Date | Base | Notable for the family |
|---|---|---|---|
| 9.2 arm64 | 2026-08-05 [V] | Debian 13.6, kernel 7.0, QEMU 11.0, LXC 7.0 [V] | First non-x86 release; NVIDIA Grace/Vera officially, other UEFI ARMv9-A best effort; no SeaBIOS, AMD SEV or GVT-g; live migration only between same-architecture nodes [V] |
| 9.2 | 2026-05-21 [V] | Debian 13.5, kernel 7.0, QEMU 11.0, LXC 7.0 [V] | Custom CPU models managed in the web UI (Datacenter) [V]; guest-agent `freeze-fs` option for backups [V]; Cluster Resource Scheduler dynamic load balancing for HA guests [V]; known issue: Windows 11/2022/2025 with CPU type `host` and VBS on Intel may freeze, fixed by machine version `11.0+pve2` [V] |
| 9.1 | 2025-11-19 [V] | Debian 13.2, kernel 6.17, QEMU 10.1, LXC 6.0.5 [V] | LXC from OCI images, application containers as technology preview [V]; vTPM state in qcow2 (snapshots with TPM on file storage) [V]; `nested-virt` vCPU flag [V]; Intel TDX initial support [V] |
| 9.0 | 2025 [I: August 2025] | Debian 13 Trixie [I] | First Trixie-based release; upgrade path from 8.4 via `pve8to9` checklist [I] |

Newer than 9.2 (x86-64) and 9.2 arm64: none found on the Roadmap page on 2026-09-27 [V: absence on the page]; a 9.3 announced elsewhere cannot be ruled out.

## CLI tools [V: pve-docs index, 2026-09-27]

| CLI | Scope |
|---|---|
| `qm` | QEMU/KVM VMs |
| `pct`, `pveam` | LXC containers, container templates |
| `pvesm` | Storage definitions and volumes |
| `pvecm` | Cluster membership and quorum |
| `ha-manager` | HA resources and groups/rules |
| `vzdump`, `qmrestore`, `pct restore` | Backups and restores on the node |
| `proxmox-backup-client` | File-level/host backups to a PBS server |
| `pveversion -v` | Exact package versions on this node |

## Config paths [V for /etc/pve; paths I]

`/etc/pve` is **pmxcfs**, a database-backed cluster filesystem replicated to every node. Guest configs: `/etc/pve/qemu-server/<vmid>.conf`, `/etc/pve/lxc/<ctid>.conf` (symlinked per node under `/etc/pve/nodes/<node>/`); storage in `/etc/pve/storage.cfg`; users/ACLs in `/etc/pve/user.cfg`; datacenter settings in `/etc/pve/datacenter.cfg`. Prefer `qm set`/`pct set`/`pvesh` over hand-editing; if you must edit, copy the file first and never edit while the cluster lacks quorum (it goes read-only).

## Repositories [I]

- `pve-enterprise` (subscription), `pve-no-subscription` (free, less tested), `pvetest`. Debian 13 uses deb822 `.sources` files under `/etc/apt/sources.list.d/`.
- Repository and upgrade policy is owned by `proxmox-security-ops`.

## Logs and state [I]

| What | Where |
|---|---|
| Task log (every UI/API action) | Web UI Tasks panel; `/var/log/pve/tasks/` |
| Cluster filesystem and corosync | `journalctl -u pve-cluster -u corosync` |
| VM start failures | The task log and the output of `qm start <vmid>`; `journalctl -b` filtered on the VMID |
| Container start debugging | `pct start <ctid> --debug` |
| API daemons | `pvedaemon`, `pveproxy`, `pvestatd` units |

## Read-only query cookbook [I]

```bash
pveversion -v                                    # exact package versions
pvesh get /nodes --output-format json             # nodes and status
pvesh get /cluster/resources --type vm            # every VM and CT, cluster-wide
pvesh get /nodes/<node>/qemu/<vmid>/config        # one VM config
pvesh get /nodes/<node>/lxc/<ctid>/config         # one CT config
pvesh get /nodes/<node>/storage                   # storages as this node sees them
pvesh get /cluster/nextid                         # next free guest ID
qm config <vmid>; pct config <ctid>               # same, via the guest tools
```

`pvesh get` never changes state; `pvesh create|set|delete` do, and follow the guardrails like any other mutation.
