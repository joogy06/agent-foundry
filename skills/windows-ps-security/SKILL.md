---
name: windows-ps-security
description: Use when hardening Windows systems via PowerShell — Windows Firewall (NetSecurity), Windows Defender/Microsoft Defender, BitLocker drive encryption, audit policy and event log analysis, local security policy, credential management (SecureString, Windows Credential Manager), AppLocker, Windows Update management, and security compliance scanning. Part of the windows-ps-* skill family.
family: windows
---

# Windows Security Administration via PowerShell

Companion skill to `windows-powershell` (parent). Focused on security hardening, compliance, and threat mitigation on Windows 10/11 and Windows Server 2019/2022/2025.

<HARD-RULE>
FIREWALL LOCKOUT PREVENTION: Never disable all firewall profiles or remove all inbound rules on a remote system without first ensuring an allow rule exists for your management port (RDP 3389, WinRM 5985/5986, or SSH 22). Always test firewall changes on a single machine before deploying broadly. Use `-WhatIf` before applying destructive rule changes.
```powershell
# ALWAYS verify management access rule exists before bulk changes
Get-NetFirewallRule -DisplayName "*Remote Desktop*" | Get-NetFirewallPortFilter
Get-NetFirewallRule -DisplayName "*WinRM*" | Get-NetFirewallPortFilter
```
</HARD-RULE>

<HARD-RULE>
BITLOCKER RECOVERY KEY BACKUP: Always back up BitLocker recovery keys to Active Directory, Azure AD, or a secure file BEFORE enabling encryption. A lost recovery key means permanent data loss if the TPM is cleared or the drive is moved to another machine.
```powershell
# Back up recovery key BEFORE encrypting
$BLV = Get-BitLockerVolume -MountPoint "C:"
Backup-BitLockerKeyProtector -MountPoint "C:" -KeyProtectorId $BLV.KeyProtector[1].KeyProtectorId
# Also export to file as secondary backup
(Get-BitLockerVolume -MountPoint "C:").KeyProtector | Where-Object { $_.KeyProtectorType -eq 'RecoveryPassword' } |
    Select-Object -ExpandProperty RecoveryPassword | Out-File "\\SecureShare\BitLockerKeys\$env:COMPUTERNAME.txt"
```
</HARD-RULE>

<HARD-RULE>
CREDENTIAL STORAGE SAFETY: Never store passwords in plain text in scripts. Use `ConvertTo-SecureString`, `Export-Clixml`, or Windows Credential Manager. SecureString encrypted with `Export-Clixml` is tied to the user AND machine that created it — it cannot be decrypted by another user or on another machine. Never commit credential files to version control.
```powershell
# CORRECT: Secure credential storage
$cred = Get-Credential
$cred | Export-Clixml -Path "$env:USERPROFILE\safe-cred.xml"
# WRONG: Plain text password in script (NEVER do this)
# $password = "MyP@ssw0rd!"   # <-- NEVER
```
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [credentials-applocker-compliance.md](credentials-applocker-compliance.md) | credential management, AppLocker, local security policy, Windows Update management, security compliance, network security, user account security, and the quick security audit script |
| [firewall-defender-bitlocker-audit.md](firewall-defender-bitlocker-audit.md) | Windows Firewall (NetSecurity), Windows Defender/Microsoft Defender, BitLocker drive encryption, and audit policy/event log analysis |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Disabling UAC or Windows Defender for "convenience" | Removes primary defense layers; malware runs with full privileges; fails every security audit | Configure exclusions for specific paths/processes; use GPO to manage settings rather than disabling wholesale |
| Storing passwords in scripts as plain text | Scripts in SCM, shared drives, or backup tapes expose credentials; single compromise escalates to domain admin | Use `Get-Credential`, `SecureString`, or external vaults (Azure Key Vault, CyberArk); never hardcode credentials |
| Not enabling PowerShell ScriptBlock logging | No visibility into what scripts execute; incident response has no forensic trail; attackers operate undetected | Enable ScriptBlock and Module logging via GPO; forward to SIEM; essential for detecting encoded/obfuscated attacks |
| Using NTLM authentication instead of Kerberos | NTLM is vulnerable to relay attacks, pass-the-hash, and brute force; cannot use modern security features | Restrict NTLM via GPO (Network security: Restrict NTLM); audit NTLM usage first, then block progressively |
| Running PowerShell remoting without JEA (Just Enough Administration) | Full administrative sessions over WinRM; any command can be executed; no command-level access control | Configure JEA endpoints with role capabilities; limit available cmdlets and parameters per role |

---

## Related Skills

| Skill | Scope |
|---|---|
| `windows-powershell` | Parent skill — core PowerShell syntax, modules, remoting, scripting patterns |
| `windows-ps-server-admin` | Windows Server roles (AD DS, DNS, DHCP, IIS, Hyper-V, clustering) |
| `windows-cmd` | Legacy CMD commands, batch scripting, low-level system tools |
