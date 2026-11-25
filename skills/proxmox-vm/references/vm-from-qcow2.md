# Recipe: UEFI VM from a vendor qcow2 image (an appliance OS as the worked case)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: qm-import-syntax
    source_url: https://pve.proxmox.com/pve-docs/qm.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "qm set --scsiN <storage>:0,import-from=<path>; qm disk import (alias importdisk); --scsihw virtio-scsi-single; disk options iothread, discard, ssd."
  - kind: external_fact
    subject: pve-arm64-vms
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.2 for arm64 released 2026-08-05; on arm64 hosts VMs use OVMF (AAVMF) only, the virt machine type, and ARM CPU models host or max; x86-64-v* and kvm64 models and SeaBIOS are x86-only; live migration only between same-architecture nodes."
-->

Labels: [V] verified 2026-09-27 (qm man page https://pve.proxmox.com/pve-docs/qm.1.html; for the HA OS example, https://www.home-assistant.io/installation/alternative); [I] re-verify.

Works for any vendor-shipped qcow2 appliance (router/firewall OS, NAS OS, home-automation OS). Take sizing, firmware and Secure Boot requirements from the vendor's install page; HA OS appears below only as one example.

Placeholders: `<vmid>`, `<storage>` (VM disk storage, e.g. a ZFS or LVM-thin pool), `<bridge>` (e.g. the LAN bridge). Never copy values from another host.

## 0. Read-only survey (show the output to the user)

```bash
qm list; pct list                 # existing guests: never touch them
pvesm status                      # storage names, free space, content types
pvesh get /cluster/nextid         # a free VMID [I]
ip -br link | grep vmbr           # bridges
free -h; nproc                    # capacity
dpkg --print-architecture         # amd64 or arm64 [I]; the image must match the host
df -h /var/tmp                    # room for the compressed AND unpacked image
```

## 1. Fetch and unpack the image

```bash
cd /var/tmp
wget <official image URL>         # often <appliance>-<version>.qcow2.xz
sha256sum <file>                  # compare with the published checksum when one exists
xz -d <appliance>-<version>.qcow2.xz     # or gunzip / unzip to match the download
```

## 2. Create the VM shell

Shown for an **x86-64 (amd64)** host. On an arm64 host (PVE 9.2 arm64 [V: Roadmap, 2026-09-27]) use an aarch64 image, `--machine virt` instead of `q35`, and `--cpu host` (or `max`) instead of `x86-64-v2-AES`; OVMF is the only firmware there [V: qm chapter, 2026-09-27].

```bash
qm create <vmid> --name <name> --machine q35 --bios ovmf --ostype l26 \
  --cores 2 --memory 4096 --balloon 0 --cpu x86-64-v2-AES \
  --net0 virtio,bridge=<bridge> --scsihw virtio-scsi-single \
  --agent enabled=1 --tags <owner-tag>        # --onboot only after a verified first boot
qm set <vmid> --efidisk0 <storage>:1,efitype=4m,pre-enrolled-keys=0
```

Size cores and memory from the vendor's stated minimum. `pre-enrolled-keys=0` is for appliances without signed boot; for example, HA OS asks for non-Secure-Boot OVMF and states a 2 GB / 2 vCPU minimum [V]. Use `pre-enrolled-keys=1` when the vendor supports Secure Boot. `--balloon 0` avoids ballooning surprises for an always-on appliance [I]. Enable `--agent` only if the appliance ships the QEMU guest agent (HA OS does [I]).

## 3. Attach the disk

Either (one step; `import-from` syntax [V], available since PVE 7.2 [I]):

```bash
qm set <vmid> --scsi0 <storage>:0,import-from=/var/tmp/<appliance>-<version>.qcow2,discard=on,ssd=1,iothread=1
```

or (two steps):

```bash
qm disk import <vmid> /var/tmp/<appliance>-<version>.qcow2 <storage>   # alias: qm importdisk [V]
qm config <vmid> | grep unused                                     # read the exact volume name
qm set <vmid> --scsi0 <storage>:<volume-from-unused0>,discard=on,ssd=1,iothread=1
```

## 4. Boot order, size, start

```bash
qm set <vmid> --boot order=scsi0
qemu-img info /var/tmp/<appliance>-<version>.qcow2 | grep 'virtual size'   # the imported disk starts at this size
qm disk resize <vmid> scsi0 +<N>G   # grow to the vendor's recommended size (HA OS: 32 GB total [V]); many appliances grow their data partition on boot [I]
qm start <vmid>
qm agent <vmid> network-get-interfaces   # after boot, to read the IP [I]
```

Then give the VM's MAC a DHCP reservation on your DHCP server and remove the downloaded image.

## 5. Verify

- `qm status <vmid>` = running; console shows the appliance banner, not the UEFI shell.
- If it drops to the UEFI shell: Secure Boot keys were enrolled or the boot order is wrong; stop the VM, recreate `efidisk0` with `pre-enrolled-keys=0`, set `--boot order=scsi0`.
- Only now enable autostart: `qm set <vmid> --onboot 1`.
- Snapshot the fresh install: `qm snapshot <vmid> fresh-install`.
- Add a vzdump job for **this VMID only**, to off-host storage (`proxmox-backup`).
