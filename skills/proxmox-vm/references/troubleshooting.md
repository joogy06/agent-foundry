# VM troubleshooting (qm)

<!-- FRESHNESS:v1
volatility: low
anchors:
  - kind: external_fact
    subject: qm-troubleshooting
    source_url: https://pve.proxmox.com/pve-docs/qm.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "qm unlock, qm shutdown --forceStop (make sure the VM stops), qm stop, qm disk rescan --vmid, qm showcmd, qm config, qm enroll-efi-keys (VM shut down) exist; cputype CLI default kvm64; EFI disks created before pve-edk2-firmware 4.2025.05-1 lack the Microsoft 2023 certificates; recreating efidisk0 resets OVMF settings."
-->

Labels: [V] from the qm man page, fetched 2026-09-27; [I] inferred or field experience, re-verify. Apply the `proxmox-admin` guardrails: every fix below targets one named VMID you own.

| Symptom / message | Likely cause | Fix |
|---|---|---|
| `TASK ERROR: VM is locked (backup)` / `(snapshot)` / `(migrate)` / `(clone)` | A task holds the lock, or a crashed task left it [I] | Check the Tasks log and `ps aux | grep <vmid>` for a running vzdump/migration. Only when nothing runs: `qm unlock <vmid>` [V]. Never unlock another owner's guest. |
| `can't lock file '/var/lock/qemu-server/lock-<vmid>.conf' - got timeout` | Another qm/API operation on the same VM is running or hung [I] | Wait for or identify that task; do not delete the lock file by hand |
| `KVM virtualisation configured, but not available` | VT-x/AMD-V disabled in firmware, or running nested without nesting [I] | Enable virtualization in the host BIOS/UEFI; for nested hosts enable `nested-virt` on the outer VM. Do not set `--kvm 0` except for tests (very slow) |
| `unable to find configuration file for VM <vmid>` | The VM lives on another cluster node, or the ID is wrong [I] | `pvesh get /cluster/resources --type vm` to find the node; run there |
| VM drops to the UEFI shell / "BdsDxe: failed to load Boot0001" | Wrong boot order, disk not attached, lost boot entry, or Secure Boot rejecting the loader (unsigned, or signed only with the 2023 CA on an EFI disk that holds only the 2011 certificates) [I; 2023 CA V: qm chapter, 2026-09-27] | Diagnose first, **keep `efidisk0`**: `qm config <vmid>` for `boot: order=`, the disk entry and the `efidisk0` `ms-cert=` marker; in the OVMF menu (Esc at boot) check Boot Manager and whether Secure Boot is on. Fix the boot order, or turn Secure Boot off in the OVMF menu for an unsigned loader [V: qm chapter]. Deleting and recreating `efidisk0` resets every OVMF setting and boot entry [V]: last resort, after a backup, and named as such |
| Start task warns about missing Microsoft certificates, or a new Windows ISO will not boot | EFI disk predates `pve-edk2-firmware` 4.2025.05-1 and lacks the 2023 certificates (marker not `ms-cert=2023k`) [V: qm chapter, 2026-09-27] | Windows with BitLocker: first run `manage-bde -protectors -disable <drive>` in the guest for every BitLocker drive, or the next boot asks for the recovery key [V]. Then shut the VM down and run `qm enroll-efi-keys <vmid>` [V], or UI Hardware > EFI Disk > Disk Action > Enroll Updated Certificates [V]. Follow Microsoft's CVE-2023-24932 guidance inside Windows [V] |
| "No bootable device" on SeaBIOS | Image is UEFI-only, or the boot order lacks the disk [I] | Switch to OVMF only for a fresh UEFI image; set `--boot order=scsi0` |
| Windows installer sees no disk | No VirtIO SCSI driver [V: VirtIO ISO needed] | Attach the virtio-win ISO as a second CD-ROM and load the driver |
| Shutdown hangs | Guest ignores ACPI, or the agent is enabled but not installed [I] | `qm shutdown <vmid> --timeout 300` [V] (no `--forceStop`). If it still runs: check the console and `qm guest cmd <vmid> ping` [V], fix the agent setting (install `qemu-guest-agent`, or `--agent 0` if it is absent), retry. `--forceStop 1` "makes sure the VM stops" [V] by hard-stopping it after the timeout, like `qm stop`: both can lose in-flight writes, so each is a separate, explicitly confirmed data-loss decision naming the VMID (`proxmox-admin` guardrail 8) |
| Slow disk I/O | `lsi` controller, no iothread, `cache=writethrough`, or thin pool full [I] | `virtio-scsi-single` + `iothread=1`; check `pvesm status` for pool usage |
| Disk full inside guest after `qm disk resize` | Partition/filesystem not grown [I] | Grow inside the guest (`growpart` + `resize2fs`/`xfs_growfs`, or Disk Management) |
| Config shows `unused0` after an import | `qm disk import` attaches nothing by itself [V] | `qm set <vmid> --scsi0 <storage>:<volume>` |
| Live migration fails with CPU errors | CPU type `host` across different CPUs [V] | Set a common model (`x86-64-v2-AES`/`v3`), cold-restart the VM, then migrate |
| VM created by CLI performs poorly or lacks AVX | `--cpu` omitted, so `kvm64` [V] | `qm set <vmid> --cpu x86-64-v2-AES` (or `v3`/`host`), then full stop and start |
| Windows with CPU `host` + VBS freezes on Intel (9.2) | Known issue [V: Roadmap] | Update `qemu-server`, set machine version `11.0+pve2` [V] |
| Need the raw QEMU command line | Debugging option mapping | `qm showcmd <vmid> --pretty` [V] |

Config changes to CPU, machine type or firmware need a full stop and start (not a guest reboot) to take effect [I]; the UI shows pending changes in orange.
