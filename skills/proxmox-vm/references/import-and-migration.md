# Importing VMs and live migration

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: esxi-import
    source_url: https://pve.proxmox.com/wiki/Migrate_to_Proxmox_VE
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "ESXi import-source storage via Datacenter > Storage > Add; tested ESXi 6.5-8.0; live import supported with downtime; vSAN and encrypted disks unsupported; snapshots slow import; remove old guest tools first; after import set --cpu x86-64-v2-AES --scsihw virtio-scsi-single; qm importovf."
  - kind: external_fact
    subject: qm-migrate
    source_url: https://pve.proxmox.com/pve-docs/qm.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "qm migrate <vmid> <target> --online --with-local-disks --targetstorage; qm remote-migrate is experimental."
-->

Labels: [V] from the cited Proxmox page, fetched 2026-09-27; [I] inferred, re-verify.

## Before any import

1. Inventory the source VM: firmware (BIOS or UEFI), disk count and sizes, NIC count and MACs, static IPs, licences tied to hardware IDs [I].
2. **Remove the old hypervisor's guest tools** (VMware Tools, Hyper-V integration services where removable) while still on the source [V].
3. Windows: pre-install the VirtIO drivers (virtio-win) on the source so the disk is found after the move [I; docs say attach the VirtIO ISO V].
4. Pick a free VMID and target storage on the Proxmox side; follow the `proxmox-admin` guardrails.

## VMware ESXi: the import wizard

1. Datacenter > Storage > Add > **ESXi**: host or vCenter address plus admin credentials [V]. It appears as an import-source storage.
2. Browse its content, select the VM, click Import; choose target storage, bridge, and options in the wizard [V].
3. **Live import** starts the VM on Proxmox while the disk data is still copying; the ESXi VM must be powered off first, so there is still downtime [V].
4. Limits [V]: tested ESXi 6.5 to 8.0; vSAN-backed disks and encrypted disks cannot be imported; VM snapshots make import much slower (consolidate first).
5. vCenter as a source works but is slower than a direct ESXi host [I].

## OVF / OVA

- CLI: `qm importovf <vmid> <file.ovf> <storage>` creates the VM from the manifest [V]; untar an OVA first (`tar xf file.ova`) [I].
- GUI OVA import exists on recent releases via a storage with the `import` content type [I].

## Hyper-V

No dedicated wizard [V: not covered on the migration page]. Manual path [I]:

1. Shut down the VM, export or copy its `.vhdx` (merge checkpoints first; `.avhdx` differencing disks must be merged).
2. `qm create` with matching firmware: Generation 2 = `--bios ovmf` + efidisk (Secure Boot keys usually needed for Windows), Generation 1 = SeaBIOS.
3. `qm disk import <vmid> /path/disk.vhdx <storage>` (qemu-img reads VHDX), attach the `unusedN` volume, set boot order.
4. Start on IDE/SATA if VirtIO drivers were not pre-installed, install drivers, then switch the disk to SCSI.

## After any import [V unless marked]

- `qm set <vmid> --cpu x86-64-v2-AES --scsihw virtio-scsi-single` [V].
- Network adapter names change; fix the guest network config [V].
- Install missing drivers (VirtIO ISO for Windows) and the QEMU guest agent [V].
- Switch emulated NICs (e1000, vmxnet3) to `virtio` once drivers are in [I].
- Re-activate licences if hardware IDs changed [I].
- Take a snapshot and a first backup (`proxmox-backup`).

## Live migration inside a cluster

`qm migrate <vmid> <target-node> --online [--with-local-disks] [--targetstorage <src>:<dst>]` [V].

| Prerequisite | Why |
|---|---|
| Nodes in one cluster with quorum (`proxmox-cluster-ha`) | Migration is a cluster operation [I] |
| CPU type available on both nodes | `host` on mixed CPUs fails or crashes the guest [V] |
| No USB/PCI passthrough | Local hardware cannot move [V]; a resource mapping present on both nodes allows **offline** migration only; live needs a PCI mapping marked live-migration-capable (mediated/vGPU cases) [V] |
| Shared storage, or `--with-local-disks` | Otherwise disks cannot follow; local disk copy takes time and bandwidth [V] |
| Same bridge names and VLANs on the target | NIC would attach to nothing [I] |
| Free RAM on the target | Migration fails, or HA overcommits [I] |
| Similar MTU on migration network | 9.1 fixed one MTU-related failure [V]; mismatches still cost time [I] |

`qm remote-migrate` to a different cluster uses an API token and is marked **experimental** [V]; test before relying on it.
