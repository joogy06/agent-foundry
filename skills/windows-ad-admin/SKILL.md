---
name: windows-ad-admin
description: Use when administering Windows Active Directory — AD DS architecture (domains, forests, trusts, sites/services), FSMO roles (Schema Master, Domain Naming, RID, PDC, Infrastructure), replication (intra-site/inter-site, DFSR/SYSVOL, replication topology), Group Policy (GPO design, precedence, WMI filters, security filtering, ADMX templates), organizational unit design, DNS integration (AD-integrated zones, SRV records), AD Certificate Services (PKI, certificate templates, auto-enrollment), AD DS monitoring and troubleshooting (dcdiag, repadmin, Event Viewer), and hybrid identity (Entra Connect, cloud sync). Complements windows-ps-server-admin and windows-sso. Part of the windows-* skill family.
family: windows
disambiguation: Active Directory ITSELF — forests, trusts, FSMO, replication, GPO design. General server administration via PowerShell is windows-ps-server-admin; federation and SSO are windows-sso.
---

# Windows Active Directory Administration

Deep architectural and operational guidance for Active Directory Domain Services. Targets Windows Server 2016/2019/2022/2025. For PowerShell AD cmdlets (New-ADUser, Get-ADGroup, etc.) see `windows-ps-server-admin`. For SSO/federation protocols (AD FS, SAML, OIDC, Kerberos delegation) see `windows-sso`. For security hardening (firewall, Defender, BitLocker, AppLocker) see `windows-ps-security`.

<HARD-RULE>
Never seize FSMO roles unless the original holder is permanently offline — seizure without proper decommission creates conflicting role holders that corrupt directory data. Always attempt a graceful transfer first with `Move-ADDirectoryServerOperationMasterRole`. Only use `-Force` (seize) after confirming the original DC will never return to the network. After seizure, the old DC must never be reconnected — metadata cleanup is required.
</HARD-RULE>

<HARD-RULE>
Always test GPO changes in a test OU before applying to production OUs — GPO misconfigurations (login scripts, security settings, software restrictions) can lock out entire departments instantly. Link new or modified GPOs to a staging OU containing test accounts/computers, validate with `gpresult /r` and RSoP, then promote to production OUs only after confirmation.
</HARD-RULE>

<HARD-RULE>
Never place all domain controllers in a single site — losing that site means losing authentication for the entire domain. Distribute DCs across physical locations, map each location to an AD site with appropriate subnets, and ensure at least one DC with a Global Catalog replica exists per major site.
</HARD-RULE>

<HARD-RULE>
Always keep at least one offline root CA — an online root CA with a compromised private key means your entire PKI trust chain is broken and every certificate must be revoked. The root CA should only come online to sign subordinate CA certificates and publish CRLs, then be powered off and stored securely. Only issuing (subordinate) CAs should be online.
</HARD-RULE>

---

## 1. AD DS Architecture

### Logical Structure

**Forest** is the outermost security boundary. All domains in a forest share a single schema, configuration partition, and global catalog. Cross-forest access requires explicit forest trusts.

**Domain** is the primary administrative and replication boundary. Each domain has its own NTDS.dit database, security policies, and trust relationships. A domain can contain millions of objects.

**Tree** is a contiguous DNS namespace of domains sharing a transitive parent-child trust (e.g., `corp.example.com` -> `eu.corp.example.com`).

**Organizational Unit (OU)** is a container within a domain for delegating administration and linking Group Policy. OUs do not affect replication or trust — they are purely administrative.

### Domain and Forest Functional Levels

| Level | Key Features Unlocked |
|---|---|
| Windows Server 2016 | Privileged Access Management (PAM), temporal group membership, MIM integration |
| Windows Server 2025 | Latest schema extensions, security defaults, Entra integration improvements |

Raise functional level only after ALL DCs in the domain (domain FL) or forest (forest FL) run the target OS version. Raising is irreversible — there is no rollback.

```powershell
# Check current levels
Get-ADDomain | Select-Object DomainMode
Get-ADForest | Select-Object ForestMode

# Raise (irreversible)
Set-ADDomainMode -Identity "corp.example.com" -DomainMode Windows2016Domain
Set-ADForestMode -Identity "example.com" -ForestMode Windows2016Forest
```

### Naming Contexts (Partitions)

Every DC hosts a set of naming contexts (directory partitions):

| Partition | Scope | Content |
|---|---|---|
| Domain NC | Per-domain (replicated to all DCs in that domain) | Users, groups, computers, OUs, GPO links |
| Configuration NC | Forest-wide (all DCs) | Sites, services, subnets, replication topology, ADCS config |
| Schema NC | Forest-wide (all DCs) | Object class and attribute definitions |
| ForestDNSZones | Forest-wide (all DNS DCs) | Forest-scoped DNS records (_msdcs zone) |
| DomainDNSZones | Per-domain (DNS DCs in that domain) | Domain-scoped AD-integrated DNS records |

### LDAP Structure

```
DC=corp,DC=example,DC=com                    # Domain root
  OU=Headquarters                            # Organizational Unit
    OU=IT                                    # Nested OU
      CN=John Smith                          # Common Name (user object)
  CN=Users                                   # Default container (not an OU)
  CN=Computers                               # Default container
  OU=Domain Controllers                      # DC computer accounts
```

Key LDAP concepts:
- **DN (Distinguished Name):** Full path — `CN=John Smith,OU=IT,OU=Headquarters,DC=corp,DC=example,DC=com`
- **RDN (Relative Distinguished Name):** Leftmost component — `CN=John Smith`
- **Base DN:** Search starting point — typically the domain root
- **Global Catalog port:** 3268 (LDAP) / 3269 (LDAPS) — searches partial attribute set across all domains in the forest

### Database Files

| File | Path | Purpose |
|---|---|---|
| NTDS.dit | `%SystemRoot%\NTDS\ntds.dit` | AD database (ESE / Extensible Storage Engine) |
| edb.log | `%SystemRoot%\NTDS\edb.log` | Transaction log (10 MB each, circular by default) |
| edb.chk | `%SystemRoot%\NTDS\edb.chk` | Checkpoint file (tracks committed transactions) |
| temp.edb | `%SystemRoot%\NTDS\temp.edb` | Temporary working space |
| SYSVOL | `%SystemRoot%\SYSVOL\` | Group Policy templates, login scripts, replication content |

For performance, place NTDS.dit and logs on separate physical disks. SYSVOL should be on a reliable volume — its corruption affects GPO delivery domain-wide.

---

## 2. FSMO Roles

Five operations master roles prevent conflicting updates to critical directory data. Only the role holder can perform the specific operation.

### Forest-Wide Roles (One Per Forest)

**Schema Master** — Controls all schema modifications (attribute and class definitions). Only one DC can write to the Schema NC at a time. Typically placed on the forest root domain's primary DC.

**Domain Naming Master** — Controls addition/removal of domains in the forest. Must be a Global Catalog server. Rarely used after initial deployment.

### Domain-Wide Roles (One Per Domain)

**RID Master** — Allocates RID (Relative Identifier) pools to DCs. Every security principal (user, group, computer) gets a unique SID = Domain SID + RID. If the RID Master is offline, DCs exhaust their local RID pool and cannot create new objects.

**PDC Emulator** — Most heavily loaded role. Handles: password change replication (immediate, not waiting for normal replication), account lockout processing, time synchronization source for the domain, Group Policy central store coordination, legacy NTLM authentication fallback.

**Infrastructure Master** — Resolves cross-domain object references (phantom records). In a multi-domain forest, do NOT place this on a GC server (unless all DCs are GCs). In a single-domain forest, placement does not matter.

### Identifying Role Holders

```cmd
:: Command Prompt
netdom query fsmo
```

```powershell
# PowerShell
Get-ADDomain | Select-Object InfrastructureMaster, RIDMaster, PDCEmulator
Get-ADForest | Select-Object SchemaMaster, DomainNamingMaster

# Or all at once
Get-ADDomainController -Filter * | Select-Object Name, OperationMasterRoles
```

### Transferring Roles (Graceful — Both DCs Online)

```powershell
# Transfer all five roles to DC02 (use specific role names as needed)
Move-ADDirectoryServerOperationMasterRole -Identity "DC02" `
    -OperationMasterRole SchemaMaster, DomainNamingMaster, RIDMaster, PDCEmulator, InfrastructureMaster

# Using ntdsutil (interactive — run on target DC)
# ntdsutil -> roles -> connections -> connect to server DC02 -> quit
# transfer schema master / transfer naming master / transfer rid master /
# transfer pdc / transfer infrastructure master
```

### Seizing Roles (Emergency — Original DC Permanently Offline)

```powershell
# ONLY when the original holder will NEVER return to the network
Move-ADDirectoryServerOperationMasterRole -Identity "DC02" `
    -OperationMasterRole RIDMaster -Force

# After seizure: clean up metadata of the dead DC
ntdsutil
# metadata cleanup -> connections -> connect to server DC02 -> quit
# select operation target -> list domains -> select domain 0
# list sites -> select site 0 -> list servers in site
# select server <number of dead DC> -> quit
# remove selected server
```

After seizing the RID Master, the new holder invalidates the old RID pool to prevent SID collisions. After seizing Schema Master or Domain Naming Master, those roles are safe to seize (rarely active). PDC Emulator and Infrastructure Master are safe to seize and re-transfer later if the original DC recovers.

### Placement Best Practices

| Role | Placement Guidance |
|---|---|
| Schema Master | Forest root domain, not performance-critical, co-locate with Domain Naming Master |
| Domain Naming Master | Forest root domain, must be GC, co-locate with Schema Master |
| RID Master | Well-connected DC in each domain, reliable network |
| PDC Emulator | Fastest hardware, best network connectivity, most central DC — highest load |
| Infrastructure Master | Non-GC DC (multi-domain) or any DC (single-domain / all-GC) |

---

## 3. Replication

AD uses multi-master replication — changes can be made on any DC and propagate to all others. The Knowledge Consistency Checker (KCC) automatically builds the replication topology.

### Intra-Site Replication

- Triggered by change notification — the originating DC notifies direct partners within 15 seconds
- Partners pull changes immediately (not push)
- Uncompressed (assumed fast LAN)
- KCC builds a ring topology with shortcut connections (no more than 3 hops between any two DCs)
- Uses RPC over IP (TCP port 135 + dynamic ports)

### Inter-Site Replication

- Scheduled (default: every 180 minutes, configurable per site link)
- Compressed (saves WAN bandwidth — typically 85-90% compression)
- Uses designated bridgehead servers (one per site per partition)
- Transport: RPC over IP (preferred) or SMTP (Schema and Configuration only, not Domain NC)
- Site link cost determines routing preference — lower cost = preferred path

### Replication Topology Components

**Site Link:** Defines which sites can replicate directly and at what cost/schedule.

```
Site Link: "HQ-Branch1"
  Sites: HQ, Branch1
  Cost: 100
  Replication interval: 60 minutes
  Schedule: 24x7
```

**Site Link Bridge:** Enables transitive replication across site links. If site A links to B and B links to C, a bridge allows A to replicate with C through B. Enabled by default ("Bridge all site links").

**Connection Object:** Represents a one-way replication agreement between two DCs. KCC creates these automatically. Manual connection objects are possible but rarely needed.

**Bridgehead Server:** The designated DC in each site that handles inter-site replication for a partition. KCC auto-selects, but you can designate preferred bridgehead servers.

### Replication Monitoring

```cmd
:: Summary of replication health across all DCs
repadmin /replsummary

:: Detailed replication partners and status for a specific DC
repadmin /showrepl DC01

:: Force replication of all partitions on all DCs
repadmin /syncall DC01 /AdeP

:: Show replication queue
repadmin /queue DC01

:: Show replication metadata for a specific object
repadmin /showobjmeta DC01 "CN=John Smith,OU=IT,DC=corp,DC=example,DC=com"

:: Check for replication failures across the forest
repadmin /replsummary /bysrc /bydest /sort:delta
```

```powershell
# PowerShell equivalent for replication partners
Get-ADReplicationPartnerMetadata -Target "DC01" -Scope Domain |
    Select-Object Server, Partner, LastReplicationSuccess, LastReplicationResult

# Check for replication failures
Get-ADReplicationFailure -Target "DC01"
```

### SYSVOL Replication (DFSR)

SYSVOL contains Group Policy templates and login scripts. Since Windows Server 2008 R2, SYSVOL uses DFS Replication (DFSR) instead of the legacy FRS (File Replication Service).

```powershell
# Check DFSR health
dfsrdiag pollad
Get-DfsReplicationGroup -GroupName "Domain System Volume"
Get-DfsrState -ComputerName DC01

# Check DFSR backlog (pending changes)
Get-DfsrBacklog -SourceComputerName DC01 -DestinationComputerName DC02 `
    -GroupName "Domain System Volume" -FolderName "SYSVOL Share"
```

If migrating from FRS to DFSR:
```cmd
:: Check current migration state
dfsrmig /getglobalstate
dfsrmig /getmigrationstate

:: Migrate (four states: Start -> Prepared -> Redirected -> Eliminated)
dfsrmig /setglobalstate 1   :: Prepared
dfsrmig /setglobalstate 2   :: Redirected
dfsrmig /setglobalstate 3   :: Eliminated (no rollback after this)
```

### USN and High-Watermark Vector

AD tracks replication using Update Sequence Numbers (USNs). Each DC maintains:
- **Local USN:** Incremented for every write (local or replicated)
- **Up-to-dateness vector:** Records the highest originating USN seen from every DC
- **High-watermark:** Per-partner tracking of the last USN received

This prevents replication loops and ensures each change is applied exactly once.

---

## 4. Sites and Services

Sites map the physical network topology into AD so that clients authenticate to nearby DCs and replication follows efficient paths.

### Site Design Principles

- One AD site per well-connected physical location (LAN speed, typically > 10 Mbps)
- Separate locations connected by WAN links should be separate sites
- Every IP subnet must be mapped to a site — unmapped clients use the Default-First-Site-Name and may authenticate to distant DCs

### Subnet-to-Site Mapping

```powershell
# Create a site
New-ADReplicationSite -Name "BranchOffice-London"

# Create subnet and assign to site
New-ADReplicationSubnet -Name "10.20.0.0/16" -Site "BranchOffice-London"
New-ADReplicationSubnet -Name "10.21.0.0/24" -Site "BranchOffice-London"

# Verify
Get-ADReplicationSubnet -Filter * | Select-Object Name, Site
```

### Site Links

```powershell
# Create site link
New-ADReplicationSiteLink -Name "HQ-London" `
    -SitesIncluded "HQ-NewYork","BranchOffice-London" `
    -Cost 200 -ReplicationFrequencyInMinutes 60

# Modify schedule (replicate only during off-hours)
Set-ADReplicationSiteLink -Identity "HQ-London" `
    -ReplicationSchedule @{DayOfWeek="Saturday"; StartHour=0; EndHour=23}
```

Cost values guide the KCC in building topology:
- Lower cost = preferred (e.g., HQ-to-HQ: 100, HQ-to-branch: 500)
- KCC uses Dijkstra's algorithm on costs to find shortest replication paths

### DC Placement Strategy

| Site Type | Minimum DCs | GC Required? | DNS Required? |
|---|---|---|---|
| Hub (HQ / datacenter) | 2+ (redundancy) | Yes (at least one) | Yes (AD-integrated) |
| Branch (50+ users) | 1 (RODC preferred) | Yes (partial attribute set) | Yes |
| Branch (< 50 users) | 0 (rely on site link to hub) | No | Conditional forwarder |

**Read-Only Domain Controller (RODC):** Ideal for branch offices with limited physical security. Holds a read-only copy of AD, caches only specified credentials (Password Replication Policy), and cannot be used to modify directory data.

```powershell
# Install RODC
Install-ADDSDomainController -DomainName "corp.example.com" `
    -SiteName "BranchOffice-London" `
    -ReadOnlyReplica -InstallDns `
    -Credential (Get-Credential) -SafeModeAdministratorPassword (Read-Host -AsSecureString)
```

### Client Site Affinity

Clients determine their site by matching their IP subnet against AD subnet-to-site mappings. The DC Locator process:

1. Client queries DNS for `_ldap._tcp.<sitename>._sites.dc._msdcs.<domain>` SRV records
2. If site-specific DC found, client uses it
3. If no DC in site, client uses next-closest-site DC (automatic site coverage)
4. DC returns site name in LDAP ping — client caches site for future lookups

---

## 5. Group Policy

Group Policy Objects (GPOs) deliver configuration to users and computers. Each GPO has two components:
- **Group Policy Container (GPC):** Stored in AD (CN=Policies,CN=System,DC=...) — metadata, link info, version
- **Group Policy Template (GPT):** Stored in SYSVOL (`\\domain\SYSVOL\domain\Policies\{GUID}`) — actual settings files

### Processing Order (LSDOU)

```
1. Local Group Policy     (gpedit.msc on the machine)
2. Site-linked GPOs       (rarely used — coarse, affects all domains in the site)
3. Domain-linked GPOs     (domain-wide baselines: password policy, audit policy)
4. OU-linked GPOs         (progressively more specific — parent OU first, child OU last)
```

**Last writer wins** — if the same setting is configured in multiple GPOs, the last-applied GPO (deepest OU) takes precedence.

### Precedence Modifiers

**Block Inheritance:** Set on an OU — blocks all GPOs from parent containers. Use sparingly; creates management blind spots.

**Enforced (No Override):** Set on a GPO link — overrides Block Inheritance and always applies. Use for security baselines that must not be overridden by child OUs.

**Link Order:** When multiple GPOs are linked to the same OU, lower link order number = higher precedence (applied last).

### Security Filtering and WMI Filtering

**Security Filtering:** By default, GPOs apply to "Authenticated Users." Replace with a specific security group to target a subset of users/computers.

```powershell
# Remove default "Authenticated Users" and add specific group
Set-GPPermission -Name "Deploy Chrome" -PermissionLevel GpoApply `
    -TargetName "Chrome-Deployment-Group" -TargetType Group
Set-GPPermission -Name "Deploy Chrome" -PermissionLevel None `
    -TargetName "Authenticated Users" -TargetType Group -Replace
```

**WMI Filtering:** Apply GPOs based on WMI queries (e.g., only laptops, only servers with > 8 GB RAM, only Windows 11). WMI filters are evaluated on the client — expensive queries slow logon.

```
SELECT * FROM Win32_OperatingSystem WHERE ProductType = "1"
-- ProductType: 1 = Workstation, 2 = DC, 3 = Server
```

```
SELECT * FROM Win32_ComputerSystem WHERE PCSystemType = "2"
-- PCSystemType: 2 = Mobile (laptop)
```

### Loopback Processing

By default, user settings come from GPOs linked where the user object lives. Loopback processing changes this so user settings come from GPOs linked where the computer object lives. Two modes:

- **Replace:** Computer's GPO user settings completely replace the user's normal settings
- **Merge:** Computer's GPO user settings are applied after (and override conflicts with) the user's normal settings

Use case: kiosk machines, conference room PCs, terminal servers where the computer location should dictate user experience regardless of who logs on.

### ADMX/ADML Central Store

Group Policy Administrative Templates (ADMX) define the settings visible in Group Policy Editor. The Central Store provides a single forest-wide location:

```
\\corp.example.com\SYSVOL\corp.example.com\Policies\PolicyDefinitions\
  *.admx                          (language-neutral definition files)
  en-US\*.adml                    (English language strings)
  fr-FR\*.adml                    (French language strings)
```

Copy ADMX files from `C:\Windows\PolicyDefinitions\` on the latest Windows version. Third-party ADMX files (Chrome, Firefox, Office, Adobe) go here too.

### GPO Version Control (AGPM)

Advanced Group Policy Management (part of MDOP) provides check-in/check-out, version history, role-based delegation (Reviewer, Editor, Approver), and offline editing for GPOs. Essential for enterprises with multiple GPO administrators.

### Preference Items vs. Policy Settings

| Aspect | Policy Settings | Preference Items |
|---|---|---|
| Enforced | Yes — setting reverts when GPO removed | No — "tattooed" (persists after GPO removed) |
| UI indicator | Grayed out in client UI | User can change locally |
| Use case | Security requirements, compliance | Default configurations, drive mappings, printers |
| Targeting | Security filtering, WMI filters | Item-level targeting (flexible, client-side) |

### Troubleshooting GPO Application

```cmd
:: Show applied GPOs and RSoP for current user/computer
gpresult /r

:: Detailed HTML report
gpresult /h C:\Temp\gpreport.html

:: Force immediate GPO refresh
gpupdate /force

:: Model what would apply (planning mode)
:: Use Group Policy Modeling wizard in GPMC
```

```powershell
# RSoP (Resultant Set of Policy) for a remote computer
Get-GPResultantSetOfPolicy -Computer "WORKSTATION01" -ReportType Html -Path "C:\Temp\rsop.html"

# List all GPOs in domain
Get-GPO -All | Select-Object DisplayName, GpoStatus, CreationTime, ModificationTime

# Find GPOs linked to a specific OU
(Get-ADOrganizationalUnit -Identity "OU=IT,OU=HQ,DC=corp,DC=example,DC=com").LinkedGroupPolicyObjects

# Find unlinked GPOs (cleanup candidates)
Get-GPO -All | Where-Object {
    ($_ | Get-GPOReport -ReportType Xml | Select-Xml -XPath "//LinksTo").Count -eq 0
}
```

---

## 6. OU Design

### Hierarchy Patterns

**Geographic (location-based):**
```
DC=corp,DC=example,DC=com
  OU=North-America
    OU=New-York
      OU=Users
      OU=Computers
      OU=Groups
  OU=Europe
    OU=London
      OU=Users
      OU=Computers
```
Best when: offices are autonomous, different GPO requirements per region, delegated regional IT teams.

**Functional (department/role-based):**
```
DC=corp,DC=example,DC=com
  OU=IT
    OU=Users
    OU=Servers
  OU=Finance
    OU=Users
    OU=Computers
  OU=HR
```
Best when: central IT, uniform policies, department-specific settings.

**Hybrid (most common in enterprises):**
```
DC=corp,DC=example,DC=com
  OU=Corp
    OU=Users
      OU=IT
      OU=Finance
      OU=HR
    OU=Computers
      OU=Workstations
      OU=Servers
    OU=Groups
      OU=Security
      OU=Distribution
    OU=Service-Accounts
```
Best when: you need both GPO targeting by object type and administrative delegation by department.

### Delegation of Control

Delegate OU administration without granting domain-wide privileges:

```powershell
# Grant helpdesk team password reset on an OU (uses Delegation of Control Wizard equivalent)
$ou = "OU=Users,OU=HQ,DC=corp,DC=example,DC=com"
$group = Get-ADGroup "Helpdesk-Team"
$acl = Get-Acl "AD:\$ou"

# Create ACE for Reset Password extended right
$guid = [GUID]"00299570-246d-11d0-a768-00aa006e0529"  # Reset Password
$ace = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
    $group.SID, "ExtendedRight", "Allow", $guid, "Descendents",
    [GUID]"bf967aba-0de6-11d0-a285-00aa003049e2"  # User object class
)
$acl.AddAccessRule($ace)
Set-Acl "AD:\$ou" $acl
```

### Protected OUs

Enable "Protect object from accidental deletion" on all OUs. This sets a Deny ACE for the Everyone principal on the Delete and Delete Subtree permissions.

```powershell
# Enable protection on all OUs
Get-ADOrganizationalUnit -Filter * |
    Set-ADOrganizationalUnit -ProtectedFromAccidentalDeletion $true

# Check which OUs lack protection
Get-ADOrganizationalUnit -Filter * -Properties ProtectedFromAccidentalDeletion |
    Where-Object { -not $_.ProtectedFromAccidentalDeletion } |
    Select-Object DistinguishedName
```

---

## 7. DNS Integration

AD is entirely dependent on DNS. Without functional DNS, domain join, authentication, replication, and GPO processing all fail.

### AD-Integrated DNS Zones

AD-integrated zones store DNS records in AD partitions instead of flat files, providing:
- Multi-master updates (any DC running DNS can accept dynamic updates)
- Secure dynamic updates (only authenticated machines can register/update records)
- Replication via AD replication (no separate zone transfers needed)
- Granular replication scope

| Replication Scope | Partition | Use Case |
|---|---|---|
| All DNS servers in the forest | ForestDNSZones | Forest-wide zones (_msdcs) |
| All DNS servers in the domain | DomainDNSZones | Standard forward/reverse lookup zones |
| All DCs in the domain | Domain NC | Legacy (not recommended) |

### Critical SRV Records

AD clients locate services via DNS SRV records under `_msdcs.<domain>`:

```
_ldap._tcp.dc._msdcs.corp.example.com      -> All DCs
_ldap._tcp.<site>._sites.dc._msdcs.corp... -> DCs in a specific site
_kerberos._tcp.dc._msdcs.corp.example.com  -> Kerberos KDC (all DCs)
_gc._tcp.corp.example.com                  -> Global Catalog servers
_ldap._tcp.pdc._msdcs.corp.example.com     -> PDC Emulator
```

If these records are missing, clients cannot find DCs. The Netlogon service registers them automatically on DC startup.

```cmd
:: Verify SRV records exist
nslookup -type=srv _ldap._tcp.dc._msdcs.corp.example.com

:: Force Netlogon to re-register SRV records
nltest /dsregdns
net stop netlogon && net start netlogon
```

### DNS Scavenging

Stale DNS records (from decommissioned machines) accumulate over time. Enable aging and scavenging:

```powershell
# Enable aging on the zone (sets no-refresh + refresh intervals)
Set-DnsServerZoneAging -Name "corp.example.com" -Aging $true `
    -NoRefreshInterval 7.00:00:00 -RefreshInterval 7.00:00:00

# Enable scavenging on the DNS server (runs periodically)
Set-DnsServerScavenging -ScavengingState $true -ScavengingInterval 7.00:00:00

# Check current aging/scavenging configuration
Get-DnsServerZoneAging -Name "corp.example.com"
Get-DnsServerScavenging
```

Default safe configuration: 7-day no-refresh + 7-day refresh = records eligible for scavenging after 14 days of no update.

### Conditional Forwarders and Stub Zones

**Conditional Forwarder:** Forward queries for a specific domain to designated DNS servers. Use for resolving partner domains or cloud zones.

```powershell
Add-DnsServerConditionalForwarderZone -Name "partner.com" `
    -MasterServers 10.50.1.10,10.50.1.11 -ReplicationScope Forest
```

**Stub Zone:** Contains only NS, SOA, and glue A records for a zone. Auto-updates from the authoritative server. Lighter than a conditional forwarder — useful when the partner's DNS servers change frequently.

### DNS Troubleshooting

```cmd
:: Comprehensive DNS health check
dcdiag /test:dns /v /e

:: Specific DNS tests
dcdiag /test:dns /DnsBasic
dcdiag /test:dns /DnsRecordRegistration
dcdiag /test:dns /DnsDynamicUpdate

:: Clear DNS cache on server
Clear-DnsServerCache

:: Check DNS resolution path
nslookup -debug corp.example.com
Resolve-DnsName -Name "corp.example.com" -Type A -DnsOnly
```

### Split-Brain DNS

When the same DNS zone (e.g., `example.com`) is used both internally and externally with different records. Internal clients resolve internal IPs from AD-integrated DNS; external clients resolve public IPs from the external DNS provider. Requires careful management — ensure internal zone has all records external clients need duplicated, or use DNS policies (Windows Server 2016+) for query-based resolution.

---

## 8. AD Certificate Services (AD CS)

AD CS provides a private PKI for issuing certificates to users, computers, and services within the organization.

### CA Hierarchy

```
Offline Root CA (standalone, air-gapped)
  |
  +-- Online Issuing CA 1 (enterprise, domain-joined)
  |     Issues: user, computer, web server, smart card certificates
  |
  +-- Online Issuing CA 2 (enterprise, domain-joined)
        Issues: code signing, OCSP response signing
```

- **Root CA:** Issues certificates only to subordinate CAs. Must be offline (powered down) except during subordinate CA certificate signing and CRL publishing. Standalone (not domain-joined) for maximum security.
- **Issuing CA (Subordinate):** Enterprise CA (domain-joined), handles day-to-day certificate issuance. Integrates with AD for auto-enrollment, certificate templates, and publishing.

### Certificate Templates

Templates define certificate purpose, key usage, validity, and enrollment permissions. Only Enterprise CAs use templates.

```powershell
# List published certificate templates
Get-CATemplate | Select-Object Name

# Duplicate and customize a template (via certtmpl.msc or PowerShell)
# Common templates to configure:
# - User                  (email signing, EFS, client auth)
# - Computer              (machine authentication, 802.1X)
# - Web Server            (SSL/TLS for IIS, internal services)
# - Workstation Authentication (domain computer identity)
# - Smartcard Logon       (two-factor with smart cards/virtual smart cards)
# - OCSP Response Signing (for OCSP responder)
```

Key template settings:
- **Cryptographic provider:** RSA 2048-bit minimum; prefer 4096-bit for CA certificates
- **Validity period:** 1-2 years for user/computer, 3-5 years for web server, 10-20 years for root CA
- **Key usage:** Digital signature, key encipherment, etc.
- **Enhanced key usage (EKU):** Client Authentication, Server Authentication, Smart Card Logon
- **Subject name:** Build from AD (auto-populate from user/computer attributes) or supply in request

### Auto-Enrollment

GPO-driven auto-enrollment allows computers and users to automatically request, receive, and renew certificates without manual intervention.

```
Computer Configuration -> Policies -> Windows Settings -> Security Settings
  -> Public Key Policies -> Certificate Services Client - Auto-Enrollment
    -> Enabled, Renew expired certificates, Update certificates that use templates
```

Requirements:
1. Certificate template published on the issuing CA
2. Template permissions: Autoenroll granted to target group (Domain Computers, Domain Users, etc.)
3. GPO linked to the OU containing the target objects
4. Enterprise CA online and accessible

### CRL Distribution and OCSP

**CRL (Certificate Revocation List):** Published by the CA at regular intervals. Clients download the CRL and cache it to check if a certificate has been revoked.

```powershell
# Check CRL distribution points configured on the CA
Get-CACrlDistributionPoint

# Publish a new CRL manually
certutil -CRL

# Verify CRL is accessible
certutil -URL "http://pki.corp.example.com/CertEnroll/IssuingCA.crl"
```

**OCSP (Online Certificate Status Protocol):** Real-time revocation checking. Lighter than CRL downloads for large environments. Deploy the Online Responder role on a separate server.

```powershell
# Install OCSP role
Install-WindowsFeature ADCS-Online-Cert -IncludeManagementTools

# Configure OCSP responder (via ocsp.msc or PowerShell)
```

### Key Archival and Recovery

Enable key archival for encryption certificates (not signing) so that encrypted data can be recovered if a user loses their private key:

1. Configure a Key Recovery Agent (KRA) certificate template
2. Issue KRA certificate to designated administrators
3. Enable key archival on the encryption certificate template
4. CA archives the private key, encrypted with the KRA's public key

```cmd
:: Recover an archived key
certutil -getkey <serial number> outputblob.pfx
certutil -recoverkey outputblob.pfx recoveredkey.pfx
```

---

## 9. Monitoring and Troubleshooting

### dcdiag — Comprehensive DC Health

```cmd
:: Run all tests on the local DC
dcdiag /v

:: Run all tests on all DCs in the domain
dcdiag /v /e

:: Specific critical tests
dcdiag /test:replications        :: Replication health
dcdiag /test:services            :: Critical services running (NTDS, Netlogon, KDC, DNS)
dcdiag /test:advertising         :: DC advertising correctly as DC, GC, time server
dcdiag /test:fsmocheck           :: FSMO role holders reachable
dcdiag /test:ridmanager          :: RID pool availability
dcdiag /test:machineaccount      :: DC machine account health
dcdiag /test:sysvolcheck         :: SYSVOL share accessible
dcdiag /test:topology            :: KCC topology generation
dcdiag /test:dns /DnsAll         :: Comprehensive DNS health
```

### repadmin — Replication Health

```cmd
:: One-line replication health summary
repadmin /replsummary

:: Show inbound replication partners and last replication status
repadmin /showrepl DC01

:: Show inter-site replication topology
repadmin /showism

:: Compare USNs across DCs for a specific object
repadmin /showmeta "CN=John Smith,OU=Users,DC=corp,DC=example,DC=com"

:: Force full sync of all partitions from all partners
repadmin /syncall DC01 /AdeP
:: Flags: A=all partitions, d=identify servers by DN, e=enterprise (cross-site), P=push

:: Check for lingering objects
repadmin /removelingeringobjects DC02 DC01_GUID dc=corp,dc=example,dc=com /advisory_mode
```

### Event Viewer — Key Logs

| Log | Path | What to Watch |
|---|---|---|
| Directory Service | Applications and Services Logs > Directory Service | Replication errors, database issues, FSMO problems |
| DNS Server | Applications and Services Logs > DNS Server | Zone loading, dynamic update failures, recursion errors |
| DFS Replication | Applications and Services Logs > DFS Replication | SYSVOL replication health, conflicts, backlog |
| System | Windows Logs > System | Netlogon errors, time sync issues, service failures |
| Security | Windows Logs > Security | Authentication events, account lockouts, privilege use |

Critical Event IDs:
- **1311 (NTDS KCC):** KCC cannot build a spanning tree — replication topology broken
- **1864 (NTDS Replication):** Replication latency warning — DC has not replicated in X days
- **2042 (NTDS Replication):** DC tombstone lifetime exceeded — lingering objects risk
- **4740 (Security):** Account lockout — investigate source with `Get-WinEvent` or `lockoutstatus.exe`

### Tombstone Lifetime and Lingering Objects

When an object is deleted, AD keeps a tombstone (stripped-down record) for 180 days (default for forests created with Server 2003 SP1+). If a DC is offline longer than the tombstone lifetime, it may reanimate deleted objects — these are lingering objects.

```cmd
:: Check tombstone lifetime
dsquery * "CN=Directory Service,CN=Windows NT,CN=Services,CN=Configuration,DC=corp,DC=example,DC=com" -attr tombstoneLifetime

:: Enable Strict Replication Consistency to prevent lingering object reanimation
repadmin /regkey DC01 +strict
```

### AD Database Maintenance

The AD database is self-maintaining (online defragmentation runs every 12 hours). Offline defragmentation is only needed to reclaim disk space after massive deletions.

```cmd
:: Offline defragmentation (requires Directory Services stopped)
net stop ntds
ntdsutil
  activate instance ntds
  files
  compact to C:\Temp\NTDS
  quit
  quit
:: Replace original NTDS.dit with compacted version, delete old logs
net start ntds
```

### AD Recycle Bin

Enables restoration of deleted AD objects with all attributes intact (no authoritative restore needed). Must be enabled at the forest level — irreversible.

```powershell
# Enable AD Recycle Bin (forest functional level 2008 R2+, irreversible)
Enable-ADOptionalFeature -Identity "Recycle Bin Feature" `
    -Scope ForestOrConfigurationSet -Target "corp.example.com"

# Find deleted objects
Get-ADObject -Filter 'isDeleted -eq $true' -IncludeDeletedObjects -Properties * |
    Select-Object Name, DistinguishedName, WhenChanged

# Restore a deleted user
Get-ADObject -Filter 'Name -like "John Smith*" -and isDeleted -eq $true' -IncludeDeletedObjects |
    Restore-ADObject

# Restore a deleted OU and all children
Get-ADObject -Filter 'isDeleted -eq $true -and LastKnownParent -like "*OU=Finance*"' `
    -IncludeDeletedObjects | Restore-ADObject
```

---

## 10. Hybrid Identity

Hybrid identity connects on-premises AD with Microsoft Entra ID (formerly Azure AD) for cloud service access.

### Entra Connect (formerly Azure AD Connect)

Entra Connect synchronizes on-premises AD objects to Entra ID. Three authentication methods:

| Method | How It Works | Best For |
|---|---|---|
| Password Hash Sync (PHS) | Hashes of password hashes synced to Entra ID; auth happens in cloud | Simplest, most resilient, enables leaked credential detection |
| Pass-Through Authentication (PTA) | Auth request forwarded to on-prem agent; password never leaves on-prem | Orgs requiring on-prem password validation, immediate lockout enforcement |
| Federation (AD FS) | Auth redirected to on-prem AD FS; SAML/WS-Fed token issued | Complex claims rules, smart card auth, third-party MFA at sign-in |

PHS is recommended as primary or fallback — it continues working if on-prem infrastructure is down.

### Entra Connect — Key Configuration

```
Source anchor: ms-DS-ConsistencyGuid (default, recommended) or ObjectGUID
Filtering: OU-based (sync only selected OUs) or group-based (pilot sync)
Password writeback: Enables cloud password changes to write back to on-prem AD
Device writeback: Syncs Entra ID registered devices back to on-prem AD
Group writeback: Syncs Entra ID groups to on-prem AD as distribution or security groups
```

Sync cycle runs every 30 minutes by default. Force sync:

```powershell
# On the Entra Connect server
Import-Module ADSync
Start-ADSyncSyncCycle -PolicyType Delta    # Delta sync (changes only)
Start-ADSyncSyncCycle -PolicyType Initial  # Full sync (use sparingly)

# Check sync status
Get-ADSyncScheduler
Get-ADSyncConnectorRunStatus
```

### Entra Cloud Sync

Lightweight alternative to Entra Connect — uses a small agent instead of a full sync server. Supports multi-forest scenarios with simpler infrastructure. Cannot do PTA or device writeback (as of 2025).

### Seamless SSO

Enables on-prem domain-joined users to automatically authenticate to Entra ID resources without entering credentials. Uses Kerberos — the user's Kerberos ticket is presented to Entra ID.

Requirements:
- PHS or PTA as authentication method
- Computer account `AZUREADSSOACC` created in on-prem AD
- Kerberos decryption key shared between on-prem and Entra ID
- Client must be on domain-joined machine on corporate network

Roll the Kerberos decryption key every 30 days for security.

### Hybrid Join

**Hybrid Entra Join:** Devices are joined to both on-prem AD and Entra ID. Enables conditional access policies, Intune co-management, and Windows Hello for Business.

```powershell
# Verify hybrid join status on a client
dsregcmd /status
# Look for: AzureAdJoined: YES, DomainJoined: YES

# Check Entra Connect device sync
Get-ADSyncConnectorStatistics -ConnectorName "corp.example.com"
```

### Entra Connect Health

Monitoring service for the sync infrastructure:
- Alerts on sync failures, password sync issues, and agent health
- Provides reports on risky sign-ins and AD FS performance
- Requires Entra ID P1 or P2 license

```powershell
# Install Health Agent for AD DS (on each DC to monitor)
# Download from: https://aka.ms/aaboradagent
# Install Health Agent for Sync (on Entra Connect server — installed automatically)
# Install Health Agent for AD FS (on each AD FS server)
```

---

## 11. Hardening

### Tiered Administration Model

Microsoft's recommended model for protecting privileged credentials:

| Tier | Assets | Admin Scope | Example |
|---|---|---|---|
| Tier 0 | AD DS, DCs, PKI, Entra Connect | Identity infrastructure | Domain Admins, Schema Admins, CA admins |
| Tier 1 | Member servers, applications | Server and application management | Server admins, SQL admins, Exchange admins |
| Tier 2 | Workstations, devices | End-user device management | Helpdesk, desktop support |

**Key rule:** Never log into a lower-tier asset from a higher-tier account. A Domain Admin should never log into a user workstation (credential theft risk via pass-the-hash or Mimikatz).

### Protected Users Group

Members of the Protected Users security group get hardened credential protections:
- No NTLM authentication (Kerberos only)
- No DES or RC4 in Kerberos pre-authentication (AES only)
- No credential delegation or caching
- TGT lifetime reduced to 4 hours (non-renewable)

```powershell
# Add privileged accounts to Protected Users
Add-ADGroupMember -Identity "Protected Users" -Members "admin-jsmith", "svc-tier0"

# Verify membership
Get-ADGroupMember -Identity "Protected Users"
```

Do NOT add service accounts that need NTLM or credential delegation to Protected Users — it will break their authentication.

### Authentication Policies and Silos

Restrict where Tier 0 accounts can authenticate (Windows Server 2012 R2+, domain functional level 2012 R2+):

```powershell
# Create an authentication policy
New-ADAuthenticationPolicy -Name "Tier0-DC-Only" `
    -UserTGTLifetimeMins 240 `
    -Enforce

# Create a silo that restricts logon to DCs only
New-ADAuthenticationPolicySilo -Name "Tier0-Silo" `
    -UserAuthenticationPolicy "Tier0-DC-Only" `
    -ComputerAuthenticationPolicy "Tier0-DC-Only" `
    -Enforce

# Assign accounts to the silo
Set-ADUser -Identity "admin-jsmith" -AuthenticationPolicySilo "Tier0-Silo"
Grant-ADAuthenticationPolicySiloAccess -Identity "Tier0-Silo" -Account "admin-jsmith"
```

### LAPS (Local Administrator Password Solution)

Automatically rotates and stores unique local administrator passwords in AD. Prevents lateral movement via shared local admin credentials.

```powershell
# Windows LAPS (built into Windows Server 2025, Windows 11 22H2+)
# Legacy LAPS requires separate download for older OS

# Check LAPS configuration
Get-LapsADPassword -Identity "WORKSTATION01" -AsPlainText

# Configure LAPS via GPO
# Computer Configuration -> Policies -> Administrative Templates -> LAPS
#   -> Enable local admin password management
#   -> Password complexity: Large letters + small letters + numbers + specials
#   -> Password length: 20+
#   -> Password age: 30 days
```

### Group Managed Service Accounts (gMSA)

gMSAs provide automatic password management for service accounts. Passwords are 240 characters, auto-rotated every 30 days, and never known to administrators.

```powershell
# Create KDS root key (one-time, forest-wide)
# Use -EffectiveImmediately for lab; production: wait 10 hours for replication
Add-KdsRootKey -EffectiveImmediately

# Create gMSA
New-ADServiceAccount -Name "gMSA-WebApp" `
    -DNSHostName "gmsa-webapp.corp.example.com" `
    -PrincipalsAllowedToRetrieveManagedPassword "WebServers-Group" `
    -KerberosEncryptionType AES128,AES256

# Install gMSA on target server
Install-ADServiceAccount -Identity "gMSA-WebApp"
Test-ADServiceAccount -Identity "gMSA-WebApp"  # Returns True if working
```

### AdminSDHolder and SDProp

AdminSDHolder is a special container whose ACL is stamped onto all protected groups (Domain Admins, Enterprise Admins, Schema Admins, etc.) every 60 minutes by the SDProp process. This prevents accidental or malicious permission changes on privileged accounts.

If you modify permissions on a protected account and they revert within an hour, SDProp is overwriting them. Modify the AdminSDHolder ACL instead:

```powershell
# View AdminSDHolder ACL
Get-Acl "AD:\CN=AdminSDHolder,CN=System,DC=corp,DC=example,DC=com" |
    Select-Object -ExpandProperty Access
```

### Fine-Grained Password Policies (FGPP)

Override domain-default password policy for specific groups (domain functional level 2008+):

```powershell
# Create a strict policy for admin accounts
New-ADFineGrainedPasswordPolicy -Name "Admin-Password-Policy" `
    -Precedence 10 `
    -MinPasswordLength 16 `
    -PasswordHistoryCount 24 `
    -MaxPasswordAge 60.00:00:00 `
    -MinPasswordAge 1.00:00:00 `
    -ComplexityEnabled $true `
    -ReversibleEncryptionEnabled $false `
    -LockoutThreshold 5 `
    -LockoutDuration 00:30:00 `
    -LockoutObservationWindow 00:30:00

# Apply to a group
Add-ADFineGrainedPasswordPolicySubject -Identity "Admin-Password-Policy" `
    -Subjects "Domain Admins","Enterprise Admins"

# Check which policy applies to a user
Get-ADUserResultantPasswordPolicy -Identity "admin-jsmith"
```

### Privileged Access Workstations (PAW)

Dedicated workstations for Tier 0 and Tier 1 administration. PAWs are hardened, tightly controlled, and used exclusively for privileged tasks — no email, web browsing, or general productivity.

Key requirements:
- Clean OS install (not upgraded from standard image)
- Hardware TPM 2.0, Secure Boot, Credential Guard enabled
- Restricted internet access (only to management endpoints)
- No standard user accounts — only privileged admin accounts
- Device guard / application control (WDAC) — only approved binaries run
- Dedicated network segment or VLAN with restricted firewall rules
- Enrolled in Intune or SCCM with strict compliance policies

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Nesting security groups more than 3 levels deep | "Account Operators > IT Staff > Server Admins > DB Admins" — troubleshooting permissions becomes impossible; token bloat causes auth failures | Keep nesting to 2 levels maximum; use direct group membership; document group hierarchy |
| Placing user accounts directly in default containers (CN=Users) | No GPO application; cannot apply fine-grained policies; accounts miss security baselines | Create OU structure by function/location; move accounts to appropriate OUs; apply GPOs at OU level |
| Not monitoring FSMO role holders | If the PDC emulator fails, password changes stop; if Schema Master fails, schema updates block | Monitor all 5 FSMO roles; document which DC holds each role; test role seizure procedure annually |
| Single Domain Controller for a domain | DC failure means complete authentication outage; no redundancy for DNS, LDAP, or Kerberos | Minimum 2 DCs per domain; 2 per site for sites with critical services; use Read-Only DCs for branch offices |
| Granting Domain Admin to service accounts | One compromised service account owns the entire domain; violates least privilege | Use gMSAs (Group Managed Service Accounts) with minimal permissions; delegate only needed rights |

---

## Related Skills

| Topic | Skill |
|---|---|
| PowerShell AD cmdlets (user/group/OU/GPO management) | `windows-ps-server-admin` |
| SSO, federation, AD FS, Kerberos delegation | `windows-sso` |
| Security hardening (firewall, Defender, BitLocker, auditing) | `windows-ps-security` |
| PowerShell scripting fundamentals | `windows-powershell` |
| CMD batch scripting and system commands | `windows-cmd` |
| Centrify/Delinea AD integration for Linux | `linux-centrify` |
| Docker with AD/Centrify user mapping | `docker-admin` |
