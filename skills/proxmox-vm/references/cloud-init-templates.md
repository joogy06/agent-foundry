# Cloud-init templates and clones

<!-- FRESHNESS:v1
volatility: low
anchors:
  - kind: external_fact
    subject: pve-cloud-init
    source_url: https://pve.proxmox.com/wiki/Cloud-Init_Support
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Cloud-init drive via --ide2 <storage>:cloudinit; --serial0 socket --vga serial0; qm template; qm clone (linked by default from a template); --sshkey(s), --ipconfig0; --cicustom user=<storage>:snippets/<file> replaces the generated config of that kind, file needed on every migration target node; qm cloudinit dump <vmid> user."
-->

Labels: [V] from https://pve.proxmox.com/wiki/Cloud-Init_Support and the qm man page, fetched 2026-09-27; [I] inferred, re-verify.

Placeholders: `<tpl>` template VMID, `<vmid>` clone VMID, `<storage>`, `<bridge>`. List guests first and pick free IDs (`proxmox-admin` guardrails).

## 1. Build the template (once)

```bash
cd /var/tmp && wget <distro cloud image URL>          # e.g. Debian genericcloud or Ubuntu cloud image [I]
sha256sum <image>                                     # compare with the published checksum

# x86-64 host shown; on an arm64 host use an aarch64 image, --machine virt, --bios ovmf + efidisk0, --cpu host (proxmox-vm SKILL.md)
qm create <tpl> --name <distro>-tpl --ostype l26 --machine q35 \
  --cores 2 --memory 2048 --net0 virtio,bridge=<bridge> \
  --cpu x86-64-v2-AES --scsihw virtio-scsi-single --agent enabled=1
qm set <tpl> --scsi0 <storage>:0,import-from=/var/tmp/<image>,discard=on,ssd=1,iothread=1   # [V]
qm set <tpl> --ide2 <storage>:cloudinit              # the cloud-init drive [V]
qm set <tpl> --boot order=scsi0                      # [V]
qm set <tpl> --serial0 socket --vga serial0          # most cloud images expect a serial console [V]
qm template <tpl>                                    # [V] converts; irreversible in place
```

- Cloud images are usually BIOS-bootable and many also UEFI; on x86-64, SeaBIOS (the default firmware) is the lower-risk choice for them, an exception to the OVMF default for installers and appliances [I]. If you choose OVMF add an `efidisk0`.
- Install `qemu-guest-agent` via user-data (packages) if the image lacks it [I].
- Do not boot the template itself; boot a clone to test [I].

## 2. Clone and configure

```bash
qm clone <tpl> <vmid> --name <name>                          # linked clone by default [V]
qm clone <tpl> <vmid> --name <name> --full --storage <st>    # independent full copy [V]
qm set <vmid> --ciuser <user> --sshkeys /path/to/key.pub     # [V]
qm set <vmid> --ipconfig0 ip=<cidr>,gw=<gateway>             # or ip=dhcp [V]
qm set <vmid> --nameserver <ip> --searchdomain <domain>      # [I]
qm disk resize <vmid> scsi0 +20G                             # cloud images ship small [I]
qm set <vmid> --tags <owner-tag>
qm start <vmid>
```

## 3. Custom user-data

- `cicustom` files **replace** the automatically generated config of that kind [V]. A custom `user=` file therefore discards everything `--ciuser`, `--sshkeys` and `--cipassword` set in section 2 [V: those settings live in the generated user-data; I], and a clone can come up with no usable login.
- Start from the generated config: `qm cloudinit dump <vmid> user > user.yaml` [V], then keep the intended user and `ssh_authorized_keys` in it and add your changes [I].
- Enable the `snippets` content type on a storage (directory-type) [I]; the file must be on storage available on every node the VM can migrate to, or the VM will not start [V]. Attach: `qm set <vmid> --cicustom "user=<storage>:snippets/user.yaml"` [V].
- Before relying on the clone: `qm cloudinit dump <vmid> user` shows the custom file's content in effect [I], then boot and test a login on the serial console (`qm terminal <vmid>` [V]) as well as over SSH.
- After changing cloud-init settings on an existing VM, regenerate the drive (`qm cloudinit update <vmid>` [I], or the UI "Regenerate Image") and reboot; cloud-init normally runs its per-instance modules only on first boot [I].

## Linked vs full clones

| | Linked | Full |
|---|---|---|
| Speed and space | Instant, shares base blocks [I] | Full copy time and space |
| Dependency | Needs the template's base disk; template cannot be removed [I] | None |
| Storage | Same storage as the template, which must support it (ZFS, LVM-thin, qcow2, Ceph) [I] | Any storage (`--storage`) [V] |
| Use for | Short-lived, many-copy labs and CI | Long-lived or production VMs |
