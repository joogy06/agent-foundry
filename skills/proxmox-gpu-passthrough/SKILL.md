---
name: proxmox-gpu-passthrough
description: Proxmox VE GPU and PCIe passthrough - IOMMU (intel_iommu, amd_iommu, iommu=pt), vfio-pci binding, blacklisting nouveau/nvidia/amdgpu/i915, IOMMU groups and ACS override, hostpci options (pcie=1, x-vga, rombar, romfile, mapping), NVIDIA, AMD reset bug and vendor-reset, Intel iGPU SR-IOV and GVT-g, NVIDIA vGPU licensing, and sharing a GPU into LXC via /dev/dri or nvidia device nodes for Jellyfin, Plex (Quick Sync, NVENC), Frigate or Ollama. Use for "No IOMMU", BAR 0 can't reserve, code 43, black screen, or device busy errors.
---

# Proxmox GPU Passthrough

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: pve-pci-passthrough
    source_url: https://pve.proxmox.com/pve-docs/chapter-qm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "IOMMU on by default for AMD and for Intel on kernel 6.8+; modules vfio, vfio_iommu_type1, vfio_pci via /etc/modules-load.d; options vfio-pci ids=; softdep; lspci -nnk shows vfio-pci; pcie=on needs q35; hostpci driver=keep|vfio, legacy-igd needs i440fx; GVT-g on 5th-7th gen Core with i915.enable_gvt=1 and kvmgt; passed-through device unusable by host or other VMs."
  - kind: external_fact
    subject: nvidia-vgpu-on-pve
    source_url: https://pve.proxmox.com/wiki/NVIDIA_vGPU_on_Proxmox_VE
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE officially supported from NVIDIA vGPU software 18; support needs NVIDIA vGPU entitlement plus PVE Basic+ subscription; pve-nvidia-vgpu-helper setup; Ampere+ needs pve-nvidia-sriov@ALL.service; latest tested PVE 9.2.10, kernel 7.0.14-12-pve, vGPU 20.2 (page updated 2026-08-13)."
  - kind: external_fact
    subject: i915-sriov-dkms
    source_url: https://github.com/strongtz/i915-sriov-dkms
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Community (not Intel) DKMS module for iGPU SR-IOV, release 2026.09.16, kernels 6.18-7.2, Xe_LP (Tiger/Alder/Raptor Lake) and newer; no MTL/LNL on xe; needs Secure Boot off; i915.enable_guc=3 i915.max_vfs=7."
-->

## Overview

Two different jobs share this name. **Passthrough** hands a whole PCIe device to one VM through vfio: the host and every other guest lose it. **Sharing** exposes the host's GPU driver device nodes to one or more LXC containers: the host keeps the GPU and containers use it together. Pick the job first; most failures come from mixing them.

Labels: **[V]** checked against the cited source on 2026-09-27; **[I]** inferred or community knowledge, so re-verify. Platform: **PVE 9.2** (2026-05-21), kernel 7.0 [V].

## When to use

- Passing a GPU, HBA or NIC into a VM; errors like "No IOMMU detected", "IOMMU group is not viable", NVIDIA code 43, a black screen, or a VM that starts once and never again (reset bug).
- Giving Jellyfin, Plex, Frigate or Ollama in an LXC hardware transcoding or CUDA.
- Splitting one GPU: Intel iGPU SR-IOV, GVT-g, NVIDIA vGPU.

**Not for:** VM basics (machine type, OVMF, disks) in `proxmox-vm`; general container config, idmaps and unprivileged setup in `proxmox-lxc`; the guest application itself (`frigate-nvr`, `ubuntu-ollama-nvidia` patterns); buying a GPU (`pc-gpu-tiering`). Changing kernel parameters or host drivers means a host reboot: follow the `proxmox-admin` guardrails and ask first on a shared host.

## Decide: VM passthrough, LXC sharing, or split

| Need | Choose | Host keeps GPU? |
|---|---|---|
| Windows gaming or a guest needing the full GPU and its own driver | VM passthrough | **No** |
| Media transcoding or detection in containers | LXC sharing of `/dev/dri` (Intel/AMD) or nvidia nodes | Yes |
| Several VMs on one Intel iGPU | SR-IOV (11th-14th gen Core iGPUs, community module) or GVT-g (5th-7th gen Core only) | Yes (PF) |
| Several VMs on one datacenter NVIDIA card | NVIDIA vGPU (licensed) | Yes |
| The only GPU is the host console | LXC sharing, or accept a headless host with serial/IPMI | Depends |

## VM passthrough: the sequence

Full commands and vendor notes: [references/vm-passthrough.md](references/vm-passthrough.md).

1. **Firmware**: enable VT-d / AMD-Vi (IOMMU), and Above 4G decoding / Resizable BAR as the card needs [I].
2. **Kernel**: IOMMU is on by default for AMD and for Intel with kernel 6.8+; older kernels need `intel_iommu=on` [V]. `iommu=pt` may improve performance [V]. Edit `/etc/default/grub` + `update-grub`, or `/etc/kernel/cmdline` + `proxmox-boot-tool refresh` on systemd-boot/ZFS installs [V: sysadmin guide].
3. **Modules**: `vfio`, `vfio_iommu_type1`, `vfio_pci` in `/etc/modules-load.d/vfio.conf`, then `update-initramfs -u -k all` [V].
4. **Verify IOMMU**: `dmesg | grep -e DMAR -e IOMMU -e AMD-Vi` [V].
5. **Groups**: `pvesh get /nodes/<node>/hardware/pci --pci-class-blacklist ""` [V]. The device may share a group only with its own functions (GPU + HDMI audio) or its root port/bridge [V]. Otherwise try another slot [V]; ACS override is a last resort with security cost [V].
6. **Bind to vfio** only if PVE's automatic unbind fails [V]. First list every device matching the ids (`lspci -nn -d <vid:did>`) and who uses it: `options vfio-pci ids=` binds **all** of them, and blacklisting a driver takes it from every card of that vendor [V]. Identical cards with different roles: bind by address with `driver_override` [V]. Add `softdep <driver> pre: vfio-pci` if the host driver still wins [V].
7. **Check**: `lspci -nnk` shows `Kernel driver in use: vfio-pci` (or no driver line) [V].
8. **VM**: `qm set <vmid> -hostpci0 <bus:dev>,pcie=1[,x-vga=1]` [V]. q35 + OVMF (with an `efidisk0`) for a **new** VM [V]; an installed SeaBIOS guest may not boot on OVMF, so check first [I]. Omit the `.function` to pass all functions [V]. Prefer a **resource mapping** (Datacenter > Resource Mappings, then `mapping=<id>`) on clusters [V].

### hostpci options

| Option | Use [V] |
|---|---|
| `pcie=1` | PCIe port; needs q35 |
| `x-vga=1` | Device is the VM's primary GPU; ignores the `vga` setting |
| `rombar=0` | Hide the ROM; some devices need it |
| `romfile=<name>` | Custom vBIOS from `/usr/share/kvm/` |
| `driver=keep` | Do not reset or bind to vfio-pci |
| `legacy-igd=1` | Intel IGD legacy mode; needs i440fx and `vga: none` |
| `mdev=<type>` | Mediated device (GVT-g, vGPU) |
| `vendor-id`, `device-id`, `sub-*` | Override IDs the guest sees |

## Vendor notes

| Vendor | Watch for |
|---|---|
| NVIDIA consumer | Needs a UEFI-capable ROM for OVMF [V]; code 43 on old drivers was a VM-detection check, removed in driver 465+ [I]; pass the audio function too |
| AMD | Polaris, Vega, Navi 10/12/14 suffer the reset bug; `vendor-reset` DKMS module fixes those [V]; on kernel 5.15+ also set `reset_method` to `device_specific` [I]. RDNA2+ is not in vendor-reset's list [V] |
| Intel iGPU | Whole-iGPU passthrough loses host console and Quick Sync for LXC; prefer sharing or SR-IOV [I] |

Intel SR-IOV/GVT-g and NVIDIA vGPU detail: [references/vm-passthrough.md](references/vm-passthrough.md#splitting-a-gpu).

## LXC sharing

Recipe for Intel/AMD `/dev/dri` and NVIDIA nodes, with Frigate/Jellyfin/Ollama checks: [references/lxc-gpu-sharing.md](references/lxc-gpu-sharing.md).

- Use `pct set <ctid> --dev0 /dev/dri/renderD128,gid=<render-gid-in-ct>` [V syntax]; works for unprivileged containers without raw cgroup lines [I].
- NVIDIA: install the **same driver version** on host and in the container (container without the kernel module), then pass `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools` [I].
- A GPU bound to vfio for a VM cannot also be shared into LXC [V: host cannot use it].

## Verify

| Check | Command |
|---|---|
| IOMMU on | `dmesg \| grep -e DMAR -e IOMMU -e AMD-Vi` [V] |
| Groups | `pvesh get /nodes/<node>/hardware/pci --pci-class-blacklist ""` [V] |
| Driver bound | `lspci -nnk -s <bus:dev>` [V] |
| Modules | `lsmod \| grep vfio` [V] |
| In VM | `nvidia-smi`, `lspci` in guest, Device Manager on Windows [I] |
| In LXC | `ls -l /dev/dri`, `vainfo`, `nvidia-smi` inside the container [I] |

## Anti-patterns

| Don't | Why |
|---|---|
| Pass through the GPU the host console or another LXC uses | The host and every other consumer lose it at VM start |
| ACS override as a first step | Breaks isolation between devices; try another slot first |
| Blacklist `i915`/`amdgpu` when LXC containers share that GPU | Removes the driver they depend on |
| Enable `allow_unsafe_interrupts` casually | The docs warn it can destabilise the host |
| Edit GRUB on a systemd-boot host | Change never applies; check `proxmox-boot-tool status` |
| Expect the GPU output in noVNC | Passed-through frame buffers are not visible in the web console [V] |
| Plan live migration or HA for a VM with a passed-through device | Passthrough blocks live migration [V]; only mappings marked `live-migration-capable` (recent NVIDIA) try it, as an experimental feature [V] |
| Privileged LXC just to reach the GPU | `devN` with a gid gives access unprivileged |
| Load unsigned DKMS modules (SR-IOV, vendor-reset, NVIDIA) with Secure Boot on | They will not load; enroll the DKMS MOK or disable Secure Boot [I] |
| Reboot a shared host to test a cmdline change without asking | Every guest goes down |
