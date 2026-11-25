# ZFS on Proxmox VE: layout, tuning and repair

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-zfs-admin-guide
    source_url: https://pve.proxmox.com/pve-docs/chapter-sysadmin.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Admin guide 9.2.12: zpool create -o ashift=12; mirrors favoured for VMs; ARC 10% RAM max 16 GiB in /etc/modprobe.d/zfs.conf; special vdev redundancy must match the pool; boot-disk replace uses sgdisk -R/-G, zpool replace, proxmox-boot-tool format/init. PVE 9.2 ships ZFS 2.4 (arcstat renamed zarcstat)."
-->

Labels: [V] = Proxmox admin guide 9.2.12 or roadmap, checked 2026-09-27; [I] = inferred, re-verify.

## Pool layout

| Layout | Usable | Survives | Use for |
|---|---|---|---|
| mirror (2-way) | 50% | 1 disk per vdev | Small hosts, boot pools |
| striped mirrors (RAID10) | 50% | 1 disk per mirror | VM pools: best IOPS [V] |
| RAIDZ1 | N-1 | 1 disk | Bulk/backup data on few disks; risky with large HDDs [I] |
| RAIDZ2 | N-2 | 2 disks | Bulk data, 6+ disks |
| dRAID | varies | configured | 10-15+ disks; faster rebuild via distributed spare [V] |

- RAIDZ expansion (add one disk to an existing RAIDZ vdev) exists since OpenZFS 2.3 [I]; old data keeps the old data-to-parity ratio until rewritten [I].
- Create (always by-id):

```bash
ls -l /dev/disk/by-id/ | grep -v part        # identify disks by model + serial
lsblk -o NAME,SIZE,SERIAL,FSTYPE,MOUNTPOINTS  # no filesystem, mount or partitions on the targets
zpool status; zpool import                   # not in a live or importable pool
pvs; wipefs -n /dev/disk/by-id/<id1>          # no LVM/Ceph PV or signature (-n: list only)
zpool create -n -o ashift=12 tank mirror <id1> <id2> mirror <id3> <id4>   # dry run: check layout
zpool create -o ashift=12 tank mirror <id1> <id2> mirror <id3> <id4>
pvesm add zfspool tank-vm --pool tank --content images,rootdir --sparse 1
```

- No `-f` by default: it forces use of devices that **appear in use** [V 2026-09-27: OpenZFS zpool-create(8)]. If ZFS refuses, find out why; use `-f` only once the checks above prove the "in use" signature is stale (for example, a disk you wiped yourself) [I].

## Block sizes

- `ashift=12` (4 KiB) is right for nearly all disks; must be >= the physical sector size; cannot change later [V].
- `volblocksize` (zvols, i.e. VM disks) is fixed at zvol creation [V]; set the storage default with `pvesm set <id> --blocksize 16k` [V: option exists; 9.2 validates 512 B to 16 MiB, power of two]. Current OpenZFS default is 16k [I].
- On RAIDZ, small volblocksize wastes space: with ashift 12 an 8k block on RAIDZ2 writes 8k + 4k + 4k parity [V]. Options: larger volblocksize (moves amplification into the guest), or mirrors [V].
- `recordsize` (datasets: containers `subvol-*`, directory storage) defaults to 128k; lower it (16k) for databases, raise it (1M) for media/backup datasets [I].
- `compression=lz4` (or zstd) is on by default for PVE-created pools [I]; leave it on.

## ARC sizing

- Default since PVE 8.1: 10% of RAM, max 16 GiB, written to `/etc/modprobe.d/zfs.conf` at install [V]. Older installs follow the ZFS default (50%; 62.5% with ZFS 2.3+) until set [V].
- Rule of thumb: 2 GiB base + 1 GiB per TiB of pool [V]; more if the pool is HDD-backed and read-heavy.

```bash
# Edit /etc/modprobe.d/zfs.conf (do not overwrite other options), e.g. 8 GiB:
#   options zfs zfs_arc_max=8589934592
update-initramfs -u -k all                                            # if root is on ZFS; applies at reboot
echo 8589934591 > /sys/module/zfs/parameters/zfs_arc_min              # live, only if arc_min >= new max
echo 8589934592 > /sys/module/zfs/parameters/zfs_arc_max              # live
zarcstat 1 3        # ZFS 2.4 name; arcstat on older versions [V]
```

If the new max is at or below `zfs_arc_min` (default 1/32 of RAM), also set `zfs_arc_min` below it, or the max is ignored [V].

## SLOG, L2ARC, special vdev

- SLOG (`log`) only helps **sync** writes; use a small mirrored enterprise SSD with power-loss protection [V]; size about half of RAM at most [V].
- L2ARC (`cache`) costs RAM for its headers; add it only after the ARC is maxed and hit rates stay low [I].
- Special vdev: metadata and, with `special_small_blocks=<size>`, small blocks [V]. Redundancy must match the pool; adding one cannot be undone [V]. If `special_small_blocks` >= recordsize, all data lands on it and fills it [V].

```bash
zpool add tank special mirror <ssd1> <ssd2>
zfs set special_small_blocks=16K tank/<dataset>
```

Keep `special_small_blocks` below the dataset recordsize and, if newer OpenZFS applies it to zvols, below volblocksize [I: re-verify on ZFS 2.4], or every VM block lands on the special vdev.

## Replacing a failed disk

1. Identify: `zpool status -v` (by-id name), `smartctl -i /dev/disk/by-id/<id>` for the serial, and match the physical bay before pulling. Check the **new** disk is blank and unused (`lsblk`, `wipefs -n`, not in `pvs` or any pool): `-f` would override ZFS's in-use check on it [V 2026-09-27: OpenZFS zpool-replace(8)].
2. Data-only pool:

```bash
zpool offline tank <old-id>          # optional, if still attached
zpool replace tank <old-id> <new-id>     # -f only for a proven-stale label on the NEW disk
zpool status -v tank                  # watch resilver
```

3. **Boot pool** (installer layout: p1 BIOS boot, p2 ESP, p3 ZFS) [V]. **`sgdisk -R` writes to the disk named after `-R`: swapping the arguments wipes the healthy disk's partition table.** Check both by-id names with `lsblk` first. For a dead disk, use the name or GUID `zpool status` shows as the old device:

```bash
proxmox-boot-tool status                          # systemd-boot or grub?
sgdisk <healthy-disk> -R <new-disk>               # copy partition table
sgdisk -G <new-disk>                              # new GUIDs
zpool replace rpool <old-disk>-part3 <new-disk>-part3
proxmox-boot-tool format <new-disk>-part2
proxmox-boot-tool init <new-disk>-part2 [grub]    # grub if status says GRUB
```

Plain GRUB (installs from 6.3 or earlier, never migrated): `grub-install <new disk>` instead [V].

4. Afterwards: `zpool status` clean, `zpool scrub` later, confirm `proxmox-boot-tool status` lists both ESPs.

## Health and notification

- `zfs-zed` mails root on pool events; `ZED_EMAIL_ADDR` in `/etc/zfs/zed.d/zed.rc` [V].
- Monthly scrub is scheduled by the Debian zfsutils cron job [I]; check `zpool status` for the last scrub date.
- Trim: `zpool set autotrim=on <pool>` or periodic `zpool trim <pool>` [I]; both require SSDs that handle discard well.

## Encryption

Native ZFS encryption works per dataset. Caveats [V]: an encrypted root needs care with GRUB boot, keys must be loaded at boot (no auto-unlock by default), and a lost key means lost data. Replication of encrypted datasets has its own limits [I]; test before relying on it.
