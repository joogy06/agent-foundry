# Zone Access, Privilege Elevation, PAM/NSS, Group Policy, Multi-Forest, and User Management

Reference file for the `linux-centrify` skill. Covers zone-based access control, privilege elevation (dzdo/dzsh), PAM/NSS integration, Group Policy for Linux, multi-forest/trust, and user/group management.

## 7. PAM / NSS Integration

### PAM Module Order

Centrify modifies PAM configuration during installation. The key files:

```bash
# Ubuntu 24.04 — /etc/pam.d/common-auth
# Centrify inserts its module early in the stack
auth    sufficient    pam_centrifydc.so
auth    requisite     pam_deny.so
auth    required      pam_unix.so try_first_pass

# RHEL 9 — /etc/pam.d/system-auth (managed by authselect)
# Centrify adds its module; verify with:
grep centrify /etc/pam.d/system-auth
grep centrify /etc/pam.d/password-auth
```

PAM stacks modified by Centrify:

| Stack | Module | Purpose |
|---|---|---|
| auth | `pam_centrifydc.so` | Authenticate against AD (Kerberos) |
| account | `pam_centrifydc.so` | Check zone access / role assignment |
| password | `pam_centrifydc.so` | AD password changes |
| session | `pam_centrifydc.so` | Home directory creation, ticket management |

### NSS Configuration

Centrify adds itself to `/etc/nsswitch.conf`:

```bash
# /etc/nsswitch.conf — after Centrify installation
passwd:     files centrifydc
shadow:     files centrifydc
group:      files centrifydc
```

Verify NSS is resolving AD users:

```bash
# Look up an AD user
getent passwd aduser@domain.example.com

# Look up an AD group
getent group linuxadmins@domain.example.com

# List all resolvable users (may be large)
getent passwd

# If getent returns nothing for AD users, check:
#   1. adclient is running: systemctl status centrifydc
#   2. NSS is configured: grep centrifydc /etc/nsswitch.conf
#   3. User has a UNIX profile in the zone
```

### Smart Card / Certificate Authentication

```bash
# Enable smart card auth in centrify.conf
pam.cert.enabled: true
pam.cert.auth.required: false   # true = cert required, false = cert optional

# PKCS#11 module path (depends on smart card middleware)
pam.cert.pkcs11.module: /usr/lib/x86_64-linux-gnu/opensc-pkcs11.so
```

### MFA Integration

Centrify supports offline and online MFA through its cloud-based Centrify Identity Platform:

```bash
# Enable MFA in centrify.conf
pam.mfa.enabled: true
pam.mfa.program: /usr/share/centrifydc/bin/centrify_mfa

# Offline MFA — cache MFA tokens for use when DC is unreachable
pam.mfa.offline.enabled: true
pam.mfa.offline.lifetime: 72h
```

---

## 8. Group Policy for Linux

### Forcing a Policy Refresh

```bash
# Refresh all Group Policy settings
sudo adgpupdate

# Force full refresh (ignore cached policy)
sudo adgpupdate --force

# Verbose refresh with details
sudo adgpupdate --verbose
```

### Policy Categories

Centrify maps Windows Group Policy concepts to Linux:

| Windows GPO Category | Linux Application |
|---|---|
| Security settings | PAM config, password policy, login restrictions |
| Centrify settings | centrify.conf parameters pushed via GPO |
| Login/logout scripts | Scripts executed at session start/end |
| Certificate auto-enrollment | Machine/user certificates from AD CS |
| Sudo/dzdo rights | Privilege elevation rules |
| Custom configuration | Arbitrary file/registry-like settings |

### Login and Logout Scripts

GPO can push login/logout scripts to Linux machines:

```bash
# Scripts are stored in SYSVOL and downloaded to:
/var/centrifydc/scripts/login/
/var/centrifydc/scripts/logout/

# Verify scripts are being applied
ls -la /var/centrifydc/scripts/login/
ls -la /var/centrifydc/scripts/logout/

# Scripts run with the user's credentials at session start/end
# Check /var/log/centrifydc.log for script execution output
```

### Custom GPO Settings

Centrify supports custom Group Policy Administrative Templates (ADMX) that map to Linux configuration files. These are managed in the Windows Group Policy Management Console (GPMC) and pushed to Linux agents via `adgpupdate`.

```bash
# View applied policies
adgpresult

# Check which GPOs are linked to this machine
adinfo --gpo
```

---

## 9. Multi-Forest and Trust

### Cross-Forest Authentication

Centrify supports multi-forest environments where:
- The Linux machine is joined to Forest A
- Users from Forest B need to authenticate (via forest trust)

Requirements:
- A forest trust must exist between Forest A and Forest B
- DNS conditional forwarders or stub zones for cross-forest name resolution
- Centrify must be configured to search the trusted forest

### Configuration for Multi-Forest

```ini
# /etc/centrifydc/centrify.conf

# Enable multi-forest support
adclient.trust.forest.enabled: true

# Specify additional forests to search (if not auto-discovered via trusts)
adclient.trust.forest.list: FORESTB.EXAMPLE.COM, FORESTC.EXAMPLE.COM

# Global Catalog server for trusted forest (optional — auto-discovered by default)
adclient.trust.forest.gc.FORESTB.EXAMPLE.COM: gc01.forestb.example.com

# Allow users from trusted forests
pam.allow.foreign.users: true
```

### Trust Types

| Trust Type | Centrify Behavior |
|---|---|
| Two-way forest trust | Full cross-forest auth; users from either forest can log in if zone permits |
| One-way trust (Forest A trusts B) | Users from Forest B can authenticate to machines in Forest A |
| Selective authentication trust | Only explicitly permitted users from the trusted forest can authenticate; Centrify respects AD's "Allowed to Authenticate" permission |
| External (domain-level) trust | Supported but forest trust is recommended |

### Troubleshooting Multi-Forest

```bash
# Verify trust is visible to Centrify
adinfo --trusts

# Test cross-forest user resolution
adquery user foreignuser@forestb.example.com

# Check DNS resolution for the trusted forest
nslookup _ldap._tcp.dc._msdcs.FORESTB.EXAMPLE.COM

# Verify GC connectivity
adinfo --gc

# Check Kerberos cross-realm referral
klist   # look for cross-realm TGT (krbtgt/FORESTB.EXAMPLE.COM@FORESTA.EXAMPLE.COM)
```

---

## 10. User and Group Management

### adquery — Looking Up AD Users and Groups

```bash
# Query a specific user
adquery user john.smith@domain.example.com
adquery user john.smith   # short form if unambiguous

# Query a specific user — verbose (all attributes)
adquery user -A john.smith@domain.example.com

# Query by UID
adquery user --uid 1500042

# List all users in the current zone
adquery user -z

# Query a group
adquery group linux_admins@domain.example.com

# Query group membership
adquery group -m linux_admins@domain.example.com

# Query by GID
adquery group --gid 1500010
```

### adid — Current User Identity

```bash
# Show the current user's AD identity and UNIX profile
adid

# Output includes:
#   AD user:        john.smith@DOMAIN.EXAMPLE.COM
#   UNIX UID:       1500042
#   UNIX GID:       1500010
#   Home:           /home/john.smith
#   Shell:          /bin/bash
#   Zone:           cn=LinuxServers,...
```

### UID/GID Mapping Strategies

| Strategy | How UIDs Are Assigned | When to Use |
|---|---|---|
| **Hierarchical zone** | UIDs defined per user in zone UNIX profile (stored in AD zone objects) | Most deployments; consistent UIDs across zone |
| **Auto-zone** | Algorithmic mapping from AD objectSID to UID | Large environments; no manual UID management |
| **Classic zone (RFC 2307)** | UID/GID stored in AD user's `uidNumber`/`gidNumber` attributes | Migration from LDAP/SSSD; preserves existing UIDs |

### Resolving UID/GID Conflicts

```bash
# Check for UID conflicts across zones
adquery user --uid 15042   # see who owns this UID

# Use getent to see what the system resolves
getent passwd 15042
getent group 15010

# If conflicts exist between local and AD users:
# Option 1: Adjust the local user's UID
sudo usermod -u 99042 localuser

# Option 2: Configure UID range separation in centrify.conf
# Ensure auto.schema.uid.min is above your local UID range
```

### Flushing User/Group Cache

```bash
# Flush all cached identity data (forces re-fetch from AD)
sudo adflush

# Flush a specific user
sudo adflush -u john.smith@domain.example.com

# Flush groups
sudo adflush -g

# After flushing, verify resolution
getent passwd john.smith@domain.example.com
```

---

## 11. Certificate Auto-Enrollment

Centrify supports automatic certificate enrollment from Active Directory Certificate Services (AD CS), bringing Windows-like auto-enrollment to Linux.

### How It Works

1. AD CS certificate templates are configured to allow enrollment by computers/users
2. Group Policy pushes auto-enrollment settings to the Centrify agent
3. `adclient` requests certificates from the CA on behalf of the machine or user
4. Certificates are stored locally and renewed automatically before expiry

### Configuration

```ini
# /etc/centrifydc/centrify.conf

# Enable certificate auto-enrollment
adclient.cert.autoenroll.enabled: true

# Certificate storage location
adclient.cert.store: /etc/centrifydc/certs

# Renewal threshold (days before expiry to renew)
adclient.cert.autoenroll.renew.days: 30
```

### Managing Certificates

```bash
# Force certificate enrollment now
sudo adgpupdate --force

# List enrolled certificates
ls -la /etc/centrifydc/certs/

# View certificate details
openssl x509 -in /etc/centrifydc/certs/machine.pem -text -noout

# Check certificate expiry
openssl x509 -in /etc/centrifydc/certs/machine.pem -enddate -noout

# Certificates can be used for:
#   - Apache/Nginx TLS
#   - LDAPS client authentication
#   - 802.1X network authentication
#   - Smart card login (user certificates)
```

### Template Requirements in AD CS

For machine certificates:
- Template must permit "Domain Computers" or specific group to enroll
- Key usage: Digital Signature, Key Encipherment
- EKU: Server Authentication (1.3.6.1.5.5.7.3.1)

For user certificates:
- Template must permit the user or their group to enroll
- EKU: Client Authentication (1.3.6.1.5.5.7.3.2), Smart Card Logon (1.3.6.1.4.1.311.20.2.2)

---

