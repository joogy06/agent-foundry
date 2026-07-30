---
name: rhel-server-admin
description: Use when administering Red Hat Enterprise Linux 9 systems — dnf/rpm package management, subscription-manager, user/group management, SSH hardening, systemd services, firewalld, NetworkManager/nmcli networking, LVM/Stratis storage, kernel tuning, security hardening (CIS, SELinux, fail2ban), Cockpit web console, backup/restore, and on-prem VM guest tools (Proxmox, VMware, Hyper-V). Parent skill for the rhel-* skill family.
family: rhel
applies_when: os_family == rhel
---

# Red Hat Enterprise Linux 9 — Core Administration

Parent skill covering system fundamentals for RHEL 9.x (and compatible: AlmaLinux 9, Rocky Linux 9, Oracle Linux 9). For specialized workloads, see companion skills: `rhel-web-servers`, `rhel-databases`, `rhel-docker-host`, `rhel-file-storage`, `rhel-network-infra`, `rhel-monitoring`, `rhel-ollama-nvidia`.

<HARD-RULE>
Always verify the RHEL version before applying advice. Commands, paths, and available packages differ between major releases.
```bash
cat /etc/redhat-release
cat /etc/os-release
uname -r
```
</HARD-RULE>

<HARD-RULE>
Never run destructive commands (rm -rf, dd, mkfs, lvremove, wipefs) without explicit user confirmation. Always double-check device paths with `lsblk` and `blkid` first.
</HARD-RULE>

---

## Subscription and Registration

### RHEL Subscription Manager

```bash
# Register system
sudo subscription-manager register --username <user> --password <pass>
sudo subscription-manager attach --auto

# Check status
sudo subscription-manager status
sudo subscription-manager list --consumed
sudo subscription-manager identity

# Enable specific repos
sudo subscription-manager repos --enable rhel-9-for-x86_64-appstream-rpms
sudo subscription-manager repos --enable rhel-9-for-x86_64-baseos-rpms
sudo subscription-manager repos --enable codeready-builder-for-rhel-9-x86_64-rpms
sudo subscription-manager repos --list-enabled

# Unregister
sudo subscription-manager unregister
```

### AlmaLinux / Rocky Linux (No Subscription Needed)

```bash
# Repos are pre-configured — just verify
dnf repolist
dnf repolist --all        # include disabled repos
```

### EPEL (Extra Packages for Enterprise Linux)

```bash
# Install EPEL
sudo dnf install epel-release          # AlmaLinux/Rocky
# For RHEL:
sudo dnf install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm

# Verify
dnf repolist | grep epel
```

---

## Package Management (DNF / RPM)

### DNF Essentials

```bash
# Update all packages
sudo dnf update -y
sudo dnf upgrade -y                    # same as update in DNF

# Install / remove
sudo dnf install <pkg>
sudo dnf remove <pkg>
sudo dnf autoremove                    # clean unused dependencies

# Search and info
dnf search <keyword>
dnf info <pkg>
dnf list installed | grep <pkg>
dnf provides /usr/bin/<binary>         # find which package owns a file
dnf group list                         # available package groups
sudo dnf group install "Development Tools"

# History and rollback
dnf history
dnf history info <id>
sudo dnf history undo <id>            # undo a transaction

# Clean cache
sudo dnf clean all
sudo dnf makecache
```

### RPM Direct Operations

```bash
rpm -qa | grep <pkg>                   # list installed
rpm -qi <pkg>                          # info about installed package
rpm -ql <pkg>                          # list files in package
rpm -qf /path/to/file                  # which package owns this file
rpm -ivh package.rpm                   # install local RPM
rpm -Uvh package.rpm                   # upgrade local RPM
rpm --import https://example.com/RPM-GPG-KEY  # import GPG key
```

### Module Streams (AppStream)

```bash
# List available modules
dnf module list
dnf module list php

# Enable a specific stream
sudo dnf module enable php:8.2
sudo dnf module install php:8.2/common

# Switch streams
sudo dnf module reset php
sudo dnf module enable php:8.3

# Check active stream
dnf module list --enabled
```

### Automatic Updates (DNF Automatic)

```bash
sudo dnf install dnf-automatic
```

Edit `/etc/dnf/automatic.conf`:
```ini
[commands]
upgrade_type = security        # security | default (all)
apply_updates = yes
download_updates = yes

[emitters]
emit_via = email,stdio

[email]
email_from = root@server.example.com
email_to = admin@example.com
email_host = localhost
```

```bash
sudo systemctl enable --now dnf-automatic-install.timer
systemctl list-timers | grep dnf
```

---

## User and Group Management

### User Operations

```bash
# Create user with home directory
sudo useradd -m -s /bin/bash <username>
sudo passwd <username>

# Create system user (no home, no login)
sudo useradd -r -s /sbin/nologin <svcname>

# Modify user
sudo usermod -aG <group> <username>     # add to supplementary group
sudo usermod -L <username>              # lock account
sudo usermod -U <username>              # unlock account
sudo usermod -e 2026-12-31 <username>   # set expiry
sudo chage -l <username>                # check password aging

# Delete user
sudo userdel <username>
sudo userdel -r <username>              # remove home too

# Check user info
id <username>
getent passwd <username>
last <username>
lastlog
```

### Sudoers

```bash
# Edit sudoers safely
sudo visudo

# Per-user drop-in (preferred)
sudo visudo -f /etc/sudoers.d/<username>
```

Drop-in example `/etc/sudoers.d/deploy`:
```
deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart myapp, /usr/bin/journalctl -u myapp
```

### Password Policy

```bash
# /etc/security/pwquality.conf
minlen = 12
minclass = 3
maxrepeat = 3
dcredit = -1
ucredit = -1
lcredit = -1
ocredit = -1

# Password aging defaults — /etc/login.defs
PASS_MAX_DAYS 90
PASS_MIN_DAYS 7
PASS_WARN_AGE 14
```

---

## SSH Hardening

Config: `/etc/ssh/sshd_config.d/hardened.conf` (drop-in preferred)

```bash
Port 22
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
MaxAuthTries 3
MaxSessions 3
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowTcpForwarding no
PermitEmptyPasswords no
UsePAM yes

AllowUsers deploy admin
```

```bash
# Apply changes
sudo systemctl reload sshd

# Test BEFORE disconnecting (use a second terminal!)
ssh -T user@host

# Key management
ssh-keygen -t ed25519 -C "admin@server"
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host

# SELinux: if using non-standard SSH port
sudo semanage port -a -t ssh_port_t -p tcp 2222
```

---

## Systemd Service Management

### Essential Commands

```bash
sudo systemctl start|stop|restart|reload <service>
sudo systemctl enable <service>
sudo systemctl enable --now <service>
sudo systemctl disable <service>
sudo systemctl mask <service>
sudo systemctl unmask <service>

# Status and inspection
systemctl status <service>
systemctl is-active <service>
systemctl is-enabled <service>
systemctl list-units --type=service --state=running
systemctl list-units --failed
systemctl cat <service>
systemctl show <service>

sudo systemctl daemon-reload
```

### Custom Service Unit

Create `/etc/systemd/system/myapp.service`:

```ini
[Unit]
Description=My Application
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=myapp
Group=myapp
WorkingDirectory=/opt/myapp
ExecStart=/opt/myapp/bin/server --config /etc/myapp/config.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/myapp /var/log/myapp
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes

# Resource limits
MemoryMax=1G
CPUQuota=200%
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Systemd Timers

```ini
# /etc/systemd/system/backup.timer
[Unit]
Description=Daily backup timer

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

```bash
systemctl list-timers --all
```

### Journald / Logging

```bash
journalctl -u <service>
journalctl -u <service> -f
journalctl -u <service> --since "1h ago"
journalctl -u <service> -p err
journalctl -b
journalctl -b -1
journalctl --disk-usage

# Persist logs across reboots
sudo mkdir -p /var/log/journal

# /etc/systemd/journald.conf
SystemMaxUse=500M
MaxRetentionSec=30day

# Vacuum
sudo journalctl --vacuum-size=200M
sudo journalctl --vacuum-time=7d
```

---

## Firewall (firewalld)

```bash
# Status
sudo firewall-cmd --state
sudo firewall-cmd --list-all
sudo firewall-cmd --list-all-zones

# Add services (permanent + reload)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload

# Add port
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --permanent --add-port=5432/tcp

# Rich rules (source-restricted access)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/24" port port="5432" protocol="tcp" accept'

# Rate limiting SSH
sudo firewall-cmd --permanent --add-rich-rule='rule service name="ssh" accept limit value="10/m"'

# Zone management
sudo firewall-cmd --get-default-zone
sudo firewall-cmd --set-default-zone=public
sudo firewall-cmd --zone=internal --add-source=10.0.0.0/24 --permanent
sudo firewall-cmd --zone=internal --add-service=nfs --permanent

# Remove rules
sudo firewall-cmd --permanent --remove-service=http
sudo firewall-cmd --reload

# List available services
sudo firewall-cmd --get-services
```

---

## Networking (NetworkManager / nmcli)

### Static IP

```bash
# List connections
nmcli connection show
nmcli device status

# Set static IP
sudo nmcli connection modify "ens18" \
  ipv4.addresses 10.0.1.50/24 \
  ipv4.gateway 10.0.1.1 \
  ipv4.dns "10.0.1.1 1.1.1.1" \
  ipv4.dns-search "home.lab" \
  ipv4.method manual

sudo nmcli connection up "ens18"
```

### VLAN

```bash
sudo nmcli connection add type vlan \
  con-name vlan100 \
  ifname ens18.100 \
  dev ens18 \
  id 100 \
  ipv4.addresses 10.0.100.10/24 \
  ipv4.method manual

sudo nmcli connection up vlan100
```

### Bond (Active-Backup)

```bash
# Create bond
sudo nmcli connection add type bond \
  con-name bond0 \
  ifname bond0 \
  bond.options "mode=active-backup,primary=ens18,miimon=100"

# Add slaves
sudo nmcli connection add type ethernet slave-type bond \
  con-name bond0-port1 ifname ens18 master bond0
sudo nmcli connection add type ethernet slave-type bond \
  con-name bond0-port2 ifname ens19 master bond0

# Set IP on bond
sudo nmcli connection modify bond0 \
  ipv4.addresses 10.0.1.50/24 \
  ipv4.gateway 10.0.1.1 \
  ipv4.method manual

sudo nmcli connection up bond0
```

### Bridge (for VMs/Containers)

```bash
sudo nmcli connection add type bridge \
  con-name br0 ifname br0 \
  ipv4.addresses 10.0.1.50/24 \
  ipv4.gateway 10.0.1.1 \
  ipv4.method manual

sudo nmcli connection add type ethernet slave-type bridge \
  con-name br0-port ifname ens18 master br0

sudo nmcli connection up br0
```

### Troubleshooting

```bash
nmcli general status
nmcli device show ens18
ip addr show
ip route show
resolvectl status                      # or cat /etc/resolv.conf
ss -tlnp                               # listening TCP ports
ss -ulnp                               # listening UDP ports
```

---

## Disk and Storage (LVM)

### LVM Workflow

```bash
# Physical volumes
sudo pvcreate /dev/sdb
sudo pvs
sudo pvdisplay /dev/sdb

# Volume groups
sudo vgcreate data-vg /dev/sdb
sudo vgs
sudo vgextend data-vg /dev/sdc

# Logical volumes
sudo lvcreate -L 50G -n app-lv data-vg
sudo lvcreate -l 100%FREE -n data-lv data-vg
sudo lvs

# Format and mount
sudo mkfs.xfs /dev/data-vg/app-lv      # XFS is default on RHEL
sudo mkdir -p /mnt/app
sudo mount /dev/data-vg/app-lv /mnt/app
```

### Extend a Logical Volume (Online)

```bash
sudo lvextend -L +20G /dev/data-vg/app-lv
sudo xfs_growfs /mnt/app                # XFS (cannot shrink)
sudo resize2fs /dev/data-vg/app-lv      # ext4

# Or both in one command
sudo lvextend -L +20G --resizefs /dev/data-vg/app-lv
```

### Stratis (Modern Storage Management)

```bash
sudo dnf install stratisd stratis-cli
sudo systemctl enable --now stratisd

# Create pool
sudo stratis pool create mypool /dev/sdb

# Create filesystem
sudo stratis filesystem create mypool appdata

# Mount (use UUID from lsblk)
sudo mount /dev/stratis/mypool/appdata /mnt/app

# Snapshots
sudo stratis filesystem snapshot mypool appdata appdata-snap

# Status
stratis pool list
stratis filesystem list
stratis blockdev list
```

### fstab

```bash
# Get UUID
sudo blkid /dev/data-vg/app-lv

# /etc/fstab — XFS default
UUID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx /mnt/app xfs defaults,noatime 0 0

# Stratis filesystem in fstab (must use x-systemd options)
UUID=<stratis-uuid> /mnt/app xfs defaults,x-systemd.requires=stratisd.service 0 0

# Test
sudo mount -a
```

### Disk Health

```bash
sudo dnf install smartmontools
sudo smartctl -a /dev/sda
sudo smartctl -t short /dev/sda
```

---

## Kernel Tuning (sysctl)

Create `/etc/sysctl.d/99-server-tuning.conf`:

```ini
# Network performance
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65536
net.ipv4.tcp_max_syn_backlog = 65536
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# Connection tracking
net.netfilter.nf_conntrack_max = 262144

# Memory
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.overcommit_memory = 0

# File descriptors
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288

# Security
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
```

```bash
sudo sysctl --system
sysctl net.ipv4.tcp_tw_reuse
```

### File Descriptor Limits

`/etc/security/limits.d/99-nofile.conf`:
```
* soft nofile 65536
* hard nofile 65536
root soft nofile 65536
root hard nofile 65536
```

---

## Security Hardening

### SELinux

<HARD-RULE>
Never disable SELinux on production systems. Use permissive mode for troubleshooting, then return to enforcing. If an application doesn't work with SELinux, fix the policy — don't disable SELinux.
</HARD-RULE>

```bash
# Status
getenforce                              # Enforcing | Permissive | Disabled
sestatus                                # detailed status

# Temporarily set permissive (survives until reboot)
sudo setenforce 0                       # permissive
sudo setenforce 1                       # enforcing

# Permanent config — /etc/selinux/config
SELINUX=enforcing                       # enforcing | permissive | disabled
SELINUXTYPE=targeted

# Troubleshooting
sudo dnf install setroubleshoot-server
sudo ausearch -m AVC --start recent     # recent denials
sudo sealert -a /var/log/audit/audit.log

# Common fixes
sudo setsebool -P httpd_can_network_connect 1
sudo setsebool -P httpd_can_network_connect_db 1
sudo semanage port -a -t http_port_t -p tcp 8080
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/www(/.*)?"
sudo restorecon -Rv /srv/www

# List booleans
getsebool -a | grep httpd
```

### Fail2Ban

```bash
sudo dnf install epel-release
sudo dnf install fail2ban
sudo systemctl enable --now fail2ban
```

Create `/etc/fail2ban/jail.local`:
```ini
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = firewallcmd-rich-rules

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/secure
maxretry = 3
```

```bash
sudo fail2ban-client status
sudo fail2ban-client status sshd
sudo fail2ban-client set sshd unbanip <ip>
```

### CIS Benchmark Quick Wins

```bash
# Disable unused filesystems
echo "install cramfs /bin/true" | sudo tee /etc/modprobe.d/cramfs.conf
echo "install freevxfs /bin/true" | sudo tee /etc/modprobe.d/freevxfs.conf
echo "install hfs /bin/true" | sudo tee /etc/modprobe.d/hfs.conf
echo "install hfsplus /bin/true" | sudo tee /etc/modprobe.d/hfsplus.conf

# Restrict core dumps
echo "* hard core 0" | sudo tee -a /etc/security/limits.d/99-core.conf
echo "fs.suid_dumpable = 0" | sudo tee /etc/sysctl.d/99-core.conf

# Login banner
echo "Authorized access only. All activity is monitored." | sudo tee /etc/issue /etc/issue.net

# Cron permissions
sudo chmod 600 /etc/crontab
sudo chmod 700 /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.monthly /etc/cron.weekly
```

### AIDE (File Integrity Monitoring)

```bash
sudo dnf install aide
sudo aide --init
sudo mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz
sudo aide --check
```

### OpenSCAP Security Scanning

```bash
sudo dnf install openscap-scanner scap-security-guide
# List available profiles
oscap info /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml

# Run CIS benchmark scan
sudo oscap xccdf eval \
  --profile xccdf_org.ssgproject.content_profile_cis \
  --results /tmp/scan-results.xml \
  --report /tmp/scan-report.html \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
```

---

## Cockpit Web Console

```bash
sudo dnf install cockpit
sudo systemctl enable --now cockpit.socket
sudo firewall-cmd --permanent --add-service=cockpit
sudo firewall-cmd --reload

# Access at https://<server-ip>:9090
# Login with any system user that has sudo

# Optional modules
sudo dnf install cockpit-storaged       # storage management
sudo dnf install cockpit-networkmanager # network config
sudo dnf install cockpit-podman         # container management
sudo dnf install cockpit-machines       # VM management (libvirt)
```

---

## Backup and Restore

### rsync

```bash
sudo rsync -avz --delete /data/ /backup/data/
sudo rsync -avz -e "ssh -i /root/.ssh/backup_key" /data/ backup@remote:/backup/server1/data/
sudo rsync -avz --exclude='*.tmp' --exclude='.cache' /data/ /backup/data/
```

### LVM Snapshots

```bash
sudo lvcreate -s -L 10G -n app-snap /dev/data-vg/app-lv
sudo mount -o ro /dev/data-vg/app-snap /mnt/snap
# ... backup ...
sudo umount /mnt/snap
sudo lvremove /dev/data-vg/app-snap
```

### Stratis Snapshots

```bash
sudo stratis filesystem snapshot mypool appdata appdata-backup
# Mount and backup from snapshot
```

### ReaR (Relax-and-Recover)

```bash
sudo dnf install rear
# /etc/rear/local.conf
OUTPUT=ISO
BACKUP=NETFS
BACKUP_URL=nfs://backup-server/rear

sudo rear mkbackup
sudo rear recover     # boot from ISO to restore
```

---

## On-Prem VM Guest Tools

### Proxmox (QEMU Guest Agent)

```bash
sudo dnf install qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
```

### VMware (open-vm-tools)

```bash
sudo dnf install open-vm-tools
sudo systemctl enable --now vmtoolsd
```

### Hyper-V

Hyper-V Integration Services are built into the RHEL 9 kernel:
```bash
lsmod | grep hv_
sudo systemctl enable --now hypervkvpd
```

---

## System Information and Troubleshooting

```bash
hostnamectl
timedatectl
uptime
free -h
df -h
lsblk

lscpu
lspci
lsusb
dmidecode -t system

top / htop
ps auxf
iotop
nethogs

systemd-analyze
systemd-analyze blame
dmesg | tail -50
```

---

## Hostname and Timezone

```bash
sudo hostnamectl set-hostname server01.home.lab
sudo timedatectl set-timezone America/New_York
timedatectl list-timezones | grep <keyword>

# NTP (chronyd is default on RHEL 9)
timedatectl status
chronyc tracking
chronyc sources -v
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Disabling SELinux instead of fixing policy denials | Removes mandatory access control; fails security audits; one compromised service can access everything | Set SELinux to permissive temporarily to diagnose; fix denials with `audit2allow` or custom policies; keep enforcing |
| Using `chmod 777` to fix permission issues | World-writable files are a security vulnerability; any process can modify, delete, or inject content | Diagnose the actual permission need; set minimal permissions (640/750); use ACLs for granular multi-user access |
| Not registering RHEL with subscription-manager | No security updates; dnf repos disabled; system drifts from patched state; compliance violations | Register immediately after install; attach appropriate subscription; enable automatic security updates |
| Editing config files without taking backups | One typo in sshd_config or fstab can lock you out or prevent boot; no easy rollback | Copy originals before editing (`cp file file.bak.$(date +%Y%m%d)`); use `etckeeper` for version control of /etc |
| Running services as root when unnecessary | Compromised service gives attacker full system access; violates principle of least privilege | Create dedicated service accounts; use systemd `User=`/`Group=` directives; drop capabilities with `CapabilityBoundingSet` |

---

## Related Skills

| Workload | Skill |
|---|---|
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Docker / Podman containers | `rhel-docker-host` |
| File sharing (NFS, Samba, Stratis) | `rhel-file-storage` |
| DNS, DHCP, NTP | `rhel-network-infra` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `rhel-ollama-nvidia` |
