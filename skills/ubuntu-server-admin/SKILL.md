---
name: ubuntu-server-admin
description: Use when administering Ubuntu Server 24.04 LTS systems — package management, user/group management, SSH hardening, systemd services, UFW/nftables firewall, netplan networking, LVM/disk management, kernel tuning, security hardening (CIS, AppArmor, fail2ban), backup/restore, and on-prem VM guest tools (Proxmox, VMware, Hyper-V). Parent skill for the ubuntu-* skill family.
---

# Ubuntu Server 24.04 LTS — Core Administration

Parent skill covering system fundamentals for Ubuntu Server 24.04.4 LTS (Noble Numbat). For specialized workloads, see companion skills: `ubuntu-web-servers`, `ubuntu-databases`, `ubuntu-docker-host`, `ubuntu-file-storage`, `ubuntu-network-infra`, `ubuntu-monitoring`, `ubuntu-ollama-nvidia`.

<HARD-RULE>
Always verify the Ubuntu version before applying advice. Commands and paths differ between releases.
```bash
lsb_release -a   # or cat /etc/os-release
uname -r          # kernel version
```
</HARD-RULE>

<HARD-RULE>
Never run destructive commands (rm -rf, dd, mkfs, lvremove, wipefs) without explicit user confirmation and a clear understanding of the target. Always double-check device paths.
</HARD-RULE>

---

## Package Management

### APT Essentials

```bash
# Update package index and upgrade
sudo apt update && sudo apt upgrade -y

# Full upgrade (handles dependency changes — use for kernel/HWE updates)
sudo apt full-upgrade -y

# Install / remove
sudo apt install <pkg>
sudo apt remove <pkg>          # keeps config files
sudo apt purge <pkg>           # removes config files too
sudo apt autoremove -y         # clean unused dependencies

# Search and info
apt search <keyword>
apt show <pkg>
apt list --installed | grep <pkg>
dpkg -l | grep <pkg>           # lower-level query
dpkg -L <pkg>                  # list files owned by package

# Pin a package to prevent upgrades
sudo apt-mark hold <pkg>
sudo apt-mark unhold <pkg>
apt-mark showhold
```

### Repository Management

```bash
# Add a PPA (use sparingly on servers)
sudo add-apt-repository ppa:<owner>/<name>

# Add third-party repo (modern signed approach — 24.04 standard)
curl -fsSL https://example.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/example.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/example.gpg] https://repo.example.com noble main" \
  | sudo tee /etc/apt/sources.list.d/example.list

# List configured repos
grep -r ^deb /etc/apt/sources.list.d/

# Remove a repo
sudo rm /etc/apt/sources.list.d/example.list
sudo rm /usr/share/keyrings/example.gpg
```

### Unattended Upgrades (Security Autopatch)

```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

Key config: `/etc/apt/apt.conf.d/50unattended-upgrades`
```
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
};
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
Unattended-Upgrade::Mail "admin@example.com";
Unattended-Upgrade::MailReport "on-change";
```

### Snap Packages

```bash
snap list                       # installed snaps
snap find <keyword>
sudo snap install <pkg>
sudo snap refresh <pkg>         # update
sudo snap remove <pkg>
snap connections <pkg>          # check interfaces/permissions
```

### HWE (Hardware Enablement) Kernel

```bash
# Install the latest HWE kernel for 24.04
sudo apt install linux-generic-hwe-24.04

# Check current and available kernels
dpkg -l | grep linux-image
uname -r
```

---

## User and Group Management

### User Operations

```bash
# Create user with home directory and bash shell
sudo useradd -m -s /bin/bash <username>
sudo passwd <username>

# Or use the interactive version
sudo adduser <username>

# Create system user (no home, no login)
sudo useradd -r -s /usr/sbin/nologin <svcname>

# Modify user
sudo usermod -aG <group> <username>     # add to supplementary group
sudo usermod -L <username>              # lock account
sudo usermod -U <username>              # unlock account
sudo usermod -e 2026-12-31 <username>   # set expiry

# Delete user
sudo userdel <username>                 # keep home
sudo userdel -r <username>              # remove home too

# Check user info
id <username>
getent passwd <username>
last <username>                         # login history
```

### Sudoers

```bash
# Edit sudoers safely (ALWAYS use visudo)
sudo visudo

# Per-user drop-in (preferred over editing main file)
sudo visudo -f /etc/sudoers.d/<username>
```

Drop-in example `/etc/sudoers.d/deploy`:
```
deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart myapp, /usr/bin/journalctl -u myapp
```

### Password Policy

```bash
# Install and configure password quality
sudo apt install libpam-pwquality

# Edit /etc/security/pwquality.conf
minlen = 12
minclass = 3
maxrepeat = 3
```

---

## SSH Hardening

Config: `/etc/ssh/sshd_config.d/hardened.conf` (drop-in preferred over editing main file)

```bash
# Hardened SSH config
Port 22                          # change if desired, update UFW too
PermitRootLogin no
PasswordAuthentication no        # key-only after deploying keys
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

# Restrict to specific users/groups
AllowUsers deploy admin
# Or: AllowGroups ssh-users
```

```bash
# Apply changes
sudo systemctl reload sshd

# Test BEFORE disconnecting (use a second terminal!)
ssh -T user@host

# Key management
ssh-keygen -t ed25519 -C "admin@server"
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host
```

### SSH Key-Only Enforcement Checklist

1. Deploy public keys to `~/.ssh/authorized_keys` (mode `600`, `.ssh` dir mode `700`)
2. Test login with key in a **separate terminal**
3. Set `PasswordAuthentication no` in sshd config
4. Reload sshd
5. Verify password login is rejected

---

## Systemd Service Management

### Essential Commands

```bash
# Service lifecycle
sudo systemctl start|stop|restart|reload <service>
sudo systemctl enable <service>          # start on boot
sudo systemctl enable --now <service>    # enable + start immediately
sudo systemctl disable <service>
sudo systemctl mask <service>            # prevent any start
sudo systemctl unmask <service>

# Status and inspection
systemctl status <service>
systemctl is-active <service>
systemctl is-enabled <service>
systemctl list-units --type=service --state=running
systemctl list-units --failed
systemctl cat <service>                  # show unit file
systemctl show <service>                 # all properties

# Reload systemd after editing unit files
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

### Systemd Timers (Cron Replacement)

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
# List active timers
systemctl list-timers --all
```

### Journald / Logging

```bash
# View logs
journalctl -u <service>                 # specific service
journalctl -u <service> -f              # follow (tail)
journalctl -u <service> --since "1h ago"
journalctl -u <service> -p err          # errors only
journalctl -b                           # current boot
journalctl -b -1                        # previous boot
journalctl --disk-usage                  # check log size

# Persist logs across reboots (default in 24.04)
sudo mkdir -p /var/log/journal

# Limit journal size — /etc/systemd/journald.conf
SystemMaxUse=500M
MaxRetentionSec=30day

# Vacuum old logs
sudo journalctl --vacuum-size=200M
sudo journalctl --vacuum-time=7d
```

---

## Firewall (UFW / nftables)

### UFW (Frontend to nftables)

```bash
# Enable/disable
sudo ufw enable
sudo ufw disable
sudo ufw status verbose
sudo ufw status numbered

# Basic rules
sudo ufw allow ssh                       # 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow from 10.0.0.0/24 to any port 5432   # PostgreSQL from LAN
sudo ufw allow from 192.168.1.0/24                  # entire subnet

# Rate limiting (brute-force protection)
sudo ufw limit ssh/tcp

# Delete rules
sudo ufw status numbered
sudo ufw delete <number>

# Default policy
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Application profiles
sudo ufw app list
sudo ufw allow 'Nginx Full'

# Logging
sudo ufw logging on
sudo ufw logging medium     # low|medium|high|full
```

### Direct nftables (Advanced)

Config: `/etc/nftables.conf`
```bash
sudo systemctl enable nftables
sudo nft list ruleset
```

---

## Networking (Netplan)

Config directory: `/etc/netplan/`

### Static IP

```yaml
# /etc/netplan/01-static.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens18:
      addresses:
        - 10.0.1.50/24
      routes:
        - to: default
          via: 10.0.1.1
      nameservers:
        addresses:
          - 10.0.1.1
          - 1.1.1.1
        search:
          - home.lab
```

### VLAN

```yaml
# /etc/netplan/02-vlans.yaml
network:
  version: 2
  vlans:
    vlan100:
      id: 100
      link: ens18
      addresses:
        - 10.0.100.10/24
```

### Bond (Active-Backup)

```yaml
# /etc/netplan/03-bond.yaml
network:
  version: 2
  bonds:
    bond0:
      interfaces:
        - ens18
        - ens19
      parameters:
        mode: active-backup
        primary: ens18
        mii-monitor-interval: 100
      addresses:
        - 10.0.1.50/24
      routes:
        - to: default
          via: 10.0.1.1
```

### Bridge (for VMs/Containers)

```yaml
# /etc/netplan/04-bridge.yaml
network:
  version: 2
  bridges:
    br0:
      interfaces:
        - ens18
      addresses:
        - 10.0.1.50/24
      routes:
        - to: default
          via: 10.0.1.1
      parameters:
        stp: false
```

### Apply and Debug

```bash
sudo netplan try                # apply with 120s auto-rollback
sudo netplan apply              # apply permanently
sudo netplan get                # show current config
ip addr show                    # verify addresses
ip route show                   # verify routes
resolvectl status               # DNS resolution status
```

---

## Disk and Storage (LVM)

### LVM Workflow

```bash
# Physical volumes
sudo pvcreate /dev/sdb
sudo pvs                        # list PVs
sudo pvdisplay /dev/sdb

# Volume groups
sudo vgcreate data-vg /dev/sdb
sudo vgs
sudo vgextend data-vg /dev/sdc  # add disk to VG

# Logical volumes
sudo lvcreate -L 50G -n app-lv data-vg
sudo lvcreate -l 100%FREE -n data-lv data-vg   # use all remaining space
sudo lvs
sudo lvdisplay

# Format and mount
sudo mkfs.ext4 /dev/data-vg/app-lv
sudo mkdir -p /mnt/app
sudo mount /dev/data-vg/app-lv /mnt/app
```

### Extend a Logical Volume (Online)

```bash
# Extend LV by 20G
sudo lvextend -L +20G /dev/data-vg/app-lv

# Resize filesystem (online for ext4 and xfs)
sudo resize2fs /dev/data-vg/app-lv       # ext4
sudo xfs_growfs /mnt/app                  # xfs

# Or do both in one command
sudo lvextend -L +20G --resizefs /dev/data-vg/app-lv
```

### fstab

```bash
# Get UUID
sudo blkid /dev/data-vg/app-lv

# /etc/fstab entry (use UUID, not device path)
UUID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx /mnt/app ext4 defaults,noatime 0 2

# Test fstab without rebooting
sudo mount -a
```

### Disk Health

```bash
sudo apt install smartmontools
sudo smartctl -a /dev/sda          # SMART data
sudo smartctl -t short /dev/sda    # run self-test
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

# Connection tracking (important for firewalls / NAT)
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
# Apply
sudo sysctl --system

# Verify a value
sysctl net.ipv4.tcp_tw_reuse
```

### Gotcha: strict overcommit (`vm.overcommit_memory = 2`) breaks V8/Bun/Node runtimes

DB and trading-host tunings often set `vm.overcommit_memory = 2` to keep the OOM killer away from critical services. That setting silently breaks modern V8-based tools — Node.js, Bun, **Claude Code**, VS Code Server, Electron apps, Playwright/Puppeteer — which reserve large chunks of virtual address space up front via `mmap(PROT_NONE)`. Typical symptom: startup or installer fails with a cryptic **"Out of memory"** even though `free -h` shows gigabytes available, cgroups are unlimited, ulimits are fine, and disk has plenty of room. The process's own `--force` flag can't help — the mmap itself is failing at the syscall level before any preflight logic runs.

**Why it happens:** under mode `2` the kernel refuses any allocation that would push *committed* memory past `CommitLimit = swap + RAM * overcommit_ratio/100`, even for reservations that will never be touched. Default `overcommit_ratio = 50`, so on an 8 GB / 4 GB-swap box the commit limit is only ~7.9 GB — tight for a Bun/V8 binary that wants to reserve 10+ GB of virtual address space.

**Diagnose:**
```bash
sysctl vm.overcommit_memory vm.overcommit_ratio
grep -rs 'overcommit_memory' /etc/sysctl.conf /etc/sysctl.d/ /usr/lib/sysctl.d/ /run/sysctl.d/
cat /proc/meminfo | grep -E 'CommitLimit|Committed_AS'

# Confirm the cause by temporarily relaxing (reverts on reboot):
sudo sysctl -w vm.overcommit_memory=0
# retry the failing command; if it works, the diagnosis is confirmed
```

**Fix options, in order of preference on a hardened host:**

1. **Keep `overcommit_memory = 2`, raise `overcommit_ratio`** — preserves OOM-killer protection for critical services. Edit the *existing* tuning file (don't create a fighting drop-in):
   ```bash
   sudo sed -i 's/^vm\.overcommit_ratio.*/vm.overcommit_ratio = 100/' /etc/sysctl.d/99-<existing>.conf
   sudo sysctl --system
   ```
   Commit-limit math on an 8 GB / 4 GB-swap host: `ratio=100` → ~11.7 GB (usually enough), `ratio=200` → ~19.4 GB (comfortable margin). Bump to 200 if Bun/V8 still errors at 100.

2. **Switch protection model** — leave `overcommit_memory = 0` (kernel default) and protect critical services via systemd `MemoryMin=` / `MemoryLow=` or `oom_score_adj = -1000`. More modern than strict overcommit and doesn't break V8-based tooling.

3. **Absolute commit limit** — instead of a ratio, set `vm.overcommit_kbytes` to a fixed byte count. Useful when RAM/swap changes would otherwise shift the ratio-derived limit.

**Drop-in conflict warning:** files in `/etc/sysctl.d/` load **alphabetically**, so two files setting the same key (e.g. `99-claude-code.conf` and `99-trading-db.conf`) both apply — the later-sorted one wins. Don't paper over an intentional hardening setting with a fighting drop-in; edit the source file instead, or you'll get inconsistent state at next reboot.

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

### AppArmor

```bash
# Status
sudo aa-status

# Modes: enforce, complain, disable
sudo aa-enforce /etc/apparmor.d/<profile>
sudo aa-complain /etc/apparmor.d/<profile>

# Reload profiles
sudo systemctl reload apparmor
```

### Fail2Ban

```bash
sudo apt install fail2ban
sudo systemctl enable --now fail2ban
```

Create `/etc/fail2ban/jail.local`:
```ini
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = ufw

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
```

```bash
# Management
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

# Set login banner (remove OS info)
echo "Authorized access only. All activity is monitored." | sudo tee /etc/issue /etc/issue.net

# Audit who can access cron
sudo chmod 600 /etc/crontab
sudo chmod 700 /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.monthly /etc/cron.weekly
```

### Automatic Security Scanning

```bash
# Lynis — system auditing
sudo apt install lynis
sudo lynis audit system

# Check listening ports
sudo ss -tlnp
sudo ss -ulnp
```

---

## Backup and Restore

### rsync

```bash
# Local backup
sudo rsync -avz --delete /data/ /backup/data/

# Remote backup over SSH
sudo rsync -avz -e "ssh -i /root/.ssh/backup_key" /data/ backup@remote:/backup/server1/data/

# Exclude patterns
sudo rsync -avz --exclude='*.tmp' --exclude='.cache' /data/ /backup/data/
```

### Timeshift (System Snapshots)

```bash
sudo apt install timeshift
sudo timeshift --create --comments "Before upgrade"
sudo timeshift --list
sudo timeshift --restore
```

### LVM Snapshots

```bash
# Create snapshot (requires free space in VG)
sudo lvcreate -s -L 10G -n app-snap /dev/data-vg/app-lv

# Mount snapshot read-only for backup
sudo mount -o ro /dev/data-vg/app-snap /mnt/snap
# ... run backup ...
sudo umount /mnt/snap

# Remove snapshot
sudo lvremove /dev/data-vg/app-snap
```

---

## On-Prem VM Guest Tools

### Proxmox (QEMU Guest Agent)

```bash
sudo apt install qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent

# Verify from Proxmox host: qm agent <vmid> ping
```

### VMware (open-vm-tools)

```bash
sudo apt install open-vm-tools
sudo systemctl enable --now open-vm-tools

# For VMs with GUI
sudo apt install open-vm-tools-desktop
```

### Hyper-V

Linux Integration Services are built into the 24.04 kernel. Verify:
```bash
lsmod | grep hv_
# Should show: hv_vmbus, hv_storvsc, hv_netvsc, hv_utils, hv_balloon
```

Key-value pair daemon for host-guest communication:
```bash
sudo systemctl enable --now hv-kvp-daemon
```

---

## System Information and Troubleshooting

```bash
# System overview
hostnamectl
timedatectl
uptime
free -h
df -h
lsblk

# Hardware
lscpu
lspci
lsusb
dmidecode -t system     # VM or physical, vendor info
cat /proc/meminfo

# Process and resource usage
top / htop
ps auxf                 # process tree
iotop                   # disk I/O by process
nethogs                 # network by process

# Boot diagnostics
systemd-analyze          # boot time
systemd-analyze blame    # slowest units
dmesg | tail -50         # kernel messages
```

---

## Hostname and Timezone

```bash
# Set hostname
sudo hostnamectl set-hostname server01.home.lab

# Set timezone
sudo timedatectl set-timezone America/New_York
timedatectl list-timezones | grep <keyword>

# NTP sync (default: systemd-timesyncd)
timedatectl status
# Custom NTP servers: /etc/systemd/timesyncd.conf
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `apt install` without `apt update` first | Installs outdated or unavailable package versions; dependency resolution fails; security patches missed | Always run `apt update` before `apt install`; automate with `unattended-upgrades` for security patches |
| Disabling AppArmor instead of fixing profile denials | Removes mandatory access control; one compromised service can access entire filesystem | Set profile to complain mode (`aa-complain`); fix denials; return to enforce mode; write custom profiles if needed |
| Editing netplan YAML with tabs instead of spaces | YAML parsing fails silently or produces wrong config; network configuration breaks on next apply | Use spaces only (2-space indent); validate with `netplan try` (auto-reverts after timeout if you lose connectivity) |
| Running all services as root | Compromised service has full system access; violates principle of least privilege; fails security audits | Create dedicated service users; use systemd `User=`/`DynamicUser=`; drop capabilities with `CapabilityBoundingSet` |
| Not configuring UFW after installation | Default Ubuntu allows all outbound and no inbound; but many admins assume it is enabled when it is not | Enable UFW (`ufw enable`); allow only required inbound ports; set default deny incoming; log blocked traffic |
| Setting `vm.overcommit_memory = 2` without raising `overcommit_ratio` | Default `ratio = 50` caps committed memory at `swap + RAM * 0.5` — too small for V8/Bun/Node virtual-address reservations. Installs and startups fail with cryptic "Out of memory" despite free RAM, healthy cgroups, and wide-open ulimits. Breaks Claude Code, VS Code Server, Electron, Playwright, etc. | Keep strict overcommit but raise `overcommit_ratio` to 100+ so V8 reservations fit under the commit limit; or protect critical services via systemd `MemoryMin=` / `oom_score_adj` and leave `overcommit_memory = 0`. Never create a fighting drop-in in `/etc/sysctl.d/` — edit the source tuning file |

---

## Related Skills

| Workload | Skill |
|---|---|
| Web servers (Nginx, Apache, Caddy) | `ubuntu-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `ubuntu-databases` |
| Docker / containers | `ubuntu-docker-host` |
| File sharing (NFS, Samba, ZFS) | `ubuntu-file-storage` |
| DNS, DHCP, NTP | `ubuntu-network-infra` |
| Prometheus, Grafana, logging | `ubuntu-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `ubuntu-ollama-nvidia` |
