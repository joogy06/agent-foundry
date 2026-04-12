---
name: linux-centrify
description: Use when configuring Centrify (Delinea Server Suite) on Linux — Active Directory domain join, adclient/adinfo/adquery commands, zone-based access control, PAM/NSS integration, Centrify DirectAuthorize (dzdo/dzsh), role-based privilege elevation, group policy for Linux, centrify.conf tuning, certificate auto-enrollment, multi-forest trust, offline MFA, troubleshooting domain connectivity, and migration from legacy authentication. Works with Ubuntu 24.04 and RHEL 9.
---

# Centrify / Delinea Server Suite — Linux Administration

Comprehensive guide for deploying and managing Centrify (now Delinea Server Suite) on Linux systems joined to Active Directory. Covers DirectControl (AD join and identity), DirectAuthorize (privilege elevation), and DirectAudit (session recording). For base OS administration, see companion skills: `ubuntu-server-admin`, `rhel-server-admin`.

<HARD-RULE>
Always verify DNS resolution and NTP synchronization before attempting a domain join. Centrify depends on accurate DNS (forward and reverse) and time within 5 minutes of the domain controller. Skipping this causes the majority of join failures.
```bash
# Verify DNS resolves domain and DCs
nslookup DOMAIN.EXAMPLE.COM
nslookup -type=SRV _ldap._tcp.DOMAIN.EXAMPLE.COM
host -t SRV _kerberos._tcp.DOMAIN.EXAMPLE.COM

# Verify time sync (max 5-minute skew for Kerberos)
timedatectl status
chronyc tracking        # RHEL 9
chronyc sources -v      # Ubuntu 24.04 / RHEL 9
```
</HARD-RULE>

<HARD-RULE>
Never delete the computer account from Active Directory while the Centrify agent (adclient) is running on the machine. This orphans the host, breaks Kerberos authentication, and requires a forced leave/rejoin. Always run `adleave` from the Linux host first, then clean up the AD object if needed.
</HARD-RULE>

<HARD-RULE>
Always back up centrify.conf before making changes. A misconfigured centrify.conf can lock out all AD users.
```bash
sudo cp /etc/centrifydc/centrify.conf /etc/centrifydc/centrify.conf.bak.$(date +%Y%m%d%H%M%S)
```
</HARD-RULE>

<HARD-RULE>
Test zone changes (role assignments, command rights, access permissions) in a staging/dev zone before applying to production zones. Zone misconfigurations can instantly lock out users or grant unintended privileges across all machines in that zone.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [install-domainjoin-config.md](install-domainjoin-config.md) | architecture overview, installation, domain join, and centrify.conf configuration |
| [troubleshooting-migration-reference.md](troubleshooting-migration-reference.md) | troubleshooting, migration patterns, OS-specific notes, and essential commands quick reference |
| [zones-privileges-pam-gpo.md](zones-privileges-pam-gpo.md) | zone-based access control, privilege elevation (dzdo/dzsh), PAM/NSS integration, Group Policy for Linux, multi-forest/trust, and user/group management |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Joining Linux to AD without verifying DNS and NTP first | adclient relies on Kerberos which requires accurate time sync and proper DNS SRV records; join fails silently or intermittently | Verify DNS resolution of AD domain controllers and NTP sync (within 5 minutes) before running adjoin |
| Granting dzdo ALL to AD groups instead of granular commands | Equivalent to giving root; violates least privilege; audit findings in regulated environments | Define specific command rights in Centrify zones; map AD groups to role-based command sets |
| Not configuring PAM/NSS fallback for local accounts | If adclient goes offline (network issue, DC unavailable), no one can log in — including emergency accounts | Keep local emergency accounts in /etc/passwd with PAM configured to fall back to local auth if Centrify is unavailable |
| Using a single Centrify zone for all servers | Different server roles need different access policies; one zone means one permission set for everything | Create zones by function (web servers, database servers, batch servers); assign AD groups per zone |
| Not monitoring adclient health and domain connectivity | Silent disconnection from AD; users locked out; security events not captured until someone tries to log in | Monitor `adinfo --mode` and `adinfo --domain` via cron or Prometheus exporter; alert on offline status |

---

## Related Skills

| Skill | Relationship |
|---|---|
| `ubuntu-server-admin` | Base OS administration for Ubuntu 24.04 — prerequisites (DNS, NTP, networking, PAM, NSS) |
| `rhel-server-admin` | Base OS administration for RHEL 9 — prerequisites (DNS, NTP, firewalld, SELinux, authselect) |
| `docker-admin` | Running Centrify in containers — agent-per-container vs host-level join, identity propagation |
| `windows-sso` | AD FS, Entra ID, SAML/OAuth SSO — the Windows side of the same AD infrastructure |
