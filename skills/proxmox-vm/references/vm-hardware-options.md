# VM hardware options in depth

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-vm-defaults
    source_url: https://pve.proxmox.com/pve-docs/chapter-qm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "UI default CPU x86-64-v2-AES, CLI (qm.1) default kvm64 (needs Westmere/Opteron gen 4+); VirtIO SCSI single + IO thread recommended; default cache is no-cache; Windows machine version pinned at creation; ballooning normally left enabled; auto-ballooning targets 80% host memory use."
  - kind: external_fact
    subject: pve-9-vm-changes
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "9.1: nested-virt vCPU flag, vTPM state in qcow2. 9.2: custom CPU models in the web UI, guest-agent freeze-fs option, Windows+host CPU+VBS freeze on Intel fixed by machine 11.0+pve2."
-->

Labels: [V] from the cited Proxmox page, fetched 2026-09-27; [I] inferred, re-verify.

## Firmware and chipset

| Setting | Notes |
|---|---|
| `--bios seabios` | PVE default [V]. Legacy BIOS; boots MBR images and most older cloud images. |
| `--bios ovmf` | UEFI. Needs `--efidisk0 <storage>:1,efitype=4m[,pre-enrolled-keys=0|1]` to persist NVRAM [V syntax]. Required for Secure Boot and for most GPU passthrough [V: docs advise OVMF for PCIe passthrough]. |
| `--machine q35` | Virtual PCIe bus; use for PCIe passthrough and modern guests [V]. |
| Machine version | Linux VMs float to the latest; Windows VMs are pinned at creation because Windows reacts to hardware changes [V]. Pin explicitly (e.g. `pc-q35-<ver>`) when a fix requires it, such as `11.0+pve2` for the 9.2 VBS freeze [V]. |
| `--tpmstate0 <storage>:1,version=v2.0` | Virtual TPM, needed by Windows 11 [I syntax]. Since 9.1 TPM state can be qcow2 on file storage, so snapshots work there [V]. |

Changing firmware on an installed guest breaks its bootloader [I]; decide before install.

## Disks and controller

| Option | Use |
|---|---|
| `--scsihw virtio-scsi-single` | One controller per disk, enabling a dedicated IO thread per disk [V]. The CLI default is still `lsi` [V], so set it explicitly on `qm create`. |
| `iothread=1` | Per disk; offloads I/O from the main QEMU loop [V]. |
| `discard=on` | Passes TRIM to thin storage (LVM-thin, ZFS, qcow2, Ceph) so freed blocks return to the pool [V]. |
| `ssd=1` | Presents the disk as non-rotational so guests issue TRIM [V]. |
| `cache` | Default no-cache (`none`) [V]. `writeback` risks data loss on host crash unless the storage handles it [I]. |
| `aio` | `io_uring`, `native`, `threads` [V values]; leave default unless benchmarked [I]. |
| VirtIO Block (`virtioN`) | Older alternative; VirtIO SCSI is preferred for TRIM and scale [I]. |

Windows: attach the VirtIO driver ISO as a second CD-ROM during install, or the installer finds no disk [V].

## CPU

| Type | When |
|---|---|
| `kvm64` | The `qm create` default when `--cpu` is omitted [V: qm.1]; old baseline, always set a better type. |
| `x86-64-v2-AES` | Web UI default for new VMs; needs a host from Intel Westmere or AMD Opteron gen 4 onward [V]. Safe on mixed clusters. |
| `x86-64-v3` | AVX2-class baseline (Haswell+/Zen+) [I]; better performance, still migration-safe if every node supports it. |
| `host` | All host flags visible [V]; best performance; migration only between identical CPUs and microcode [V]. |
| Custom model | 9.2 adds web UI management of custom CPU models (Datacenter > Guest Resources/Hardware) [V]. |
| `flags=+nested-virt` | 9.1 shorthand in the `flags` list to enable nested virtualization without `host` [V]. |

Sockets x cores: keep sockets at 1 unless NUMA-aware licensing or pinning needs more [I]. `--numa 1` for large VMs on multi-socket hosts [I].

## Memory

- `--memory` is the maximum; `--balloon <MiB>` the minimum; `--balloon 0` disables the balloon driver [V].
- Auto-ballooning reclaims memory from guests when host usage passes a target (default 80%) [V].
- Leave ballooning enabled in general [V]; disable for passthrough VMs (all guest RAM is pinned for DMA, so ballooning gains nothing) [I] and for latency-sensitive guests.
- Windows needs the VirtIO balloon driver and service to report memory [I].
- KSM (kernel samepage merging) on the host deduplicates identical pages; weigh against side-channel concerns on multi-tenant hosts [I].

## QEMU guest agent

- `--agent enabled=1[,freeze-fs=1][,fstrim_cloned_disks=1][,type=virtio]` [V].
- Install inside the guest: `qemu-guest-agent` package (Linux) or from the VirtIO ISO (Windows) [I].
- Gives clean shutdown, IP addresses in the UI, and filesystem freeze/thaw around snapshot backups [V]. `freeze-fs` (default 1) covers backups, clones, replication and snapshots; 9.2 introduced that name and kept the older `freeze-fs-on-backup` as an alias, so older hosts use that spelling [V]. Set it to 0 for guests where the freeze hangs (some Windows/database cases) [I].
- Query: `qm agent <vmid> network-get-interfaces`, `qm agent <vmid> ping` [V].

## Disk operations

- Grow: `qm disk resize <vmid> scsi0 +10G` [V]; then grow the partition and filesystem inside the guest. Shrinking is not supported [V].
- Move to other storage: `qm disk move <vmid> scsi0 <storage> [--delete 1]` [V], works live; keep the source (omit `--delete`) until the VM is verified, and have a restorable backup first (`proxmox-backup`).
- Import a disk file: `qm disk import <vmid> <file> <storage>`, then attach the resulting `unusedN` [V].

## USB and PCI basics

- USB: `--usb0 host=<vendor>:<product>` (follows the device) or `host=<bus>-<port>` (pins a port) [V]. Network-attached devices need no passthrough and survive migration; prefer them.
- PCI: `--hostpci0 <bus:dev.fn>,pcie=1` on q35 [V syntax]; needs IOMMU enabled. Anything beyond a simple NIC or HBA (GPUs, vfio binding, reset bugs): `proxmox-gpu-passthrough`.
- Resource mappings (Datacenter) name a device cluster-wide: `--hostpci0 mapping=<id>` [V].
- USB or PCI passthrough blocks online migration and pins the VM to one node [V].

## Host directory sharing

- `--virtiofs0 dirid=<mapping-id>` shares a host directory defined as a directory resource mapping [V syntax]. The guest needs virtiofs support (Linux kernel driver; WinFsp and VirtIO-FS service on Windows) [I]. Live migration with virtiofs is limited [I].

## Other

- Network: `--net0 virtio,bridge=<bridge>[,tag=<vlan>][,firewall=1]` [I]; `queues=<n>` for multiqueue on busy VMs [I].
- Display: `--vga serial0` for cloud images with a serial console [V]; `std`/`virtio` otherwise.
- Hotplug: `--hotplug disk,network,usb` (defaults) [I]; memory/CPU hotplug needs NUMA and guest support [I].
- Start order: `--startup order=<n>,up=<sec>` for dependency ordering at boot [I].
