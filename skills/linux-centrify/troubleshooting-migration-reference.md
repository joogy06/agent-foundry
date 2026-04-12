# Troubleshooting, Migration, OS Notes, and Quick Reference

Reference file for the `linux-centrify` skill. Covers troubleshooting, migration patterns, OS-specific notes, and essential commands quick reference.

## 12. Troubleshooting

### Quick Health Check

```bash
# 1. Is adclient running?
systemctl status centrifydc
sudo systemctl start centrifydc   # if stopped

# 2. Domain connection status
adinfo
# Look for: CentrifyDC mode: connected

# 3. Full diagnostic
adinfo --test
# Runs ~20 checks including DNS, Kerberos, LDAP, GC, time skew, zone lookup

# 4. Current DC and site
adinfo --server
adinfo --site
```

### adinfo --test Breakdown

`adinfo --test` performs these checks (each returns PASS/FAIL):

| Test | What It Checks |
|---|---|
| Domain join status | Machine is joined to a domain |
| DC connectivity | Can reach the current domain controller |
| LDAP connectivity | LDAP bind to DC succeeds |
| Global Catalog | GC is reachable |
| DNS | Forward/reverse DNS for host and DC |
| Time synchronization | Clock skew within Kerberos tolerance |
| Kerberos TGT | Machine has a valid TGT |
| Zone lookup | Machine's zone is found in AD |
| Site lookup | AD site is correctly identified |
| Group Policy | GPO download path is accessible |

### Enable Debug Logging

```bash
# Enable full debug (WARNING: very verbose, high disk I/O)
sudo addebug on

# Enable specific debug categories
sudo addebug on --category auth,ldap,krb5

# Debug output goes to:
tail -f /var/log/centrifydc.log

# Disable debug when done
sudo addebug off
```

### Common Issues and Fixes

#### DNS Resolution Failure

```bash
# Symptoms: adjoin fails, adinfo shows "disconnected"
# Fix: verify DNS
nslookup DOMAIN.EXAMPLE.COM
nslookup -type=SRV _ldap._tcp.DOMAIN.EXAMPLE.COM
nslookup $(hostname -f)

# Ensure /etc/resolv.conf points to AD-aware DNS
cat /etc/resolv.conf
# Should contain: nameserver <DC-IP-or-AD-DNS-IP>

# Ubuntu 24.04 — systemd-resolved
resolvectl status
sudo resolvectl dns eth0 10.0.0.1 10.0.0.2

# RHEL 9 — NetworkManager
nmcli dev show | grep DNS
sudo nmcli con mod eth0 ipv4.dns "10.0.0.1 10.0.0.2"
sudo nmcli con up eth0
```

#### Time Skew (Kerberos Errors)

```bash
# Symptoms: "Clock skew too great" in logs, Kerberos auth fails
# Fix: sync time
sudo chronyc makestep
chronyc tracking
timedatectl status

# If adclient.sntp.enabled is true, Centrify manages time itself
# For modern systems, disable Centrify SNTP and use chrony:
# In centrify.conf:
#   adclient.sntp.enabled: false
```

#### Disconnected Mode / Stale Cache

```bash
# Symptoms: adinfo shows "disconnected", users can't log in
adinfo
# Check: CentrifyDC mode: disconnected

# Step 1: Check network connectivity to DC
ping dc01.domain.example.com
nc -zv dc01.domain.example.com 389
nc -zv dc01.domain.example.com 88

# Step 2: Force reconnection
sudo adreload

# Step 3: If still disconnected, restart
sudo systemctl restart centrifydc

# Step 4: Flush cache if data is stale
sudo adflush
```

#### Expired Kerberos Tickets

```bash
# Symptoms: access denied, "Ticket expired" in logs
klist
# Check "Expires" column

# Renew tickets
kinit -R    # renew existing ticket
kinit       # get new ticket (requires password)

# For machine account (adclient manages this automatically)
sudo systemctl restart centrifydc
```

#### Zone Lookup Failure

```bash
# Symptoms: "Unable to find zone" during adjoin or in adinfo
# Cause: zone DN is wrong or machine is not a member of the zone

# Verify zone exists in AD
adquery zone --dn "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com"

# Check if this machine is in the zone
adinfo --zone

# Re-join to correct zone if needed
sudo adleave --force
sudo adjoin -w DOMAIN.EXAMPLE.COM --zone "cn=CorrectZone,cn=Zones,..."
```

#### adcdiag — Comprehensive Diagnostics

```bash
# Run full diagnostic suite
sudo adcdiag

# Test specific areas
sudo adcdiag --dns         # DNS resolution tests
sudo adcdiag --krb5        # Kerberos tests
sudo adcdiag --ldap        # LDAP connectivity tests
sudo adcdiag --zone        # Zone configuration tests

# Save diagnostic output for support
sudo adcdiag > /tmp/centrify-diag-$(date +%Y%m%d).txt 2>&1
```

### Log Files

```bash
# Primary Centrify log
/var/log/centrifydc.log

# Syslog/journal entries
journalctl -u centrifydc --since "1 hour ago"
journalctl -u centrifydc -f   # follow live

# PAM debug (if enabled)
/var/log/auth.log       # Ubuntu
/var/log/secure          # RHEL

# Kerberos ticket cache
klist -l
klist -e    # show encryption types
```

### Rejoining the Domain

```bash
# When all else fails — leave and rejoin
# Step 1: Back up config
sudo cp /etc/centrifydc/centrify.conf /etc/centrifydc/centrify.conf.bak.$(date +%Y%m%d%H%M%S)

# Step 2: Leave (try graceful first)
sudo adleave --user admin@DOMAIN.EXAMPLE.COM
# If that fails:
sudo adleave --force

# Step 3: Clean up stale Kerberos cache
sudo rm -f /tmp/krb5cc_*
sudo kdestroy -A

# Step 4: Rejoin
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --user admin@DOMAIN.EXAMPLE.COM --force

# Step 5: Verify
adinfo --test
```

---

## 13. Migration Patterns

### Migrating from SSSD to Centrify

```bash
# Phase 1: Audit current state
# Document existing SSSD config
cat /etc/sssd/sssd.conf
getent passwd | grep @    # list AD users currently resolved
id someaduser             # capture current UID/GID

# Phase 2: Install Centrify alongside SSSD (parallel run)
sudo apt install -y centrifydc   # Ubuntu
sudo dnf install -y centrifydc   # RHEL

# Do NOT join the domain yet — install only

# Phase 3: Preserve UIDs
# Option A: Use RFC 2307 / classic zone — UIDs stored in AD attributes
#           (already populated if SSSD used id_provider = ad with POSIX attributes)
# Option B: Configure auto-zone with matching algorithm
# Option C: Manually set UNIX profiles in the Centrify zone to match current UIDs

# Phase 4: Join domain with Centrify
# Stop SSSD first to avoid conflicts
sudo systemctl stop sssd
sudo systemctl disable sssd

# Remove SSSD from NSS/PAM
# Ubuntu: re-run pam-auth-update
# RHEL: authselect select centrifydc

# Join
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --user admin@DOMAIN.EXAMPLE.COM

# Phase 5: Verify
adinfo --test
getent passwd someaduser@domain.example.com
id someaduser@domain.example.com
# Confirm UID/GID matches the old values

# Phase 6: Clean up SSSD
sudo apt remove -y sssd sssd-tools   # Ubuntu
sudo dnf remove -y sssd sssd-tools   # RHEL
```

### Migrating from Winbind to Centrify

```bash
# Phase 1: Document Winbind state
wbinfo -u          # list users
wbinfo -g          # list groups
wbinfo -t          # test trust
cat /etc/samba/smb.conf | grep -E '(realm|workgroup|security|idmap)'
getent passwd | grep '\\'   # Winbind users

# Phase 2: Map Winbind UID ranges to Centrify zone profiles
# Winbind uses idmap ranges — note the range:
grep 'idmap config' /etc/samba/smb.conf
# Example: idmap config DOMAIN : range = 10000-999999

# Phase 3: Stop Winbind and switch
sudo systemctl stop winbind
sudo systemctl disable winbind

# Remove Winbind from NSS
# Edit /etc/nsswitch.conf: remove "winbind" entries

# Phase 4: Install and join with Centrify
sudo adjoin -w DOMAIN.EXAMPLE.COM \
  --zone "cn=LinuxServers,cn=Zones,ou=Centrify,dc=domain,dc=example,dc=com" \
  --user admin@DOMAIN.EXAMPLE.COM

# Phase 5: Verify UID consistency
id domainuser@domain.example.com
ls -ln /home/domainuser/   # check file ownership matches
```

### Migrating from Native LDAP (nslcd / nss-pam-ldapd)

```bash
# Phase 1: Document current LDAP config
cat /etc/nslcd.conf
cat /etc/nsswitch.conf
getent passwd | grep -v "^root\|^nobody"   # identify LDAP-sourced users

# Phase 2: Ensure AD has POSIX attributes (uidNumber, gidNumber)
# If users were in OpenLDAP, their POSIX attributes need to be in AD
# Use Centrify's classic zone or RFC 2307 mapping

# Phase 3: Stop nslcd, install Centrify
sudo systemctl stop nslcd
sudo systemctl disable nslcd
# Install and join as shown above

# Phase 4: Verify and fix file ownership if UIDs changed
sudo find /home -nouser -exec ls -ln {} \;   # find orphaned files
sudo find /home -nouser -exec chown newuid:newgid {} \;   # fix ownership
```

### Cutover Strategy (All Migrations)

1. **Inventory**: Document all AD users, their UIDs/GIDs, home directories, and file ownership
2. **Parallel install**: Install Centrify without joining; verify packages and prerequisites
3. **Staging zone**: Create a test zone; join a non-production machine first
4. **UID mapping**: Ensure UNIX profiles in the Centrify zone match existing UIDs (critical for NFS, file ownership)
5. **Cutover window**: Stop old auth service, join Centrify, verify with `adinfo --test` and `getent`
6. **Validation**: Test SSH login, `dzdo` elevation, NFS access, cron jobs, application service accounts
7. **Monitoring**: Watch `/var/log/centrifydc.log` and `journalctl -u centrifydc` for 48 hours post-migration

### Rollback Plan

```bash
# If Centrify join fails or causes issues:

# Step 1: Leave the domain
sudo adleave --force

# Step 2: Remove Centrify from PAM/NSS
# Ubuntu — re-run pam-auth-update and deselect Centrify
sudo pam-auth-update
# Manually edit /etc/nsswitch.conf — remove "centrifydc"

# RHEL — switch authselect back
sudo authselect select sssd   # or: sudo authselect select winbind
# Edit /etc/nsswitch.conf — remove "centrifydc"

# Step 3: Re-enable the old auth service
sudo systemctl enable --now sssd   # or winbind, nslcd

# Step 4: Verify old auth works
getent passwd someaduser
id someaduser
ssh someaduser@localhost
```

---

## OS-Specific Notes

### Ubuntu 24.04

- PAM is managed by `pam-auth-update`; Centrify registers a profile automatically on install
- systemd-resolved may cache DNS; flush with `resolvectl flush-caches`
- AppArmor may need profiles for `adclient` if custom confinement is in use
- Package format: `.deb` from Centrify/Delinea APT repository

### RHEL 9

- PAM is managed by `authselect`; Centrify provides an authselect profile:
  ```bash
  sudo authselect select centrifydc
  sudo authselect current   # verify
  ```
- SELinux: Centrify ships SELinux policies; verify they're loaded:
  ```bash
  sudo semodule -l | grep centrify
  # If missing, install from the Centrify package:
  sudo semodule -i /usr/share/centrifydc/selinux/centrifydc.pp
  ```
- Firewalld: ensure DC ports are open:
  ```bash
  sudo firewall-cmd --permanent --add-service=ldap
  sudo firewall-cmd --permanent --add-service=kerberos
  sudo firewall-cmd --permanent --add-port=3268/tcp
  sudo firewall-cmd --permanent --add-port=3269/tcp
  sudo firewall-cmd --permanent --add-port=464/tcp
  sudo firewall-cmd --reload
  ```
- Package format: `.rpm` from Centrify/Delinea YUM repository

---

## Quick Reference — Essential Commands

| Task | Command |
|---|---|
| Check domain status | `adinfo` |
| Full connectivity test | `adinfo --test` |
| Join domain | `sudo adjoin -w DOMAIN --zone "DN" --user admin@DOMAIN` |
| Leave domain | `sudo adleave --user admin@DOMAIN` |
| Force leave (local only) | `sudo adleave --force` |
| Query AD user | `adquery user username@domain` |
| Query AD group | `adquery group groupname@domain` |
| Current user identity | `adid` |
| Privilege elevation | `dzdo <command>` |
| List my dzdo rights | `dzdo -l` |
| Refresh Group Policy | `sudo adgpupdate` |
| Enable debug logging | `sudo addebug on` |
| Disable debug logging | `sudo addebug off` |
| Flush identity cache | `sudo adflush` |
| Run diagnostics | `sudo adcdiag` |
| Restart agent | `sudo systemctl restart centrifydc` |
| View agent logs | `tail -f /var/log/centrifydc.log` |
| View running config | `adinfo --config` |

---

## Related Skills

| Skill | Relationship |
|---|---|
| `ubuntu-server-admin` | Base OS administration for Ubuntu 24.04 — prerequisites (DNS, NTP, networking, PAM, NSS) |
| `rhel-server-admin` | Base OS administration for RHEL 9 — prerequisites (DNS, NTP, firewalld, SELinux, authselect) |
| `docker-admin` | Running Centrify in containers — agent-per-container vs host-level join, identity propagation |
| `windows-sso` | AD FS, Entra ID, SAML/OAuth SSO — the Windows side of the same AD infrastructure |
