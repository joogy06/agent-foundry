---
name: ubuntu-file-storage
description: Use when configuring file sharing and advanced storage on Ubuntu 24.04 LTS — NFS server/client, Samba/CIFS shares, ZFS pools and datasets, disk quotas, POSIX ACLs, snapshots, and storage monitoring. Part of the ubuntu-* skill family.
family: ubuntu
applies_when: os_family == debian
---

# Ubuntu Server 24.04 LTS — File Sharing & Advanced Storage

Companion skill to `ubuntu-server-admin` (parent). Covers NFS, Samba/CIFS, ZFS, disk quotas, POSIX ACLs, and storage monitoring on Ubuntu 24.04 LTS (Noble Numbat).

<HARD-RULE>
Never run destructive storage commands (zpool destroy, zfs destroy, mkfs, wipefs, dd) without explicit user confirmation. Always verify device paths with `lsblk` and `blkid` first.
</HARD-RULE>

---

## 1. NFS

```bash
# Server install
sudo apt install nfs-kernel-server
sudo systemctl enable --now nfs-server
```

### /etc/exports

```bash
/srv/nfs/data    10.0.1.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/iso     10.0.1.50(ro,sync,no_subtree_check)
# NFSv4 pseudo-root (Kerberos-ready — bind-mount exports under /srv/nfs4)
/srv/nfs4        10.0.1.0/24(rw,sync,fsid=0,crossmnt,no_subtree_check)
/srv/nfs4/data   10.0.1.0/24(rw,sync,no_subtree_check)
```

Key options: `sync` (safe default) vs `async` (faster, risk on crash) | `no_subtree_check` (recommended) | `root_squash` (default) vs `no_root_squash` (cautiously) | `all_squash,anonuid=1000,anongid=1000` (guest-like).

```bash
sudo exportfs -ra          # apply without restart
sudo exportfs -v           # show active exports
# NFSv4 pseudo-root bind mount
sudo mkdir -p /srv/nfs4/data && sudo mount --bind /srv/nfs/data /srv/nfs4/data
# Persist: add to /etc/fstab — /srv/nfs/data /srv/nfs4/data none bind 0 0
```

### Client (fstab and autofs)

```bash
sudo apt install nfs-common
# /etc/fstab
10.0.1.10:/data  /mnt/nfs/data  nfs4  defaults,_netdev,rsize=1048576,wsize=1048576  0  0

# Autofs on-demand mounting
sudo apt install autofs
# /etc/auto.master:  /mnt/nfs  /etc/auto.nfs  --timeout=300
# /etc/auto.nfs:     data  -rw,rsize=1048576,wsize=1048576  10.0.1.10:/data
sudo systemctl restart autofs
```

### Performance and Firewall

```bash
# Increase NFS threads — /etc/default/nfs-kernel-server
RPCNFSDCOUNT=16   # default 8; scale with cores/clients
# Stats: nfsstat -s (server) | nfsstat -c (client) | nfsiostat

# Firewall — NFSv4 only needs TCP 2049
sudo ufw allow from 10.0.1.0/24 to any port 2049 proto tcp comment 'NFSv4'
# NFSv3 also needs rpcbind (111) + pinned mountd/statd ports (see /etc/default/nfs-*)
```

---

## 2. Samba / CIFS

```bash
sudo apt install samba samba-common-bin
sudo systemctl enable --now smbd nmbd
```

### smb.conf (`/etc/samba/smb.conf`)

```ini
[global]
   workgroup = WORKGROUP
   server string = Ubuntu File Server
   server role = standalone server
   security = user
   map to guest = Never
   passdb backend = tdbsam
   log file = /var/log/samba/log.%m
   max log size = 1000
   use sendfile = yes
   aio read size = 16384
   aio write size = 16384
   # macOS: vfs objects = fruit streams_xattr  /  fruit:metadata = stream

[data]
   path = /srv/samba/data
   browseable = yes
   read only = no
   valid users = @smbgroup
   create mask = 0664
   directory mask = 0775
   force group = smbgroup

[homes]
   browseable = no
   read only = no
   create mask = 0700
   directory mask = 0700
   valid users = %S

[public]
   path = /srv/samba/public
   read only = yes
   guest ok = yes

[projects]
   path = /srv/samba/projects
   read only = no
   valid users = @smbgroup
   vfs objects = acl_xattr
   map acl inherit = yes
   store dos attributes = yes
   inherit acls = yes

[printers]
   path = /var/spool/samba
   printable = yes
   guest ok = no
```

### Users and Directory Setup

```bash
sudo adduser --no-create-home --shell /usr/sbin/nologin smbuser1
sudo smbpasswd -a smbuser1              # add Samba password
sudo pdbedit -L -v                       # list users
sudo smbpasswd -x smbuser1              # remove

sudo mkdir -p /srv/samba/{data,public,projects}
sudo groupadd smbgroup
sudo chgrp -R smbgroup /srv/samba/data /srv/samba/projects
sudo chmod 2775 /srv/samba/data /srv/samba/projects  # setgid
testparm && sudo systemctl reload smbd
```

### Audit Logging

```ini
# Add to share or [global] in smb.conf
   vfs objects = full_audit
   full_audit:prefix = %u|%I|%S
   full_audit:success = connect disconnect mkdir rmdir open rename unlink write
   full_audit:failure = connect
   full_audit:facility = local5
   full_audit:priority = notice
```

```bash
echo 'local5.* /var/log/samba/audit.log' | sudo tee /etc/rsyslog.d/samba-audit.conf
sudo systemctl restart rsyslog
```

### Firewall and Linux Client

```bash
sudo ufw allow from 10.0.1.0/24 to any port 139,445 proto tcp comment 'Samba'
sudo ufw allow from 10.0.1.0/24 to any port 137,138 proto udp comment 'NetBIOS'

# Linux CIFS client
sudo apt install cifs-utils
# /etc/fstab (credentials in /root/.smbcredentials, mode 600)
//10.0.1.10/data  /mnt/samba  cifs  credentials=/root/.smbcredentials,uid=1000,gid=1000,_netdev  0  0
# /root/.smbcredentials: username=smbuser1 / password=secret / domain=WORKGROUP
```

---

## 3. ZFS

<HARD-RULE>
ZFS pool destruction is irreversible. `zpool destroy` and `zfs destroy -r` permanently delete all data. Always snapshot or verify backups before any destructive operation.
</HARD-RULE>

<HARD-RULE>
Never mix ZFS and hardware RAID on the same disks. ZFS manages its own redundancy. Configure RAID controllers as JBOD passthrough.
</HARD-RULE>

<HARD-RULE>
You cannot remove a device from a RAIDZ/RAIDZ2 vdev once created. Plan vdev layout carefully before pool creation.
</HARD-RULE>

### Installation and Pool Creation

```bash
sudo apt install zfsutils-linux
zfs --version

# Mirror (RAID1)
sudo zpool create tank mirror /dev/sdb /dev/sdc
# RAIDZ1 (single parity, 3+ disks)
sudo zpool create tank raidz /dev/sdb /dev/sdc /dev/sdd
# RAIDZ2 (double parity, 4+ disks)
sudo zpool create tank raidz2 /dev/sdb /dev/sdc /dev/sdd /dev/sde

# Use /dev/disk/by-id/ paths for stability (prevents device name drift)
sudo zpool create tank mirror /dev/disk/by-id/scsi-SATA_WD_ABC123 /dev/disk/by-id/scsi-SATA_WD_DEF456

# Add SLOG and L2ARC
sudo zpool add tank log mirror /dev/nvme0n1p1 /dev/nvme1n1p1
sudo zpool add tank cache /dev/nvme0n1p2

zpool status && zpool list
```

### Datasets and Compression

```bash
sudo zfs create tank/data && sudo zfs create tank/backups
sudo zfs set mountpoint=/srv/data tank/data
sudo zfs set quota=500G tank/data              # limit space
sudo zfs set reservation=100G tank/backups     # guarantee space
sudo zfs set recordsize=1M tank/backups        # large sequential I/O
sudo zfs set recordsize=16K tank/vms           # databases / VM images
sudo zfs set compression=lz4 tank/data         # fast default
sudo zfs set compression=zstd tank/backups     # higher ratio, more CPU
zfs list -o name,used,avail,refer,mountpoint,compression,compressratio
```

### Snapshots and Send/Recv

```bash
sudo zfs snapshot tank/data@2026-03-23           # single snapshot
sudo zfs snapshot -r tank@daily-2026-03-23       # recursive (all children)
zfs list -t snapshot -o name,used,refer,creation
ls /srv/data/.zfs/snapshot/2026-03-23/           # browse without rollback
sudo zfs rollback tank/data@before-upgrade
sudo zfs destroy tank/data@old-snap

# Replication — full send, then incremental
sudo zfs send tank/data@2026-03-23 | ssh backuphost sudo zfs recv pool/backup/data
sudo zfs send -i tank/data@2026-03-22 tank/data@2026-03-23 \
  | ssh backuphost sudo zfs recv pool/backup/data
```

### Scrub and ARC Tuning

```bash
sudo zpool scrub tank
# Enable built-in weekly scrub timer (Ubuntu 24.04)
sudo systemctl enable --now zfs-scrub-weekly@tank.timer

# ARC stats
arc_summary
# Limit ARC to 8 GiB (coexistence with other services)
echo "options zfs zfs_arc_max=8589934592" | sudo tee /etc/modprobe.d/zfs.conf
sudo update-initramfs -u
# Immediate (no reboot): echo 8589934592 | sudo tee /sys/module/zfs/parameters/zfs_arc_max
```

---

## 4. Disk Quotas

### ext4

```bash
sudo apt install quota
# /etc/fstab — add usrquota,grpquota to mount options
UUID=xxxx  /data  ext4  defaults,usrquota,grpquota  0  2
sudo mount -o remount /data && sudo quotacheck -cugm /data && sudo quotaon /data
sudo setquota -u username 409600 512000 0 0 /data   # soft/hard blocks (1K), soft/hard inodes
sudo setquota -g devteam 2097152 2621440 0 0 /data
sudo setquota -t 604800 604800 /data                 # grace period (7 days)
sudo repquota -a                                      # report all
```

### XFS

```bash
# /etc/fstab: UUID=xxxx /data xfs defaults,usrquota,grpquota 0 2
sudo mount -o remount /data
sudo xfs_quota -x -c "limit bsoft=400m bhard=500m username" /data
sudo xfs_quota -x -c "limit -g bsoft=2g bhard=2500m devteam" /data
sudo xfs_quota -x -c "report -ugh" /data
```

---

## 5. POSIX ACLs

```bash
sudo apt install acl    # utilities; ext4/xfs have ACL support built in

# Set ACLs
sudo setfacl -m u:alice:rwx /srv/data/project
sudo setfacl -m g:auditors:r-x /srv/data/project
sudo setfacl -R -m g:devteam:rwx /srv/data/project  # recursive

# Default ACLs (inherited by new files/dirs)
sudo setfacl -d -m g:devteam:rwx /srv/data/project

# View / remove
getfacl /srv/data/project
sudo setfacl -x u:alice /srv/data/project            # remove entry
sudo setfacl -b /srv/data/project                    # remove all ACLs

# Backup and restore
getfacl -R /srv/data > /backup/data-acls.txt
setfacl --restore=/backup/data-acls.txt
```

### ACLs with Samba

Use `vfs objects = acl_xattr` with `map acl inherit = yes` and `store dos attributes = yes` in the smb.conf share (see the `[projects]` share in Section 2). Then set the base POSIX ACLs:

```bash
sudo setfacl -R -m g:smbgroup:rwx /srv/samba/projects
sudo setfacl -R -d -m g:smbgroup:rwx /srv/samba/projects
```

---

## 6. Storage Monitoring

### ZFS Health and SMART

```bash
zpool status -v                          # errors, scrub state, device health
zpool list -o name,size,alloc,free,cap,frag,health
zpool iostat -v 5                        # live I/O stats

sudo apt install smartmontools
sudo smartctl -H /dev/sda               # quick health
sudo smartctl -a /dev/sda               # full SMART data
sudo smartctl -t short /dev/sda         # self-test (~2 min)
sudo systemctl enable --now smartmontools
# /etc/smartd.conf: DEVICESCAN -a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -m admin@example.com
```

### Disk Space and I/O

```bash
df -h && df -i                           # filesystem + inode usage
du -sh /srv/data/* | sort -rh | head -20 # largest dirs
sudo apt install ncdu && sudo ncdu /srv  # interactive browser
sudo apt install sysstat
iostat -xz 5                             # per-device I/O (%util >80% = bottleneck)
sudo iotop -ao                           # per-process I/O
```

### Disk Space and ZFS Alerts

```bash
#!/bin/bash
# /usr/local/bin/disk-alert.sh — cron: */15 * * * * root /usr/local/bin/disk-alert.sh
THRESHOLD=85; MAILTO="admin@example.com"; HOST=$(hostname -f)
df -H --output=pcent,target | tail -n+2 | while read pct mount; do
  usage=${pct%\%}
  [ "$usage" -ge "$THRESHOLD" ] && echo "${mount} is ${pct} full on ${HOST}" \
    | mail -s "Disk Alert: ${HOST} ${mount} ${pct}" "$MAILTO"
done
```

```bash
#!/bin/bash
# /usr/local/bin/zfs-health-alert.sh — cron: */30 * * * * root /usr/local/bin/zfs-health-alert.sh
MAILTO="admin@example.com"; HOST=$(hostname -f)
HEALTH=$(zpool status -x 2>/dev/null)
[ "$HEALTH" != "all pools are healthy" ] && echo "$HEALTH" \
  | mail -s "ZFS ALERT: ${HOST}" "$MAILTO"
zpool list -Hp -o name,cap | while read pool cap; do
  [ "$cap" -ge 80 ] && echo "Pool ${pool} is ${cap}% full" \
    | mail -s "ZFS Space: ${HOST} ${pool} ${cap}%" "$MAILTO"
done
```

```bash
sudo chmod +x /usr/local/bin/disk-alert.sh /usr/local/bin/zfs-health-alert.sh
echo "*/15 * * * * root /usr/local/bin/disk-alert.sh" | sudo tee /etc/cron.d/disk-alert
echo "*/30 * * * * root /usr/local/bin/zfs-health-alert.sh" | sudo tee /etc/cron.d/zfs-health
```

---

## Ports Quick Reference

| Service | Ports | Protocol |
|---------|-------|----------|
| NFSv4 | 2049 | TCP |
| NFSv3 | 111, 2049, 32765-32767 | TCP/UDP |
| Samba | 139, 445 | TCP |
| Samba NetBIOS | 137, 138 | UDP |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Exporting NFS shares without client IP restrictions | Any machine on the network can mount and read/write; data exposure; unauthorized modifications | Specify client IPs in /etc/exports; use root_squash (default); consider Kerberos authentication for sensitive data |
| Creating ZFS pools without redundancy (single disk) | Disk failure loses entire pool; ZFS checksumming detects corruption but cannot repair without redundancy | Use mirror or raidz for any data that matters; single-disk pools only for replaceable cache/temp data |
| No snapshot schedule on ZFS datasets | ZFS's best feature (instant snapshots) goes unused; accidental deletion has no recovery path | Schedule automated snapshots (zfs-auto-snapshot or sanoid); retain hourly/daily/weekly; prune old snapshots |
| Samba shares without proper filesystem ACLs | Unix permissions too coarse for Windows clients; users get wrong access levels; permission complaints | Use POSIX ACLs (setfacl) to match Windows permission granularity; map Windows SIDs to Unix users/groups |
| Not monitoring disk usage on shared storage | Volume fills up; all clients fail simultaneously; usually discovered when a critical write fails | Monitor with df/zpool status; set alerts at 80% capacity; implement quotas for user/group limits |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core admin (LVM, firewall, SSH, systemd) | `ubuntu-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `ubuntu-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `ubuntu-databases` |
| Docker / containers | `ubuntu-docker-host` |
| DNS, DHCP, NTP | `ubuntu-network-infra` |
| Prometheus, Grafana, logging | `ubuntu-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `ubuntu-ollama-nvidia` |
