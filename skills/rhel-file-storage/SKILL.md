---
name: rhel-file-storage
description: Use when configuring file sharing and advanced storage on RHEL 9 (and AlmaLinux/Rocky 9) — NFS server/client with nfs-utils, Samba/CIFS shares with SELinux contexts, Stratis storage management, XFS administration, VDO deduplication, disk quotas, POSIX ACLs, snapshots, and storage monitoring. Part of the rhel-* skill family.
family: rhel
applies_when: os_family == rhel
---

# Red Hat Enterprise Linux 9 — File Sharing & Advanced Storage

Companion skill to `rhel-server-admin` (parent). Covers NFS, Samba/CIFS, Stratis, LVM-VDO, XFS administration, disk quotas, POSIX ACLs, and storage monitoring on RHEL 9.x (and compatible: AlmaLinux 9, Rocky Linux 9, Oracle Linux 9).

<HARD-RULE>
Never run destructive storage commands (stratis pool destroy, stratis filesystem destroy, mkfs, wipefs, dd, lvremove, vgremove, pvremove) without explicit user confirmation. Always verify device paths with `lsblk` and `blkid` first.
</HARD-RULE>

<HARD-RULE>
Never disable SELinux to "fix" NFS or Samba issues. Set the correct SELinux booleans and file contexts instead. Use `ausearch -m AVC --start recent` and `sealert` to diagnose denials.
</HARD-RULE>

<HARD-RULE>
Stratis is the recommended modern storage solution on RHEL 9. ZFS is NOT in RHEL repositories and is not supported by Red Hat. Do not suggest ZFS on RHEL systems.
</HARD-RULE>

---

## 1. NFS (nfs-utils)

```bash
sudo dnf install nfs-utils
sudo systemctl enable --now nfs-server
cat /proc/fs/nfsd/versions       # expect: +4 +4.1 +4.2
```

### /etc/exports

```bash
/srv/nfs/data    10.0.1.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/iso     10.0.1.50(ro,sync,no_subtree_check)
# NFSv4 pseudo-root
/srv/nfs4        10.0.1.0/24(rw,sync,fsid=0,crossmnt,no_subtree_check)
/srv/nfs4/data   10.0.1.0/24(rw,sync,no_subtree_check)
```

Key options: `sync` (safe) vs `async` (faster, risk on crash) | `no_subtree_check` (recommended) | `root_squash` (default) vs `no_root_squash` | `all_squash,anonuid=1000,anongid=1000` (guest-like).

```bash
sudo exportfs -ra && sudo exportfs -v       # apply and verify
# NFSv4 bind mount
sudo mkdir -p /srv/nfs4/data && sudo mount --bind /srv/nfs/data /srv/nfs4/data
# Persist: /etc/fstab — /srv/nfs/data /srv/nfs4/data none bind 0 0
```

### SELinux for NFS

```bash
sudo setsebool -P nfs_export_all_rw 1
sudo setsebool -P nfs_export_all_ro 1
sudo setsebool -P use_nfs_home_dirs 1       # if sharing home dirs
sudo semanage fcontext -a -t nfs_t "/srv/nfs(/.*)?"
sudo restorecon -Rv /srv/nfs
getsebool -a | grep nfs                     # verify
```

### Client (fstab and autofs)

```bash
sudo dnf install nfs-utils
# /etc/fstab
10.0.1.10:/data  /mnt/nfs/data  nfs4  defaults,_netdev,rsize=1048576,wsize=1048576  0  0

# Autofs on-demand mounting
sudo dnf install autofs
# /etc/auto.master.d/nfs.autofs:  /mnt/nfs  /etc/auto.nfs  --timeout=300
# /etc/auto.nfs:                  data  -rw,rsize=1048576,wsize=1048576  10.0.1.10:/data
sudo systemctl enable --now autofs
```

### Firewalld and Performance

```bash
# NFSv4 only needs TCP 2049
sudo firewall-cmd --permanent --add-service=nfs
sudo firewall-cmd --reload
# NFSv3 also needs: --add-service=rpc-bind --add-service=mountd

# Restrict to zone
sudo firewall-cmd --permanent --zone=internal --add-source=10.0.1.0/24
sudo firewall-cmd --permanent --zone=internal --add-service=nfs
sudo firewall-cmd --reload

# Tuning: /etc/nfs.conf [nfsd] threads = 16   (default 8; scale with cores)
# Stats: nfsstat -s (server) | nfsstat -c (client) | nfsiostat 5
```

---

## 2. Samba / CIFS

```bash
sudo dnf install samba samba-common samba-client
sudo systemctl enable --now smb nmb
```

### smb.conf (`/etc/samba/smb.conf`)

```ini
[global]
   workgroup = WORKGROUP
   server string = RHEL File Server
   security = user
   map to guest = Never
   passdb backend = tdbsam
   log file = /var/log/samba/log.%m
   max log size = 1000
   use sendfile = yes

[data]
   path = /srv/samba/data
   browseable = yes
   read only = no
   valid users = @smbgroup
   create mask = 0664
   directory mask = 0775
   force group = smbgroup

[projects]
   path = /srv/samba/projects
   read only = no
   valid users = @smbgroup
   vfs objects = acl_xattr
   map acl inherit = yes
   store dos attributes = yes
   inherit acls = yes
```

### Users and Directory Setup

```bash
sudo useradd -M -s /sbin/nologin smbuser1
sudo smbpasswd -a smbuser1              # set Samba password
sudo pdbedit -L -v                       # list users
sudo mkdir -p /srv/samba/{data,public,projects}
sudo groupadd smbgroup
sudo chgrp -R smbgroup /srv/samba/data /srv/samba/projects
sudo chmod 2775 /srv/samba/data /srv/samba/projects  # setgid
testparm && sudo systemctl reload smb
```

### SELinux for Samba

<HARD-RULE>
Samba shares on RHEL require correct SELinux contexts. Files with wrong labels are silently inaccessible even if Unix permissions are correct. Always set `samba_share_t` on custom share paths.
</HARD-RULE>

```bash
sudo semanage fcontext -a -t samba_share_t "/srv/samba(/.*)?"
sudo restorecon -Rv /srv/samba
sudo setsebool -P samba_enable_home_dirs on
sudo setsebool -P samba_share_nfs on         # if re-exporting NFS mounts
getsebool -a | grep samba                     # verify
ls -lZ /srv/samba/                            # confirm samba_share_t
```

### Firewalld, Client, and Windows

```bash
sudo firewall-cmd --permanent --add-service=samba && sudo firewall-cmd --reload

# Linux CIFS client
sudo dnf install cifs-utils
# /etc/fstab (credentials in /root/.smbcredentials, mode 600)
//10.0.1.10/data  /mnt/samba  cifs  credentials=/root/.smbcredentials,uid=1000,gid=1000,_netdev  0  0
# Windows: net use Z: \\10.0.1.10\data /user:smbuser1
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
sudo systemctl restart rsyslog smb
```

---

## 3. Stratis Storage Management

```bash
sudo dnf install stratisd stratis-cli
sudo systemctl enable --now stratisd
```

### Pool and Filesystem Operations

```bash
sudo stratis pool create mypool /dev/sdb
sudo stratis pool create bigpool /dev/sdc /dev/sdd    # multi-device
sudo stratis pool add-data mypool /dev/sde             # expand pool

# Create thin-provisioned XFS filesystems
sudo stratis filesystem create mypool appdata
sudo stratis filesystem create mypool backups

# Mount
sudo mkdir -p /mnt/appdata
sudo mount /dev/stratis/mypool/appdata /mnt/appdata

# fstab (must wait for stratisd)
UUID=<stratis-uuid>  /mnt/appdata  xfs  defaults,x-systemd.requires=stratisd.service  0  0

# Status
stratis pool list && stratis filesystem list && stratis blockdev list
```

### Snapshots

```bash
sudo stratis filesystem snapshot mypool appdata appdata-snap-$(date +%F)

# Mount snapshot (read-write COW clone)
sudo mount /dev/stratis/mypool/appdata-snap-2026-03-23 /mnt/snap

# Restore via rename
sudo umount /mnt/appdata
sudo stratis filesystem rename mypool appdata appdata-broken
sudo stratis filesystem rename mypool appdata-snap-2026-03-23 appdata
sudo mount /dev/stratis/mypool/appdata /mnt/appdata
sudo stratis filesystem destroy mypool appdata-broken   # cleanup
```

### Tiered Storage (Cache)

```bash
sudo stratis pool init-cache mypool /dev/nvme0n1       # add SSD/NVMe cache
sudo stratis pool add-cache mypool /dev/nvme1n1        # add more cache devices
stratis blockdev list mypool                            # Tier column: Data vs Cache
```

### Destruction (must unmount and destroy filesystems first)

```bash
sudo umount /mnt/appdata
sudo stratis filesystem destroy mypool appdata
sudo stratis pool destroy mypool
```

---

## 4. VDO / LVM-VDO (Deduplication & Compression)

In RHEL 9, VDO is integrated into LVM as `lvmvdo`. Standalone VDO is deprecated.

```bash
sudo dnf install lvm2 kmod-kvdo vdo

# Create VG and VDO logical volume
sudo pvcreate /dev/sdb && sudo vgcreate vdo-vg /dev/sdb
sudo lvcreate --type vdo --name vdo-lv --size 100G --virtualsize 300G vdo-vg

# Format and mount
sudo mkfs.xfs -K /dev/vdo-vg/vdo-lv     # -K skips discard (faster)
sudo mkdir -p /mnt/vdo && sudo mount /dev/vdo-vg/vdo-lv /mnt/vdo

# fstab
/dev/vdo-vg/vdo-lv  /mnt/vdo  xfs  defaults,x-systemd.requires=vdo.service,_netdev  0  0
```

### Statistics and Tuning

```bash
sudo vdostats --human-readable
sudo lvs -o+vdo_compression,vdo_deduplication,vdo_compression_state
sudo lvs -o name,size,data_percent,vdo_saving_percent vdo-vg

# Enable/disable per LV
sudo lvchange --compression y /dev/vdo-vg/vdo-lv
sudo lvchange --deduplication y /dev/vdo-vg/vdo-lv
```

### Growing VDO

```bash
sudo lvextend --size +50G /dev/vdo-vg/vpool0           # physical pool
sudo lvextend --virtualsize +100G /dev/vdo-vg/vdo-lv   # virtual size
sudo xfs_growfs /mnt/vdo                                # grow filesystem
```

---

## 5. XFS Administration

XFS is the default filesystem on RHEL 9. Supports online growth but NOT shrink.

<HARD-RULE>
XFS filesystems cannot be shrunk. To reduce size: back up data, recreate smaller, restore.
</HARD-RULE>

```bash
xfs_info /mnt/data                           # block size, log, AG details
sudo xfs_growfs /mnt/data                    # online growth (after lvextend)

# Repair (must unmount first)
sudo umount /mnt/data
sudo xfs_repair /dev/data-vg/data-lv
sudo xfs_repair -L /dev/data-vg/data-lv     # force log zeroing (last resort)

# Fragmentation
sudo xfs_db -c frag -r /dev/data-vg/data-lv # check
sudo xfs_fsr -v /mnt/data                    # defragment (online)

# Freeze/thaw for consistent snapshots
sudo xfs_freeze -f /mnt/data                # freeze
# ... take LVM snapshot or backup ...
sudo xfs_freeze -u /mnt/data                # unfreeze
```

### xfsdump / xfsrestore

```bash
sudo dnf install xfsdump
sudo xfsdump -l 0 -L "full-backup" -M "tape1" -f /backup/data-full.dump /mnt/data
sudo xfsdump -l 1 -L "incr-backup" -M "tape1" -f /backup/data-incr.dump /mnt/data
sudo xfsrestore -f /backup/data-full.dump /mnt/restore
sudo xfsrestore -i -f /backup/data-full.dump /mnt/restore   # interactive
xfsdump -I                                                    # dump inventory
```

---

## 6. Disk Quotas

### XFS Quotas (Preferred on RHEL)

```bash
# Enable in /etc/fstab mount options
UUID=xxxx  /data  xfs  defaults,usrquota,grpquota,prjquota  0  0
sudo mount -o remount /data

# User and group quotas
sudo xfs_quota -x -c "limit bsoft=400m bhard=500m username" /data
sudo xfs_quota -x -c "limit -g bsoft=2g bhard=2500m devteam" /data

# Project quota (directory-level)
# 1. /etc/projects:  10:/data/projectA
# 2. /etc/projid:    projectA:10
sudo xfs_quota -x -c "project -s projectA" /data
sudo xfs_quota -x -c "limit -p bsoft=5g bhard=6g projectA" /data

# Reports
sudo xfs_quota -x -c "report -ugh" /data    # all quotas
sudo xfs_quota -x -c "report -p" /data       # project quotas
sudo xfs_quota -x -c "free" /data            # free space
```

### ext4 Quotas

```bash
sudo dnf install quota
# /etc/fstab: UUID=xxxx /data ext4 defaults,usrquota,grpquota 0 2
sudo mount -o remount /data && sudo quotacheck -cugm /data && sudo quotaon /data
sudo setquota -u username 409600 512000 0 0 /data   # soft/hard blocks, inodes
sudo setquota -g devteam 2097152 2621440 0 0 /data
sudo repquota -a
```

---

## 7. POSIX ACLs

```bash
# XFS and ext4 have built-in ACL support on RHEL 9

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

Use `vfs objects = acl_xattr` with `map acl inherit = yes` and `store dos attributes = yes` in smb.conf (see `[projects]` in Section 2).

```bash
sudo setfacl -R -m g:smbgroup:rwx /srv/samba/projects
sudo setfacl -R -d -m g:smbgroup:rwx /srv/samba/projects
ls -lZ /srv/samba/projects                            # verify samba_share_t
```

### ACLs with NFS

POSIX ACLs work over NFS when server and client agree on UID/GID mapping. Set matching `Domain` in `/etc/idmapd.conf` on all hosts:

```bash
# [General]
# Domain = home.lab
sudo systemctl restart nfs-idmapd
```

---

## 8. Storage Monitoring

### Stratis and VDO Health

```bash
stratis pool list && stratis filesystem list && stratis blockdev list
stratis daemon version
sudo vdostats --human-readable
sudo lvs -o name,size,data_percent,vdo_saving_percent
```

### SMART Monitoring

```bash
sudo dnf install smartmontools
sudo systemctl enable --now smartd
sudo smartctl -H /dev/sda               # quick health
sudo smartctl -a /dev/sda               # full SMART data
sudo smartctl -t short /dev/sda         # self-test (~2 min)
sudo smartctl -l selftest /dev/sda      # view results
# /etc/smartmontools/smartd.conf:
# DEVICESCAN -a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -m admin@example.com
```

### Disk Space and I/O

```bash
df -h && df -i                           # filesystem + inode usage
du -sh /srv/data/* | sort -rh | head -20 # largest dirs
sudo dnf install ncdu && sudo ncdu /srv  # interactive browser
sudo dnf install sysstat
iostat -xz 5                             # per-device I/O (%util >80% = bottleneck)
sudo iotop -ao                           # per-process I/O
```

### Alert Scripts

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
# /usr/local/bin/stratis-health.sh — cron: */30 * * * * root /usr/local/bin/stratis-health.sh
MAILTO="admin@example.com"; HOST=$(hostname -f)
stratis pool list 2>/dev/null | tail -n+2 | while read name total used state alerts; do
  [ "$state" != "Ok" ] && echo "Stratis pool ${name} state: ${state}" \
    | mail -s "Stratis ALERT: ${HOST} pool ${name}" "$MAILTO"
done
```

```bash
sudo chmod +x /usr/local/bin/disk-alert.sh /usr/local/bin/stratis-health.sh
echo "*/15 * * * * root /usr/local/bin/disk-alert.sh" | sudo tee /etc/cron.d/disk-alert
echo "*/30 * * * * root /usr/local/bin/stratis-health.sh" | sudo tee /etc/cron.d/stratis-health
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
| Exporting NFS shares without restricting client IPs | Any machine on the network can mount the share; data exfiltration; unauthorized writes | Specify client IPs or subnets in /etc/exports; use `root_squash` (default) and `sec=krb5p` for authentication |
| Using Samba shares without SELinux context | SELinux blocks Samba access; admins disable SELinux instead of setting correct boolean/context | Set `samba_share_t` context on shared directories; enable `samba_enable_home_dirs` boolean if sharing homes |
| No disk quotas on shared storage | One user fills the volume; all users affected; no accountability for storage consumption | Enable XFS project quotas or ext4 quotas; set soft and hard limits per user/group; monitor with `repquota` |
| Stratis pool with single disk and no monitoring | Single disk failure loses entire pool; no warning before space exhaustion | Use Stratis with multiple disks for redundancy; monitor pool space with `stratis pool list`; alert at 80% usage |
| Not testing NFS failover or backup restore | Assume storage is always available; actual failure reveals untested recovery procedures take hours | Test NFS server failover quarterly; validate backup restore to alternate server; document recovery time |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core admin (LVM, firewall, SSH, systemd, SELinux) | `rhel-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Docker / Podman containers | `rhel-docker-host` |
| DNS, DHCP, NTP | `rhel-network-infra` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `rhel-ollama-nvidia` |
