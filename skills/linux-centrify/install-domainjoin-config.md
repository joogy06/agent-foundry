# Overview, Installation, Domain Join, and Configuration

Reference file for the `linux-centrify` skill. Covers architecture overview, installation, domain join, and centrify.conf configuration.

## 1. Overview and Architecture

### Product Components

| Component | Purpose |
|---|---|
| **DirectControl** | AD domain join, identity mapping (PAM/NSS), Kerberos authentication, Group Policy |
| **DirectAuthorize** | Zone-based access control, privilege elevation (`dzdo`/`dzsh`), command rights, role assignments |
| **DirectAudit** | Session recording, keystroke logging, video playback of privileged sessions |

### Agent Components on Linux

| Binary | Function |
|---|---|
| `adclient` | Core daemon — maintains AD connection, Kerberos tickets, caches identity data |
| `adinfo` | Query agent status — domain, site, joined DC, connection state |
| `adquery` | Look up AD users/groups and their UNIX attributes |
| `adjoin` | Join the machine to an AD domain and zone |
| `adleave` | Cleanly leave the AD domain |
| `adgpupdate` | Force Group Policy refresh |
| `addebug` | Enable/disable debug logging |
| `adflush` | Flush cached identity data |
| `adcdiag` | Run connectivity and configuration diagnostics |
| `dzdo` | Centrify privilege elevation (replaces sudo) |
| `dzsh` | Restricted shell for audited/limited sessions |
| `adid` | Display the current user's AD identity and UNIX profile |

### How Centrify Integrates with PAM/NSS

Centrify installs its own PAM and NSS modules:
- **PAM**: `/lib/security/pam_centrifydc.so` handles authentication, account, session, and password stacks
- **NSS**: `libnss_centrifydc.so` provides `passwd`, `group`, and `shadow` resolution from AD
- The `adclient` daemon runs as root, maintains a Kerberos TGT for the machine account, and serves identity lookups from its local cache

### Zone Model

Zones are AD objects (stored in `CN=Zones` under a configurable container) that define:
- Which machines belong to the zone
- Which AD users/groups can log in
- UNIX profiles (UID, GID, home directory, shell) for those users
- Roles and rights (command rights, PAM access, privilege elevation rules)

Zone types:
- **Hierarchical zones** — child zones inherit from parent; recommended for most deployments
- **Classic zones (RFC 2307)** — UID/GID stored directly in AD user attributes; legacy approach
- **Auto-zone** — auto-generates UNIX profiles from AD attributes using an algorithmic UID/GID mapping

---

## 2. Installation

### Prerequisites

```bash
# 1. DNS — machine must resolve the AD domain and DCs
nslookup DOMAIN.EXAMPLE.COM
dig +short _ldap._tcp.dc._msdcs.DOMAIN.EXAMPLE.COM SRV

# 2. NTP — Kerberos requires time within 5 minutes of DC
timedatectl set-ntp true
timedatectl status

# 3. Network — ports to domain controllers
#    TCP 88   (Kerberos)
#    TCP 389  (LDAP)
#    TCP 636  (LDAPS)
#    TCP 445  (SMB/CIFS — for Group Policy)
#    TCP 464  (Kerberos password change)
#    TCP 3268 (Global Catalog)
#    TCP 3269 (Global Catalog over SSL)

# 4. Hostname — FQDN should be set correctly
hostnamectl set-hostname myserver.domain.example.com
hostname -f   # verify FQDN
```

### Ubuntu 24.04 Installation

```bash
# Add Delinea / Centrify repository (adjust URL per your license/download portal)
sudo tee /etc/apt/sources.list.d/centrify.list <<'EOF'
deb [trusted=yes] https://repo.centrify.com/deb stable main
EOF

# Import the GPG key
curl -fsSL https://repo.centrify.com/RPM-GPG-KEY-centrify | sudo gpg --dearmor -o /etc/apt/keyrings/centrify.gpg

# Install the agent
sudo apt update
sudo apt install -y centrifydc

# Optional: DirectAuthorize components
sudo apt install -y centrifydc-ldapproxy centrifydc-nis

# Verify installation
adinfo --version
dpkg -l | grep centrify
```

### RHEL 9 Installation

```bash
# Add Centrify repository
sudo tee /etc/yum.repos.d/centrify.repo <<'EOF'
[centrify]
name=Centrify Repository
baseurl=https://repo.centrify.com/rpm/centos/9/x86_64/
enabled=1
gpgcheck=1
gpgkey=https://repo.centrify.com/RPM-GPG-KEY-centrify
EOF

# Install the agent
sudo dnf install -y centrifydc

# Optional: DirectAuthorize and NIS gateway
sudo dnf install -y centrifydc-ldapproxy centrifydc-nis

# Verify
adinfo --version
rpm -qa | grep centrify
```

### Using the Interactive Installer Script

Centrify provides `centrifydc-install.sh` in the download bundle for offline or customized installs:

```bash
# Extract the bundle
tar xzf centrify-suite-2024-el9-x86_64.tgz
cd centrify-suite-2024-el9-x86_64/

# Run interactive installer
sudo ./install.sh

# Or non-interactive with options
sudo ./install.sh \
  --express \
  --domain DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --container "ou=Servers,ou=Centrify,dc=domain,dc=example,dc=com" \
  --user joinadmin@DOMAIN.EXAMPLE.COM
```

---

## 3. Domain Join

### Basic Join

```bash
# Join with interactive password prompt
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --user joinadmin@DOMAIN.EXAMPLE.COM

# Join and place computer in a specific OU
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --container "ou=LinuxServers,ou=Computers,dc=domain,dc=example,dc=com" \
  --user joinadmin@DOMAIN.EXAMPLE.COM

# Join with one-time password (for automated deployments)
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --otp "MyOneTimePassword123"
```

### Adjoin Options Reference

| Option | Purpose |
|---|---|
| `-w` / `--workstation` | Domain to join (can omit flag, just pass domain name) |
| `--zone` | DN of the zone to join |
| `--container` | OU for the computer account |
| `--user` | AD account to authenticate the join |
| `--otp` | One-time password (pre-staged in AD) |
| `--name` | Override the computer name in AD |
| `--force` | Force join even if a stale object exists |
| `--selfserve` | Use Centrify self-service join (no admin creds needed) |
| `-S` / `--server` | Specify a DC to join against |
| `--verbose` | Verbose output during join |

### Pre-Creating Computer Objects

For environments where the Linux admin lacks AD write access, pre-create the computer object using Centrify tools on Windows (Access Manager) or PowerShell:

```powershell
# PowerShell (on Windows with RSAT / Centrify cmdlets)
New-ADComputer -Name "LINUXSRV01" -Path "OU=LinuxServers,OU=Computers,DC=domain,DC=example,DC=com"
# Then set a one-time password for the Centrify join
Set-CdcComputerOneTimePassword -Computer "LINUXSRV01" -Password "TempPass123!"
```

Then on the Linux host:

```bash
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --name LINUXSRV01 \
  --otp "TempPass123!"
```

### Verify Domain Join

```bash
# Quick status
adinfo

# Expected output includes:
#   Joined to domain: DOMAIN.EXAMPLE.COM
#   Joined as:        LINUXSRV01$@DOMAIN.EXAMPLE.COM
#   Current DC:       dc01.domain.example.com
#   Preferred site:   Default-First-Site-Name
#   Zone:             cn=LinuxServers,cn=Zones,...
#   CentrifyDC mode:  connected

# Full connectivity test
adinfo --test

# Verify Kerberos ticket
klist -l
klist    # show machine TGT

# Verify DNS registration (if dynamic DNS update was enabled)
nslookup $(hostname -f)
host $(hostname -f)
```

### Leaving the Domain

```bash
# Graceful leave — removes computer account from AD
sudo adleave --user adminuser@DOMAIN.EXAMPLE.COM

# Force leave — local cleanup only, does NOT remove AD object
sudo adleave --force
```

---

## 4. centrify.conf Configuration

The primary configuration file is `/etc/centrifydc/centrify.conf`. Key parameters:

### Authentication and Access Control

```ini
# Allow specific users (comma-separated) — overrides zone roles for local policy
pam.allow.users: user1@domain.example.com, user2@domain.example.com

# Allow specific groups
pam.allow.groups: linux_admins@domain.example.com, app_team@domain.example.com

# Deny specific users/groups (evaluated before allow)
pam.deny.users: contractor1@domain.example.com
pam.deny.groups: terminated_employees@domain.example.com

# Allow local users to log in even if AD is unreachable
pam.allow.local.users: true
```

### Identity Mapping

```ini
# Home directory template (auto-create)
auto.schema.homedir: /home/%{user}
# Other tokens: %{domain}, %{userid}, %{samaccountname}

# Default shell for AD users without a UNIX profile
auto.schema.shell: /bin/bash

# Override primary GID for all AD users (useful for shared group)
nss.override.gid: 10000

# UID/GID range for auto-zone mapping
auto.schema.uid.min: 1000000
auto.schema.uid.max: 2000000
auto.schema.gid.min: 1000000
auto.schema.gid.max: 2000000
```

### Cache and Performance

```ini
# Cache mode: connected, disconnected, preferred
adclient.cache.mode: connected

# Disconnected mode — allow cached logins if DC is unreachable
adclient.cache.mode.disconnect: true

# Cache lifetime for user/group lookups (seconds)
adclient.cache.user.lifetime: 3600
adclient.cache.group.lifetime: 3600

# Maximum cache entries
adclient.cache.user.max: 50000
adclient.cache.group.max: 50000
```

### Kerberos Settings

```ini
# Ticket lifetime
adclient.krb5.tkt.lifetime: 10h

# Renewable lifetime
adclient.krb5.tkt.renew.lifetime: 7d

# Force AES encryption (disable RC4)
adclient.krb5.permitted.encryption.types: aes256-cts-hmac-sha1-96 aes128-cts-hmac-sha1-96
```

### Network and LDAP

```ini
# LDAP signing
adclient.ldap.signing: required

# LDAP channel binding
adclient.ldap.channel.binding: true

# Umask for LDAP connections
adclient.ldap.umask: 022

# SNTP — let adclient sync time (disable if chrony/ntpd manages time)
adclient.sntp.enabled: false

# Preferred DC site
adclient.site: MySiteName

# DC failover behavior (seconds before retry)
adclient.server.retry.interval: 60
```

### Reconnection Behavior

```ini
# How often to check for DC connectivity when disconnected (seconds)
adclient.reconnect.interval: 60

# Maximum time to stay in disconnected mode before denying logins (0 = unlimited)
adclient.cache.mode.disconnect.maxtime: 0
```

### Applying Configuration Changes

```bash
# Restart adclient to pick up centrify.conf changes
sudo systemctl restart centrifydc

# Or reload (less disruptive, but not all params support reload)
sudo adreload

# Verify the running config
adinfo --config
```

---

## 5. Zone-Based Access Control

### Zone Concepts

Zones are the central authorization model in Centrify. Each zone defines:
- **Machine roles**: groups of computers in the zone
- **UNIX profiles**: UID, GID, shell, home for each AD user/group
- **Role assignments**: who can access machines and with what privileges
- **Command rights**: specific commands users can run with elevated privileges

### Viewing Zone Information

```bash
# Show the zone this machine belongs to
adinfo --zone

# Query the zone DN
adinfo | grep Zone

# List users with UNIX profiles in the current zone
adquery user --zone
```

### Role Assignments

Roles are defined in the Centrify Access Manager (Windows console) or via the `dzdo` policy infrastructure. Key built-in roles:

| Role | Access Level |
|---|---|
| `login` | Can log in (SSH, console) — no privilege elevation |
| `sysadmin` | Full root access via `dzdo` |
| `linux_admin` | Custom role with specific command rights |

Roles are assigned to AD users or groups and scoped to:
- The entire zone
- A specific computer role (subset of machines)
- An individual machine

### PAM Access Module

Centrify's PAM module (`pam_centrifydc.so`) checks zone-based roles at login time. If a user has no role assignment granting login to the machine, PAM denies the session.

```bash
# Verify a user's zone access
adquery user -A sshuser@domain.example.com
# Look for "allowed" in the output

# Check effective roles for current user
dzdo -l
```

---

## 6. Privilege Elevation (dzdo / dzsh)

### dzdo vs sudo

`dzdo` is Centrify's drop-in replacement for sudo. Key differences:
- Rights are defined in AD (not /etc/sudoers)
- Centralized management across all zone machines
- Auditable — integrates with DirectAudit session recording
- Supports time-limited elevation and approval workflows

```bash
# Run a command as root via dzdo
dzdo systemctl restart httpd

# Run as a specific user
dzdo -u postgres psql

# Open a root shell
dzdo -i
dzdo su -

# List available rights for current user
dzdo -l
```

### Command Rights

Command rights are defined in the Centrify Access Manager and specify:
- **Command pattern**: path and arguments (supports wildcards)
- **Run-as user**: which user the command runs as (usually root)
- **Authentication**: whether the user must re-enter their password
- **Environment**: allowed/denied environment variables

Example command right definitions (managed in Access Manager):

| Right Name | Pattern | Run As | Auth Required |
|---|---|---|---|
| Restart Apache | `/usr/bin/systemctl restart httpd` | root | Yes |
| View Logs | `/usr/bin/less /var/log/*` | root | No |
| Full Shell | `*` | root | Yes |

### Restricted Shell (dzsh)

`dzsh` provides an audited, restricted shell for users who need limited root access:

```bash
# Assign dzsh as a user's login shell in their zone UNIX profile
# (done in Access Manager or via admod)

# When the user logs in, they get dzsh instead of bash
# dzsh enforces command rights — only permitted commands execute
# All commands are logged for audit
```

### Time-Limited Elevation

Centrify supports time-boxed privilege elevation where a role assignment is valid only for a specific window. This is configured in Access Manager under role assignment properties (start time, end time, and optionally requires approval).

---

