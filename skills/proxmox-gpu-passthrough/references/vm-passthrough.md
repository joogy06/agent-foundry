# VM passthrough and GPU splitting reference

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: pve-pci-passthrough
    source_url: https://pve.proxmox.com/pve-docs/chapter-qm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "vfio modules via /etc/modules-load.d; update-initramfs -u -k all; options vfio-pci ids=... disable_vga=1; softdep <mod> pre: vfio-pci; SR-IOV via max_vfs or sysfs sriov_numvfs; mdev types in /sys/bus/pci/devices/<id>/mdev_supported_types."
  - kind: external_fact
    subject: vendor-reset
    source_url: https://github.com/gnif/vendor-reset
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Supports AMD Polaris 10/11/12, Vega 10/20 (Vega 56/64, Radeon VII), Navi 10/12/14; install via dkms; must load early."
-->

Labels: **[V]** checked against the cited source on 2026-09-27; **[I]** inferred, so re-verify.

## Host setup, step by step

```bash
# 0. Read-only survey
lspci -nn | grep -Ei 'vga|3d|display|audio'            # ids like 10de:2704
lspci -nnk -s 01:00                                       # current driver [V]
cat /proc/cmdline; proxmox-boot-tool status               # which bootloader [I]

# 1. Kernel cmdline (only if needed: old Intel kernel, or iommu=pt)
#   GRUB:          GRUB_CMDLINE_LINUX_DEFAULT="quiet iommu=pt"  then update-grub
#   systemd-boot:  append to /etc/kernel/cmdline                then proxmox-boot-tool refresh   [I]

# 2. vfio modules [V]
printf 'vfio\nvfio_iommu_type1\nvfio_pci\n' > /etc/modules-load.d/vfio.conf

# 3a. Often nothing: PVE tries to make the device unavailable to the host itself [V].
#     Only if that fails, pick a binding method. First inventory EVERY function that
#     would match, and who uses it (host console, another VM's hostpci, an LXC /dev/dri):
lspci -nn -d 10de:2704; lspci -nn -d 10de:22bb           # one line per matching device [V]
grep -r hostpci /etc/pve/qemu-server/ ; grep -r -e dev -e cgroup2 /etc/pve/lxc/   # [I] other consumers

# 3b. By id: ONLY when every device with these ids is meant for passthrough.
#     'ids=' binds ALL devices with that vendor:device pair (kernel vfio-pci param) [V]
echo 'options vfio-pci ids=10de:2704,10de:22bb' > /etc/modprobe.d/vfio.conf
echo 'softdep nouveau pre: vfio-pci' >> /etc/modprobe.d/vfio.conf   # only if the host driver still grabs it [V]

# 3c. Two identical cards with different roles: do NOT use ids= or a blacklist. Bind by
#     ADDRESS with the kernel's per-device driver_override (sysfs ABI) [V]. A persistent
#     wrapper is Debian's driverctl package [I]:
#       apt install driverctl
#       driverctl set-override 0000:01:00.0 vfio-pci; driverctl set-override 0000:01:00.1 vfio-pci
#       driverctl list-overrides
#     Or skip host-side binding and let PVE claim the device by address at VM start [I].
#     Test on the console: the other card must keep its host driver after reboot.

#    Blacklisting the driver is broadest of all: every card of that vendor loses it [V].

# 4. Apply
update-initramfs -u -k all        # [V]
# reboot (ask first on a shared host)

# 5. Verify [V]
dmesg | grep -e DMAR -e IOMMU -e AMD-Vi
lsmod | grep vfio
lspci -nnk -s 01:00               # Kernel driver in use: vfio-pci
pvesh get /nodes/$(hostname)/hardware/pci --pci-class-blacklist ""
```

Driver names to blacklist when the host must not use the card [V]: NVIDIA `nouveau`, `nvidia*`; AMD `amdgpu`, `radeon`; Intel `i915` (and `xe` on newer Intel [I]). Blacklist only when **no** other device of the same vendor needs the driver on the host; binding by id is narrower, by address narrowest [I].

With OVMF you can disable VGA arbitration: `options vfio-pci ids=<vid>:<did> disable_vga=1` [V] (same all-matching-devices caveat).

## VM config

q35 + OVMF gives the best compatibility **for a new VM** [V]. On an **existing** guest, check first; changing firmware under an installed OS can leave it unbootable [I]:

```bash
qm config <vmid> | grep -E '^(bios|machine|efidisk0)'   # no bios line = SeaBIOS (default) [I]
# inside a Linux guest: [ -d /sys/firmware/efi ] && echo UEFI || echo BIOS   [I]
```

- New VM, or guest already UEFI: set OVMF with an EFI disk, which stores the firmware settings [V]:
  ```bash
  qm set <vmid> --machine q35 --bios ovmf --efidisk0 <storage>:1,efitype=4m   # [V] (pve qm docs, 2026-09-27)
  ```
- Existing SeaBIOS guest: keep SeaBIOS (`pcie=1` still works on q35) and the GPU's legacy ROM, or convert the OS to UEFI as a separate, backed-up and tested job (`mbr2gpt` on Windows; GRUB EFI reinstall on Linux) [I]. Changing i440fx to q35 can also rename guest NICs [I].
- OVMF needs a GPU with a UEFI-capable ROM; otherwise SeaBIOS [V].

```bash
qm set <vmid> -hostpci0 01:00,pcie=1,x-vga=1   # all functions, primary GPU [V]
qm set <vmid> -hostpci0 mapping=<map-id>,pcie=1  # cluster resource mapping [V]
```

Create the mapping in Datacenter > Resource Mappings (one entry per node, pointing at that node's device path) [V], or via the API: `pvesh create /cluster/mapping/pci --id <map-id> --map node=<node>,path=0000:01:00,id=<vid>:<did>` [I: check `pvesh usage /cluster/mapping/pci`].

- Set VM memory ballooning off and consider hugepages for large-BAR GPUs [I].
- The web console will not show the GPU output: attach a monitor or use RDP/VNC/Parsec/Sunshine inside the guest [V]. Compute-only (CUDA/OpenCL) needs no display [V].
- `allow_unsafe_interrupts=1` (`options vfio_iommu_type1 ...`) only when interrupt remapping is missing, and it can destabilise the host [V].

## IOMMU groups and ACS

- Acceptable group mates: other functions of the same card, the root port or PCIe bridge [V].
- Fix order [I]: another slot (CPU-attached slots usually isolate better than chipset ones) → BIOS update → a board with better ACS → last resort `pcie_acs_override=downstream,multifunction` (needs a patched kernel; the PVE kernel carries the patch [I]). The override lies to the kernel about isolation: devices in the fake group can still DMA to each other [V: "not without risks"].

## Reset problems

| Symptom | Cause | Fix |
|---|---|---|
| VM works once, hangs or black screen on second start | GPU does not reset (FLR missing) | Reboot host; AMD Polaris/Vega/Navi1x: `vendor-reset` [V] |
| `vendor-reset` loaded but no effect | Kernel 5.15+ uses the kernel's reset method list | `echo device_specific > /sys/bus/pci/devices/0000:01:00.0/reset_method` via a udev rule or hookscript [I] |
| NVIDIA code 43 | Old drivers blocked VMs; or broken ROM | Driver 465+ [I]; supply a clean `romfile` [V option] |
| `BAR 0: can't reserve [mem ...]` in dmesg, single-GPU host | Host boot framebuffer (efifb/simplefb) still holds the card | Add `initcall_blacklist=sysfb_init` to the kernel cmdline, or boot the host on another GPU/iGPU [I] |
| Old NVIDIA driver in Windows still shows code 43 | Driver sees a hypervisor | `cpu: host,hidden=1` [I]; better, update the driver |
| AMD RDNA2/3 reset issues | Not covered by vendor-reset [V] | Community workarounds vary; test before committing hardware [I] |

`vendor-reset` installs with DKMS and must load early (`/etc/modules`) [V; early loading]; improper init can hang the card [V].

## Splitting a GPU

### Intel iGPU

| Generation | Method | Status |
|---|---|---|
| 5th-7th gen Core (Broadwell, Skylake, Kaby Lake; GPU Gen8-9.5), Xeon E3 v4-v6 [V]; later 9th-gen/Comet Lake parts sometimes work [I] | **GVT-g** mediated devices: `kvmgt` module, `i915.enable_gvt=1`, `hostpci0: 00:02.0,mdev=i915-GVTg_V5_4` [V] | In-kernel; old hardware; x86 only [V] |
| Xe-LP iGPUs: Tiger Lake, Alder Lake, Raptor Lake (11th-14th gen Core) [V]; not Meteor Lake or Lunar Lake on the xe path [V] | **SR-IOV** via community `i915-sriov-dkms`: `i915.enable_guc=3 i915.max_vfs=7`, `echo 7 > /sys/devices/pci0000:00/0000:00:02.0/sriov_numvfs` [V] | Not Intel-supported; Secure Boot off; kernels 6.18-7.2 at release 2026.09.16; no Meteor/Lunar Lake on xe [V] |

Persist VF count with `sysfsutils` (`/etc/sysfs.d/`) [V]. Pass VFs (`00:02.1`...) to VMs as normal PCI devices [V]. Re-test after every PVE kernel update: DKMS must rebuild [I].

### NVIDIA vGPU

- PVE is an **officially supported** NVIDIA vGPU platform from vGPU software 18 [V].
- Requires NVIDIA vGPU licences (entitlement; license service such as DLS) and a supported datacenter/workstation GPU from NVIDIA's list [V]. Support tickets need a PVE **Basic or higher** subscription [V].
- Host: `pve-nvidia-vgpu-helper setup` (since pve-manager 8.3.4), install the NVIDIA host driver; Ampere and newer: `systemctl enable --now pve-nvidia-sriov@ALL.service` [V]. Then `mdev=<type>` on `hostpciN` [V].
- Guest clocks must be NTP-synced for licence checkout [V].
- Last tested by Proxmox: PVE 9.2.10, kernel 7.0.14-12-pve, vGPU 20.2 (page 2026-08-13) [V].
- Consumer GeForce "vgpu_unlock" hacks are unsupported and licence-violating territory; do not recommend them [I].

### SR-IOV NICs

Same pattern: `max_vfs=N` module option or `sriov_numvfs` in sysfs; pass VFs individually [V].
