---
name: proxmox-vm
description: Proxmox VE virtual machines with qm - creating KVM VMs from ISO or a qcow2 cloud/appliance image (import-from, qm disk import), OVMF vs SeaBIOS, q35, efidisk and TPM, VirtIO SCSI single with iothread, discard and SSD emulation, CPU type (host vs x86-64-v2-AES/v3 for migration), ballooning, qemu-guest-agent, cloud-init templates, linked vs full clones, disk resize and move, USB and PCI device basics, live migration prerequisites, and importing from VMware ESXi (import wizard, OVF/OVA) or Hyper-V (VHDX). Part of the proxmox-admin family.
---

# Proxmox VM (qm)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: qm-cli-syntax
    source_url: https://pve.proxmox.com/pve-docs/qm.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "qm clone --full; qm template; qm disk move|resize|import; qm migrate --online --with-local-disks --targetstorage; qm importovf; --agent enabled,freeze-fs,fstrim_cloned_disks; --scsihw virtio-scsi-single; --balloon 0 disables; --hostpci ...,mapping,pcie,x-vga; --virtiofs dirid=<mapping>."
  - kind: external_fact
    subject: pve-vm-defaults
    source_url: https://pve.proxmox.com/pve-docs/chapter-qm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Web UI default CPU type for new VMs x86-64-v2-AES (qm.1 CLI default cputype kvm64); VirtIO SCSI single + IO thread recommended and default for new Linux VMs since 7.3; ballooning should normally stay enabled; USB/PCI passthrough blocks online migration."
-->

## Overview

`qm` manages QEMU/KVM VMs on one node. Most VM problems trace back to creation-time choices: firmware, controller, CPU type, disk options.

Labels: **[V]** checked against the cited Proxmox page on 2026-09-27; **[I]** inferred or from memory, re-verify.

**Apply the family guardrails from `proxmox-admin` first**: confirm the node, list guests, one named VMID, never touch other guests, a restorable backup before disk or storage work.

## When to use

- Create, configure, template, clone, resize, migrate or import a VM.
- A VM is locked, will not boot, is slow, or will not live-migrate.

**Not for:** containers (`proxmox-lxc`); GPU/vfio (`proxmox-gpu-passthrough`); storage pools (`proxmox-storage`); bridges (`proxmox-networking`); HA (`proxmox-cluster-ha`); backups (`proxmox-backup`); the guest OS (its own skill).

## Architecture first

The defaults and recipes below are for **x86-64 (amd64)** hosts. Check the node (`dpkg --print-architecture`) and the image's architecture before creating anything [I]. On an **arm64** host (PVE 9.2 for arm64, released 2026-08-05 [V: Roadmap, fetched 2026-09-27]): use an aarch64 image; firmware is OVMF only (SeaBIOS is x86-only); machine type `virt`, not `q35`; CPU `host` or `max`, because `x86-64-v*` and `kvm64` are x86-only [V: qm chapter, fetched 2026-09-27]. Live migration works only between nodes of the same architecture [V].

## Creation defaults (x86-64)

| Choice | Default pick | Pick the other when |
|---|---|---|
| Firmware `--bios` | `ovmf` + `--efidisk0 <st>:1,efitype=4m` for modern OSes and appliances [V syntax] | `seabios` (the PVE default [V]) for legacy OSes or images built for BIOS boot |
| Secure Boot keys | `pre-enrolled-keys=1` for Windows 11 and signed distros [I]; an older EFI disk without `ms-cert=2023k` needs the 2023 certificates enrolled (troubleshooting) [V: qm chapter, 2026-09-27] | `=0` for appliances that do not boot with keys enrolled (e.g. HA OS) [V: HA docs] |
| TPM | `--tpmstate0 <st>:1,version=v2.0` for Windows 11 [I syntax] | Omit for Linux unless measured boot is wanted |
| Machine `--machine` | `q35` (virtual PCIe; needed for PCIe passthrough) [V] | `i440fx` only for very old guests |
| Controller `--scsihw` | `virtio-scsi-single` + `iothread=1` per disk [V: recommended, default for new Linux VMs since 7.3] | Windows needs the VirtIO driver ISO at install [V] |
| Disk options | `discard=on` on thin storage, `ssd=1` so the guest issues TRIM, `cache` left at the no-cache default [V] | `aio` and `cache` changes only with a measured reason |
| CPU `--cpu` | Set it: `x86-64-v2-AES` (UI default; the CLI default is `kvm64` [V]) or `x86-64-v3` [I] on mixed clusters | `host` for single-node or identical-CPU clusters wanting full flags [V]; nested virtualization via the `nested-virt` flag (9.1+) [V] |
| Memory | Ballooning left on, with `--balloon <min>` below `--memory` [V] | `--balloon 0` for latency-sensitive or passthrough VMs (PCI passthrough pins all RAM) [I] |
| Guest agent | `--agent enabled=1` and install `qemu-guest-agent` in the guest [V] | Without it, shutdown is ACPI-only and backups cannot freeze the filesystem [I] |
| OS type `--ostype` | `l26` Linux, `win11` Windows 11/2022/2025 [V values] | Sets sane per-OS defaults; do not leave `other` |

Details, flags and examples: [references/vm-hardware-options.md](references/vm-hardware-options.md).

## Create from a qcow2 image (x86-64)

Recipe with checks: [references/vm-from-qcow2.md](references/vm-from-qcow2.md). Shape:

```bash
qm create <vmid> --name <name> --machine q35 --bios ovmf --ostype l26 \
  --cores 2 --memory 4096 --net0 virtio,bridge=<bridge> \
  --cpu x86-64-v2-AES --scsihw virtio-scsi-single --agent enabled=1 --tags <owner-tag>
qm set <vmid> --efidisk0 <storage>:1,efitype=4m,pre-enrolled-keys=0
qm set <vmid> --scsi0 <storage>:0,import-from=/path/image.qcow2,discard=on,ssd=1,iothread=1
qm set <vmid> --boot order=scsi0
qm disk resize <vmid> scsi0 32G    # grow only; never below the image's virtual size
qm start <vmid>                    # verify it boots, THEN: qm set <vmid> --onboot 1
```

## Cloud-init templates and clones

- Build once: import a cloud image as `scsi0`, add `--ide2 <storage>:cloudinit`, `--serial0 socket --vga serial0`, `--boot order=scsi0`, then `qm template <vmid>` [V].
- Per clone: `--ciuser`, `--sshkeys <file>`, `--ipconfig0 ip=<cidr>,gw=<gw>` or `ip=dhcp` [V].
- `--cicustom "user=<storage>:snippets/<file>.yaml"` **replaces** the generated user-data [V], so `--ciuser`/`--sshkeys` no longer reach the guest: put the user and keys in the YAML, check `qm cloudinit dump <vmid> user`, and test a console login [I].
- Clones: **linked** is the default from a template [V], small but tied to the template's base disk [I]; **full** (`--full --storage <st>`) is independent, for long-lived VMs [V]. Resize after cloning; cloud images ship small [I].

Walkthrough: [references/cloud-init-templates.md](references/cloud-init-templates.md).

## Disks, devices, migration and imports

- Disks: `qm disk resize` grows only [V], then grow inside the guest; `qm disk move` works live, keep the source until verified; `qm disk import` leaves `unusedN` to attach [V]. Detail: [references/vm-hardware-options.md](references/vm-hardware-options.md).
- USB (`--usb0 host=...`), PCI (`--hostpci0 ...,pcie=1` on q35) and resource mappings (`mapping=<id>`) [V syntax]: [references/vm-hardware-options.md](references/vm-hardware-options.md). USB or PCI passthrough blocks online migration [V]. GPUs, vfio and IOMMU: `proxmox-gpu-passthrough`.
- Live migration `qm migrate <vmid> <target> --online` [V] needs a cluster, a CPU type both nodes support, no local USB/PCI devices, and shared storage or `--with-local-disks --targetstorage` [V]. Detail: [references/import-and-migration.md](references/import-and-migration.md).
- Imports: ESXi wizard (Datacenter > Storage > Add > ESXi), `qm importovf`, or `qm disk import` of a Hyper-V VHDX; remove old guest tools first [V]. Steps and pitfalls: [references/import-and-migration.md](references/import-and-migration.md).
- Locked VMs, "KVM not available", stuck shutdowns, boot failures: [references/troubleshooting.md](references/troubleshooting.md).

## Anti-patterns

| Don't | Why |
|---|---|
| CPU type `host` on a cluster with mixed CPUs | Live migration fails or the guest crashes on the other node [V] |
| Pre-enrolled Secure Boot keys for an appliance that lacks signed boot | Drops to the UEFI shell instead of booting |
| Delete and recreate `efidisk0` to fix a boot problem | Resets OVMF settings and boot entries [V]; diagnose boot order and signatures first |
| `qm shutdown --forceStop 1` as a routine fix | Falls back to a hard stop; in-flight writes can be lost [V] |
| Switch an installed guest from SeaBIOS to OVMF or back | The installed bootloader will not match; the VM will not boot |
| Delete a template with linked clones | The clones lose their base disk |
| Import from ESXi with VMware Tools still installed | Leftover drivers and services break or slow the guest [V] |
| Skip the guest agent | No clean shutdown, IP reporting or filesystem freeze during backup |
| `--onboot 1` before the first verified boot | A broken VM restarts with every host boot |
| `qm unlock` while a backup or migration task still runs | Corrupts that task's state; check the Tasks log first |
