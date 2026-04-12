# Credentials, AppLocker, Security Policy, Updates, Compliance, and Network Security

Reference file for the `windows-ps-security` skill. Covers credential management, AppLocker, local security policy, Windows Update management, security compliance, network security, user account security, and the quick security audit script.

## 6. AppLocker

### View AppLocker Policy

```powershell
# Get current AppLocker policy
Get-AppLockerPolicy -Effective | Select-Object -ExpandProperty RuleCollections

# Get policy in XML format
Get-AppLockerPolicy -Effective -Xml | Out-File "C:\Backup\applocker-policy.xml"

# Get local policy
Get-AppLockerPolicy -Local | Select-Object -ExpandProperty RuleCollections

# Check AppLocker service status
Get-Service AppIDSvc | Select-Object Status, StartType
Set-Service AppIDSvc -StartupType Automatic
Start-Service AppIDSvc
```

### Create AppLocker Rules

```powershell
# Generate default rules (ALWAYS create default rules first to avoid lockout)
$defaultRules = Get-ChildItem -Path "C:\Windows" -File -Recurse -Include *.exe -ErrorAction SilentlyContinue |
    Get-AppLockerFileInformation |
    New-AppLockerPolicy -RuleType Publisher,Hash -User Everyone -Optimize

# Create publisher-based rule (recommended — survives updates)
$fileInfo = Get-AppLockerFileInformation -Path "C:\Program Files\App\app.exe"
$rule = $fileInfo | New-AppLockerPolicy -RuleType Publisher -User "Domain\AllowedGroup"

# Create path-based rule
$policy = New-AppLockerPolicy -RuleType Path `
    -FileInformation (Get-AppLockerFileInformation -Path "C:\ApprovedApps\*") `
    -User Everyone

# Set policy locally
Set-AppLockerPolicy -PolicyObject $policy -Merge

# Set enforcement mode (Enforce or AuditOnly)
$policy = Get-AppLockerPolicy -Local
$policy.RuleCollections | ForEach-Object { $_.EnforcementMode = "AuditOnly" }
Set-AppLockerPolicy -PolicyObject $policy
```

### Test AppLocker Policy

```powershell
# Test if an app would be allowed
Test-AppLockerPolicy -Path "C:\Users\user\Downloads\setup.exe" `
    -User "DOMAIN\JohnDoe" -PolicyObject (Get-AppLockerPolicy -Effective)

# Test multiple files
Get-ChildItem "C:\Users\user\Downloads\*.exe" |
    Test-AppLockerPolicy -User "DOMAIN\JohnDoe" `
    -PolicyObject (Get-AppLockerPolicy -Effective) |
    Format-Table Path, PolicyDecision

# View AppLocker event log for blocked applications
Get-WinEvent -LogName "Microsoft-Windows-AppLocker/EXE and DLL" -MaxEvents 20 |
    Select-Object TimeCreated, Message
```

---

## 7. Local Security Policy

### Export and Analyze Security Settings

```powershell
# Export current security policy to INF file
secedit /export /cfg C:\Backup\secpolicy.inf /areas SECURITYPOLICY

# Export all areas
secedit /export /cfg C:\Backup\secpolicy-full.inf

# View the exported policy
Get-Content C:\Backup\secpolicy.inf
```

### Password Policy

```powershell
# View current password policy
net accounts

# Set password policy via secedit template
# Create security template INF:
$policyContent = @"
[Unicode]
Unicode=yes
[System Access]
MinimumPasswordAge = 1
MaximumPasswordAge = 90
MinimumPasswordLength = 14
PasswordComplexity = 1
PasswordHistorySize = 24
LockoutBadCount = 5
ResetLockoutCount = 30
LockoutDuration = 30
[Version]
signature="`$CHICAGO`$"
Revision=1
"@
$policyContent | Out-File -FilePath "C:\Temp\password-policy.inf" -Encoding Unicode

# Apply security template
secedit /configure /db C:\Temp\secpolicy.sdb /cfg C:\Temp\password-policy.inf /areas SECURITYPOLICY

# Verify changes
net accounts
```

### User Rights Assignments

```powershell
# Export user rights assignments
secedit /export /cfg C:\Temp\userrights.inf /areas USER_RIGHTS

# View who has specific rights
$policy = Get-Content C:\Temp\userrights.inf
$policy | Select-String "SeRemoteInteractiveLogonRight"   # RDP logon
$policy | Select-String "SeServiceLogonRight"              # Log on as service
$policy | Select-String "SeBatchLogonRight"                # Log on as batch
$policy | Select-String "SeDenyNetworkLogonRight"          # Deny network logon
$policy | Select-String "SeDebugPrivilege"                 # Debug programs

# Grant user right via ntrights (from Resource Kit) or secpol.msc
# PowerShell alternative: use carbon module
Install-Module -Name Carbon -Force -AllowClobber
Grant-CPrivilege -Identity "DOMAIN\SvcAccount" -Privilege SeServiceLogonRight
```

### Restricted Groups and Account Policies

```powershell
# View local Administrators group membership
Get-LocalGroupMember -Group "Administrators"

# Remove unauthorized admin
Remove-LocalGroupMember -Group "Administrators" -Member "DOMAIN\UnauthorizedUser"

# View all local groups and members
Get-LocalGroup | ForEach-Object {
    $group = $_.Name
    Get-LocalGroupMember -Group $group -ErrorAction SilentlyContinue | ForEach-Object {
        [PSCustomObject]@{
            Group      = $group
            Member     = $_.Name
            ObjectClass = $_.ObjectClass
            Source     = $_.PrincipalSource
        }
    }
} | Format-Table -AutoSize
```

---

## 8. Windows Update Management

### PSWindowsUpdate Module

```powershell
# Install PSWindowsUpdate module
Install-Module -Name PSWindowsUpdate -Force

# List available updates
Get-WindowsUpdate

# List available updates with details
Get-WindowsUpdate -MicrosoftUpdate | Format-Table Title, KB, Size, IsDownloaded, IsInstalled

# Install all available updates
Install-WindowsUpdate -MicrosoftUpdate -AcceptAll -AutoReboot

# Install specific KB
Install-WindowsUpdate -KBArticleID "KB5034441" -AcceptAll

# Install updates without auto-reboot
Install-WindowsUpdate -MicrosoftUpdate -AcceptAll -IgnoreReboot

# Hide/decline an update
Hide-WindowsUpdate -KBArticleID "KB1234567"

# View update history
Get-WUHistory | Select-Object -First 20 Title, Date, Result, KB

# Uninstall an update
Remove-WindowsUpdate -KBArticleID "KB5034441" -NoRestart
```

### WSUS Client Configuration

```powershell
# Configure WSUS server via registry
$wsusPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
$auPath = "$wsusPath\AU"

New-Item -Path $wsusPath -Force
New-Item -Path $auPath -Force

# Set WSUS server URL
Set-ItemProperty -Path $wsusPath -Name "WUServer" -Value "https://wsus.domain.com:8531"
Set-ItemProperty -Path $wsusPath -Name "WUStatusServer" -Value "https://wsus.domain.com:8531"

# Configure auto-update behavior
# 2 = Notify, 3 = Auto download + notify, 4 = Auto download + install
Set-ItemProperty -Path $auPath -Name "UseWUServer" -Value 1
Set-ItemProperty -Path $auPath -Name "AUOptions" -Value 3
Set-ItemProperty -Path $auPath -Name "NoAutoUpdate" -Value 0
Set-ItemProperty -Path $auPath -Name "ScheduledInstallDay" -Value 0    # 0=Every day
Set-ItemProperty -Path $auPath -Name "ScheduledInstallTime" -Value 3   # 3 AM

# Force Windows Update detection
wuauclt /detectnow
(New-Object -ComObject Microsoft.Update.AutoUpdate).DetectNow()

# Report Windows Update client to WSUS
wuauclt /reportnow

# Check Windows Update service status
Get-Service wuauserv | Select-Object Status, StartType
```

### Remote Update Management

```powershell
# Install PSWindowsUpdate on remote machines
Install-WindowsUpdate -ComputerName Server01, Server02 `
    -MicrosoftUpdate -AcceptAll -IgnoreReboot -Credential $cred

# Get update status across multiple servers
$servers = @("Server01", "Server02", "Server03")
$servers | ForEach-Object {
    Invoke-Command -ComputerName $_ -ScriptBlock {
        Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 5
    } -Credential $cred
} | Format-Table PSComputerName, HotFixID, InstalledOn, Description
```

---

## 9. Security Compliance

### Microsoft Security Baselines

```powershell
# Download and apply security baselines using LGPO.exe
# (Part of Microsoft Security Compliance Toolkit)

# Apply GPO backup to local policy
# LGPO.exe must be downloaded from Microsoft
& "C:\Tools\LGPO.exe" /g "C:\Baselines\Win11-23H2-Security\GPOs\{GUID}"

# Export current local policy for comparison
& "C:\Tools\LGPO.exe" /b "C:\Backup\CurrentPolicy"

# Parse GPO backup to readable text
& "C:\Tools\LGPO.exe" /parse /m "C:\Baselines\Win11-23H2-Security\GPOs\{GUID}\DomainSysvol\GPO\Machine\registry.pol"
```

### DSC for Security Compliance

```powershell
# Install required DSC modules
Install-Module -Name SecurityPolicyDsc -Force
Install-Module -Name AuditPolicyDsc -Force
Install-Module -Name NetworkingDsc -Force

# Example DSC configuration for security baseline
Configuration SecurityBaseline {
    Import-DscResource -ModuleName SecurityPolicyDsc
    Import-DscResource -ModuleName AuditPolicyDsc

    Node 'localhost' {
        AccountPolicy AccountPolicies {
            Name                                        = 'AccountPolicies'
            Minimum_Password_Length                      = 14
            Maximum_Password_Age                         = 90
            Minimum_Password_Age                         = 1
            Enforce_password_history                     = 24
            Password_must_meet_complexity_requirements   = 'Enabled'
            Account_lockout_threshold                    = 5
            Account_lockout_duration                     = 30
            Reset_account_lockout_counter_after          = 30
        }

        AuditPolicySubcategory LogonAudit {
            Name      = 'Logon'
            AuditFlag = 'Success'
            Ensure    = 'Present'
        }

        AuditPolicySubcategory LogonFailureAudit {
            Name      = 'Logon'
            AuditFlag = 'Failure'
            Ensure    = 'Present'
        }
    }
}

# Compile and apply
SecurityBaseline -OutputPath "C:\DSC\SecurityBaseline"
Start-DscConfiguration -Path "C:\DSC\SecurityBaseline" -Wait -Verbose -Force

# Check compliance
Test-DscConfiguration -Detailed
```

### CIS Benchmark Automation

```powershell
# Automated CIS benchmark checks (sample)
$results = @()

# CIS 1.1.1 — Minimum password length >= 14
$passPolicy = net accounts | Select-String "Minimum password length"
$minLength = [int]($passPolicy -replace '\D','')
$results += [PSCustomObject]@{
    Control  = "CIS 1.1.1"
    Setting  = "Minimum password length"
    Expected = "14"
    Actual   = $minLength
    Status   = if ($minLength -ge 14) { "PASS" } else { "FAIL" }
}

# CIS 2.3.1.1 — Guest account disabled
$guest = Get-LocalUser -Name "Guest" -ErrorAction SilentlyContinue
$results += [PSCustomObject]@{
    Control  = "CIS 2.3.1.1"
    Setting  = "Guest account disabled"
    Expected = "True"
    Actual   = (-not $guest.Enabled)
    Status   = if (-not $guest.Enabled) { "PASS" } else { "FAIL" }
}

# CIS 9.1.1 — Windows Firewall Domain profile enabled
$fwDomain = (Get-NetFirewallProfile -Profile Domain).Enabled
$results += [PSCustomObject]@{
    Control  = "CIS 9.1.1"
    Setting  = "Domain firewall enabled"
    Expected = "True"
    Actual   = $fwDomain
    Status   = if ($fwDomain) { "PASS" } else { "FAIL" }
}

# CIS 18.9.47.1 — Windows Defender real-time protection
$rtProtection = (Get-MpPreference).DisableRealtimeMonitoring
$results += [PSCustomObject]@{
    Control  = "CIS 18.9.47.1"
    Setting  = "Real-time protection enabled"
    Expected = "False"
    Actual   = $rtProtection
    Status   = if (-not $rtProtection) { "PASS" } else { "FAIL" }
}

# Output results
$results | Format-Table -AutoSize
$results | Export-Csv "C:\Compliance\CIS-results-$(Get-Date -Format 'yyyyMMdd').csv" -NoTypeInformation
```

---

## 10. Network Security

### TLS/SSL Configuration

```powershell
# View current TLS cipher suites
Get-TlsCipherSuite | Format-Table Name, CipherBlockLength, CipherLength, KeyExchangeAlgorithm

# Disable weak cipher suites
Disable-TlsCipherSuite -Name "TLS_RSA_WITH_3DES_EDE_CBC_SHA"
Disable-TlsCipherSuite -Name "TLS_RSA_WITH_RC4_128_SHA"
Disable-TlsCipherSuite -Name "TLS_RSA_WITH_NULL_SHA256"

# Enable strong cipher suite
Enable-TlsCipherSuite -Name "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384" -Position 0

# Disable TLS 1.0 and 1.1 via registry
$tlsVersions = @("TLS 1.0", "TLS 1.1")
foreach ($ver in $tlsVersions) {
    $serverPath = "HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\$ver\Server"
    $clientPath = "HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\$ver\Client"
    New-Item -Path $serverPath -Force
    New-Item -Path $clientPath -Force
    Set-ItemProperty -Path $serverPath -Name "Enabled" -Value 0 -Type DWord
    Set-ItemProperty -Path $serverPath -Name "DisabledByDefault" -Value 1 -Type DWord
    Set-ItemProperty -Path $clientPath -Name "Enabled" -Value 0 -Type DWord
    Set-ItemProperty -Path $clientPath -Name "DisabledByDefault" -Value 1 -Type DWord
}

# Enable TLS 1.2 and 1.3 explicitly
foreach ($ver in @("TLS 1.2", "TLS 1.3")) {
    $serverPath = "HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\$ver\Server"
    $clientPath = "HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\$ver\Client"
    New-Item -Path $serverPath -Force
    New-Item -Path $clientPath -Force
    Set-ItemProperty -Path $serverPath -Name "Enabled" -Value 1 -Type DWord
    Set-ItemProperty -Path $serverPath -Name "DisabledByDefault" -Value 0 -Type DWord
    Set-ItemProperty -Path $clientPath -Name "Enabled" -Value 1 -Type DWord
    Set-ItemProperty -Path $clientPath -Name "DisabledByDefault" -Value 0 -Type DWord
}

# Disable SSL 2.0 and 3.0
foreach ($ver in @("SSL 2.0", "SSL 3.0")) {
    $serverPath = "HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\$ver\Server"
    New-Item -Path $serverPath -Force
    Set-ItemProperty -Path $serverPath -Name "Enabled" -Value 0 -Type DWord
}
```

### SMB Security

```powershell
# Enable SMB signing (required)
Set-SmbServerConfiguration -RequireSecuritySignature $true -Force
Set-SmbClientConfiguration -RequireSecuritySignature $true -Force

# Disable SMBv1 (critical security measure)
Disable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -NoRestart
Set-SmbServerConfiguration -EnableSMB1Protocol $false -Force

# Verify SMB versions in use
Get-SmbServerConfiguration | Select-Object EnableSMB1Protocol, EnableSMB2Protocol

# Enable SMB encryption
Set-SmbServerConfiguration -EncryptData $true -Force

# View active SMB sessions
Get-SmbSession | Select-Object ClientComputerName, ClientUserName, Dialect, NumOpens

# View SMB shares and their security
Get-SmbShare | Get-SmbShareAccess | Format-Table Name, AccountName, AccessControlType, AccessRight
```

### LDAP Signing and NTLMv2

```powershell
# Enforce LDAP signing via registry
$ldapPath = "HKLM:\SYSTEM\CurrentControlSet\Services\NTDS\Parameters"
Set-ItemProperty -Path $ldapPath -Name "LDAPServerIntegrity" -Value 2 -Type DWord
# 0 = None, 1 = Require if supported, 2 = Required

# Enforce LDAP client signing
$ldapClientPath = "HKLM:\SYSTEM\CurrentControlSet\Services\ldap"
Set-ItemProperty -Path $ldapClientPath -Name "LDAPClientIntegrity" -Value 2 -Type DWord

# Enforce NTLMv2 only (LmCompatibilityLevel = 5)
$lsaPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa"
Set-ItemProperty -Path $lsaPath -Name "LmCompatibilityLevel" -Value 5 -Type DWord
# 5 = Send NTLMv2 response only, refuse LM & NTLM

# Restrict NTLM authentication
Set-ItemProperty -Path $lsaPath -Name "RestrictSendingNTLMTraffic" -Value 2 -Type DWord
# Audit NTLM usage before restricting
Set-ItemProperty -Path "$lsaPath\MSV1_0" -Name "AuditReceivingNTLMTraffic" -Value 2 -Type DWord
```

---

## 11. User Account Security

### Local Administrator Password Solution (LAPS)

```powershell
# Check if LAPS is installed
Get-Command Get-LapsADPassword -ErrorAction SilentlyContinue

# Windows LAPS (built-in to Windows 11 22H2+ and Server 2025)
# View LAPS password for a computer
Get-LapsADPassword -Identity "WORKSTATION01" -AsPlainText

# Configure LAPS policy via registry (or GPO)
$lapsPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\LAPS"
New-Item -Path $lapsPath -Force
Set-ItemProperty -Path $lapsPath -Name "BackupDirectory" -Value 2 -Type DWord  # 2 = Active Directory
Set-ItemProperty -Path $lapsPath -Name "PasswordAgeDays" -Value 30 -Type DWord
Set-ItemProperty -Path $lapsPath -Name "PasswordLength" -Value 20 -Type DWord
Set-ItemProperty -Path $lapsPath -Name "PasswordComplexity" -Value 4 -Type DWord  # Large+small+numbers+specials

# Legacy LAPS module
Import-Module AdmPwd.PS
Get-AdmPwdPassword -ComputerName "WORKSTATION01"
Reset-AdmPwdPassword -ComputerName "WORKSTATION01"
```

### Service Account Management

```powershell
# List services running under non-default accounts
Get-CimInstance Win32_Service |
    Where-Object { $_.StartName -notin @("LocalSystem", "NT AUTHORITY\LocalService",
        "NT AUTHORITY\NetworkService", "NT Authority\LocalService", "LocalSystem") } |
    Select-Object Name, DisplayName, StartName, State | Format-Table -AutoSize

# Change service account
$svc = Get-CimInstance Win32_Service -Filter "Name='MyService'"
$svc | Invoke-CimMethod -MethodName Change -Arguments @{
    StartName     = "DOMAIN\SvcAccount"
    StartPassword = "NewP@ssw0rd"
}

# Audit service account permissions
Get-CimInstance Win32_Service | ForEach-Object {
    $acl = sc.exe sdshow $_.Name 2>$null
    [PSCustomObject]@{
        Service = $_.Name
        Account = $_.StartName
        SDDL    = $acl
    }
} | Where-Object { $_.Account -notmatch "^(LocalSystem|NT AUTHORITY)" }
```

### Group Managed Service Accounts (gMSA)

```powershell
# Create gMSA (requires AD DS PowerShell module on domain controller)
New-ADServiceAccount -Name "gMSA_WebApp" `
    -DNSHostName "gMSA_WebApp.domain.com" `
    -PrincipalsAllowedToRetrieveManagedPassword "WebServers_Group" `
    -KerberosEncryptionType AES128, AES256

# Install gMSA on target server
Install-ADServiceAccount -Identity "gMSA_WebApp"

# Test gMSA account
Test-ADServiceAccount -Identity "gMSA_WebApp"

# Use gMSA for a service
$svc = Get-CimInstance Win32_Service -Filter "Name='MyWebApp'"
$svc | Invoke-CimMethod -MethodName Change -Arguments @{
    StartName     = "DOMAIN\gMSA_WebApp$"
    StartPassword = ""
}
```

### Privileged Access Hardening

```powershell
# Enumerate local administrators across machines
$computers = Get-ADComputer -Filter * -SearchBase "OU=Servers,DC=domain,DC=com" | Select-Object -ExpandProperty Name
$computers | ForEach-Object {
    Invoke-Command -ComputerName $_ -ScriptBlock {
        Get-LocalGroupMember -Group "Administrators"
    } -ErrorAction SilentlyContinue
} | Select-Object PSComputerName, Name, ObjectClass | Format-Table

# Disable built-in Administrator account (use LAPS-managed password instead)
Disable-LocalUser -Name "Administrator"

# Rename built-in Administrator account (defense in depth)
Rename-LocalUser -Name "Administrator" -NewName "localadm_x7q2"

# Disable Guest account
Disable-LocalUser -Name "Guest"

# Set UAC to highest level via registry
$uacPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
Set-ItemProperty -Path $uacPath -Name "ConsentPromptBehaviorAdmin" -Value 2 -Type DWord  # Prompt on secure desktop
Set-ItemProperty -Path $uacPath -Name "EnableLUA" -Value 1 -Type DWord                    # UAC enabled
Set-ItemProperty -Path $uacPath -Name "PromptOnSecureDesktop" -Value 1 -Type DWord        # Secure desktop

# Require Ctrl+Alt+Del for logon
Set-ItemProperty -Path $uacPath -Name "DisableCAD" -Value 0 -Type DWord

# Deny logon for high-risk accounts across network
# (Apply via GPO: "Deny access to this computer from the network")
```

---

## Quick Security Audit Script

```powershell
# Comprehensive single-machine security posture check
function Get-SecurityPosture {
    $report = @()

    # OS version
    $os = Get-CimInstance Win32_OperatingSystem
    $report += "=== OS: $($os.Caption) Build $($os.BuildNumber) ==="

    # Firewall status
    $fw = Get-NetFirewallProfile | Select-Object Name, Enabled
    $report += "`n--- Firewall ---"
    $fw | ForEach-Object { $report += "  $($_.Name): Enabled=$($_.Enabled)" }

    # Defender status
    $def = Get-MpComputerStatus
    $report += "`n--- Windows Defender ---"
    $report += "  Real-time Protection: $($def.RealTimeProtectionEnabled)"
    $report += "  Signature Age: $((Get-Date) - $def.AntivirusSignatureLastUpdated | Select-Object -ExpandProperty Days) days"
    $report += "  Tamper Protection: $($def.IsTamperProtected)"

    # BitLocker
    $report += "`n--- BitLocker ---"
    Get-BitLockerVolume | ForEach-Object {
        $report += "  $($_.MountPoint): $($_.VolumeStatus) Protection=$($_.ProtectionStatus)"
    }

    # Password policy
    $report += "`n--- Password Policy ---"
    $report += (net accounts | Out-String).Trim()

    # Local admins
    $report += "`n--- Local Administrators ---"
    Get-LocalGroupMember -Group "Administrators" | ForEach-Object {
        $report += "  $($_.Name) ($($_.ObjectClass))"
    }

    # Listening ports
    $report += "`n--- Listening Ports (TCP) ---"
    Get-NetTCPConnection -State Listen |
        Sort-Object LocalPort |
        Select-Object LocalPort, OwningProcess,
            @{N='Process';E={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).Name}} |
        ForEach-Object { $report += "  :$($_.LocalPort) -> $($_.Process) (PID $($_.OwningProcess))" }

    # SMBv1 check
    $smb1 = (Get-SmbServerConfiguration).EnableSMB1Protocol
    $report += "`n--- SMB ---"
    $report += "  SMBv1 Enabled: $smb1 $(if ($smb1) {'[WARNING]'} else {'[OK]'})"

    # Recent failed logons
    $report += "`n--- Recent Failed Logons (last 24h) ---"
    try {
        $failed = Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625;StartTime=(Get-Date).AddHours(-24)} -MaxEvents 10 -ErrorAction Stop
        $failed | ForEach-Object {
            $report += "  $($_.TimeCreated) - User: $($_.Properties[5].Value) from $($_.Properties[19].Value)"
        }
    } catch {
        $report += "  No failed logons found (or insufficient permissions)"
    }

    $report -join "`n"
}

# Run and save report
Get-SecurityPosture | Tee-Object -FilePath "C:\SecurityAudit\posture-$(Get-Date -Format 'yyyyMMdd-HHmm').txt"
```

---

## Related Skills

| Skill | Scope |
|---|---|
| `windows-powershell` | Parent skill — core PowerShell syntax, modules, remoting, scripting patterns |
| `windows-ps-server-admin` | Windows Server roles (AD DS, DNS, DHCP, IIS, Hyper-V, clustering) |
| `windows-cmd` | Legacy CMD commands, batch scripting, low-level system tools |
