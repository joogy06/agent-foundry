---
name: windows-ps-server-admin
description: Use when administering Windows Server via PowerShell — Active Directory (users, groups, OUs, GPO), DNS Server, DHCP Server, IIS/web hosting, Hyper-V VM management, Windows Server Update Services (WSUS), file server/shares (SMB), Print Server, Certificate Services, and server roles/features installation. Part of the windows-ps-* skill family.
---

# Windows Server Administration via PowerShell

Companion skill to `windows-powershell` (parent) covering Windows Server roles and features managed through PowerShell. Targets Windows Server 2019/2022/2025. For security-specific topics (Windows Firewall, BitLocker, Defender, auditing), see `windows-ps-security`.

<HARD-RULE>
Always confirm the Windows Server version before applying advice. Cmdlets, module availability, and feature names vary between Server editions and versions.
```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber
[System.Environment]::OSVersion
Get-WindowsFeature | Where-Object Installed
```
</HARD-RULE>

<HARD-RULE>
Never run destructive Active Directory commands (Remove-ADUser, Remove-ADOrganizationalUnit, Remove-ADGroup, Remove-ADComputer) without explicit user confirmation. Always verify the target object with Get-AD* first. AD deletions can cascade and are difficult to reverse without authoritative restores.
</HARD-RULE>

<HARD-RULE>
Always run PowerShell as Administrator (elevated session) for server role management. Most Server cmdlets require elevation and will silently fail or throw access-denied errors without it.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [iis-hyperv-storage-certs-monitoring.md](iis-hyperv-storage-certs-monitoring.md) | IIS web server, Hyper-V VM management, file server/SMB, WSUS, Certificate Services, and server monitoring |
| [roles-ad-dns-dhcp.md](roles-ad-dns-dhcp.md) | server roles/features, Active Directory administration, Group Policy, DNS Server, and DHCP Server |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `Set-ADUser` in a loop instead of bulk operations | One LDAP call per user; 1000 users = 1000 network round trips; takes minutes instead of seconds | Use pipeline: `Get-ADUser -Filter ... | Set-ADUser -Property value`; or use LDIFDE for bulk imports |
| Managing GPOs without version control | No rollback capability; conflicting edits between admins; no audit trail for changes | Export GPOs to XML backup before changes; store in git; document every GPO change with business justification |
| Not testing GPO changes in a lab OU first | A bad GPO applied to production OUs can lock out users, break applications, or disable services domain-wide | Create a test OU with representative test accounts/computers; apply and validate GPO there first; then link to production |
| Using local admin accounts instead of gMSAs for services | Password rotation is manual; shared passwords get leaked; no accountability for service account usage | Use Group Managed Service Accounts (gMSAs); automatic password rotation; tied to specific computer accounts |
| Disabling Windows Firewall instead of creating proper rules | Exposes all services to the network; violates CIS benchmarks; lateral movement becomes trivial for attackers | Create specific inbound rules for required services; use Group Policy to enforce firewall state; log dropped traffic |

---

## Related Skills

| Scope | Skill |
|---|---|
| PowerShell fundamentals (parent) | `windows-powershell` |
| Windows security (firewall, BitLocker, Defender, auditing) | `windows-ps-security` |
| CMD / batch scripting | `windows-cmd` |
