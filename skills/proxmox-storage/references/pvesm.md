# pvesm command reference

<!-- FRESHNESS:v1
volatility: low
anchors:
  - kind: external_fact
    subject: pvesm-cli
    source_url: https://pve.proxmox.com/pve-docs/chapter-pvesm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "pvesm status/list/scan/add/set/remove syntax per admin guide 9.2.12; storage definitions live in /etc/pve/storage.cfg."
-->

Labels: [V] = Proxmox admin guide 9.2.12, checked 2026-09-27; [I] = inferred, re-verify.

## Commands [V]

```bash
pvesm status                              # read-only first
pvesm list <storage> [--content images]
pvesm scan nfs <server>
pvesm scan lvmthin <vg>
pvesm scan iscsi <portal>
pvesm add nfs <id> --server <ip> --export <path> --content iso,backup
pvesm set <id> --content images,rootdir   # or --disable 1
pvesm remove <id>                         # removes the definition, not the data
```

## Notes

- A default install has `local` (dir, `/var/lib/vz`) plus `local-lvm` (LVM-thin) on ext4/xfs, or `local-zfs` on a ZFS install [I].
- `pvesm remove` deletes only the definition in `/etc/pve/storage.cfg`; data stays on the backend [I].
- Restrict a storage to some nodes with `--nodes n1,n2`; mark shared only if every node sees the same data [I].
