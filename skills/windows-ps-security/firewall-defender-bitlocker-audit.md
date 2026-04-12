# Firewall, Defender, BitLocker, and Audit Policy

Reference file for the `windows-ps-security` skill. Covers Windows Firewall (NetSecurity), Windows Defender/Microsoft Defender, BitLocker drive encryption, and audit policy/event log analysis.

## 1. Windows Firewall (NetSecurity)

### Check Firewall Status

```powershell
# All profiles status
Get-NetFirewallProfile | Format-Table Name, Enabled, DefaultInboundAction, DefaultOutboundAction, LogFileName

# Specific profile
Get-NetFirewallProfile -Profile Domain | Select-Object *

# List all active rules
Get-NetFirewallRule -Enabled True | Format-Table DisplayName, Direction, Action, Profile -AutoSize

# Count rules by direction and action
Get-NetFirewallRule -Enabled True | Group-Object Direction, Action | Select-Object Count, Name
```

### Enable / Disable Firewall

```powershell
# Enable all profiles (recommended)
Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True

# Set default actions — block inbound, allow outbound (standard hardening)
Set-NetFirewallProfile -Profile Domain,Private,Public `
    -DefaultInboundAction Block `
    -DefaultOutboundAction Allow

# Disable firewall for specific profile (use with caution)
Set-NetFirewallProfile -Profile Public -Enabled False
```

### Create Firewall Rules

```powershell
# Allow inbound on specific port (e.g., HTTPS)
New-NetFirewallRule -DisplayName "Allow HTTPS Inbound" `
    -Direction Inbound -Protocol TCP -LocalPort 443 `
    -Action Allow -Profile Domain,Private

# Block inbound from specific IP range
New-NetFirewallRule -DisplayName "Block Suspicious Network" `
    -Direction Inbound -RemoteAddress "10.99.0.0/16" `
    -Action Block -Profile Any

# Allow application through firewall
New-NetFirewallRule -DisplayName "Allow MyApp" `
    -Direction Inbound -Program "C:\Apps\myapp.exe" `
    -Action Allow -Profile Domain

# Allow outbound to specific destination
New-NetFirewallRule -DisplayName "Allow SQL Outbound" `
    -Direction Outbound -Protocol TCP -RemotePort 1433 `
    -RemoteAddress "10.0.1.50" -Action Allow

# Allow ICMPv4 (ping)
New-NetFirewallRule -DisplayName "Allow ICMPv4-In" `
    -Protocol ICMPv4 -IcmpType 8 -Direction Inbound -Action Allow

# Allow RDP only from management subnet
New-NetFirewallRule -DisplayName "RDP - Mgmt Subnet Only" `
    -Direction Inbound -Protocol TCP -LocalPort 3389 `
    -RemoteAddress "10.0.100.0/24" -Action Allow -Profile Domain,Private
```

### Modify and Remove Rules

```powershell
# Disable a rule (not remove)
Set-NetFirewallRule -DisplayName "Allow HTTPS Inbound" -Enabled False

# Change rule action
Set-NetFirewallRule -DisplayName "Allow HTTPS Inbound" -Action Block

# Remove a rule
Remove-NetFirewallRule -DisplayName "Block Suspicious Network"

# Remove all rules matching a pattern (use -WhatIf first!)
Remove-NetFirewallRule -DisplayName "Temp*" -WhatIf
Remove-NetFirewallRule -DisplayName "Temp*"
```

### Firewall Logging

```powershell
# Enable logging for dropped packets and successful connections
Set-NetFirewallProfile -Profile Domain,Private,Public `
    -LogAllowed True -LogBlocked True `
    -LogFileName "%SystemRoot%\System32\LogFiles\Firewall\pfirewall.log" `
    -LogMaxSizeKilobytes 16384

# Read firewall log
Get-Content "$env:SystemRoot\System32\LogFiles\Firewall\pfirewall.log" -Tail 50

# Parse firewall log for dropped connections
Select-String -Path "$env:SystemRoot\System32\LogFiles\Firewall\pfirewall.log" `
    -Pattern "DROP" | Select-Object -Last 20
```

### Export / Import Rules

```powershell
# Export all rules to file
netsh advfirewall export "C:\Backup\firewall-policy.wfw"

# Import rules from file
netsh advfirewall import "C:\Backup\firewall-policy.wfw"

# Export rules to CSV for review
Get-NetFirewallRule -Enabled True | Select-Object DisplayName, Direction, Action, Profile |
    Export-Csv -Path "C:\Backup\firewall-rules.csv" -NoTypeInformation
```

---

## 2. Windows Defender / Microsoft Defender

### Status and Configuration

```powershell
# Full status overview
Get-MpComputerStatus | Select-Object AntivirusEnabled, AntispywareEnabled,
    RealTimeProtectionEnabled, IoavProtectionEnabled, BehaviorMonitorEnabled,
    AntivirusSignatureLastUpdated, QuickScanEndTime, FullScanEndTime

# Check Defender service status
Get-Service -Name WinDefend | Select-Object Status, StartType

# View all Defender preferences
Get-MpPreference
```

### Signature Updates

```powershell
# Update signatures immediately
Update-MpSignature

# Update from specific source (UNC path, MMPC, etc.)
Update-MpSignature -UpdateSource MicrosoftUpdateServer

# Check signature age
$status = Get-MpComputerStatus
$daysSinceUpdate = (Get-Date) - $status.AntivirusSignatureLastUpdated
Write-Output "Signatures are $($daysSinceUpdate.Days) days old"
```

### Scanning

```powershell
# Quick scan
Start-MpScan -ScanType QuickScan

# Full scan
Start-MpScan -ScanType FullScan

# Custom scan on specific path
Start-MpScan -ScanType CustomScan -ScanPath "D:\Downloads"

# Offline scan (reboots system — WARNING)
Start-MpWDOScan
```

### Exclusions

```powershell
# Add path exclusion
Add-MpPreference -ExclusionPath "C:\DevTools"

# Add process exclusion
Add-MpPreference -ExclusionProcess "devenv.exe"

# Add extension exclusion
Add-MpPreference -ExclusionExtension ".log"

# View current exclusions
Get-MpPreference | Select-Object ExclusionPath, ExclusionProcess, ExclusionExtension

# Remove exclusion
Remove-MpPreference -ExclusionPath "C:\DevTools"
```

### Attack Surface Reduction (ASR) Rules

```powershell
# View current ASR rules
Get-MpPreference | Select-Object -ExpandProperty AttackSurfaceReductionRules_Ids
Get-MpPreference | Select-Object -ExpandProperty AttackSurfaceReductionRules_Actions

# Enable ASR rule (1 = Block, 2 = Audit, 6 = Warn)
# Block Office apps from creating child processes
Add-MpPreference -AttackSurfaceReductionRules_Ids "D4F940AB-401B-4EFC-AADC-AD5F3C50688A" `
    -AttackSurfaceReductionRules_Actions Enabled

# Block credential stealing from LSASS
Add-MpPreference -AttackSurfaceReductionRules_Ids "9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2" `
    -AttackSurfaceReductionRules_Actions Enabled

# Block executable content from email client and webmail
Add-MpPreference -AttackSurfaceReductionRules_Ids "BE9BA2D9-53EA-4CDC-84E5-9B1EEEE46550" `
    -AttackSurfaceReductionRules_Actions Enabled

# Set all ASR rules to Audit mode first (recommended before blocking)
# Key ASR Rule GUIDs:
# D4F940AB — Block Office child processes
# 3B576869 — Block Office from creating executable content
# 75668C1F — Block Office from injecting into other processes
# 9e6c4e1f — Block credential stealing from LSASS
# BE9BA2D9 — Block executable content from email
# D3E037E1 — Block JavaScript/VBScript launching executables
# 5BEB7EFE — Block execution of obfuscated scripts
# 92E97FA1 — Block Win32 API calls from Office macros
$asrRules = @(
    "D4F940AB-401B-4EFC-AADC-AD5F3C50688A",
    "3B576869-A4EC-4529-8536-B80A7769E899",
    "75668C1F-73B5-4CF0-BB93-3ECF5CB7CC84",
    "9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2",
    "BE9BA2D9-53EA-4CDC-84E5-9B1EEEE46550",
    "D3E037E1-3EB8-44C8-A917-57927947596D",
    "5BEB7EFE-FD9A-4556-801D-275E5FFC04CC",
    "92E97FA1-2EDF-4476-BDD6-9DD0B4DDDC7B"
)
foreach ($rule in $asrRules) {
    Add-MpPreference -AttackSurfaceReductionRules_Ids $rule `
        -AttackSurfaceReductionRules_Actions AuditMode
}
```

### Controlled Folder Access

```powershell
# Enable controlled folder access
Set-MpPreference -EnableControlledFolderAccess Enabled

# Add protected folder
Add-MpPreference -ControlledFolderAccessProtectedFolders "D:\CriticalData"

# Allow an app through controlled folder access
Add-MpPreference -ControlledFolderAccessAllowedApplications "C:\Apps\trusted.exe"

# Set to audit mode first
Set-MpPreference -EnableControlledFolderAccess AuditMode
```

### Tamper Protection Check

```powershell
# Check tamper protection status (cannot be changed via PowerShell — managed via Security Center / Intune)
Get-MpComputerStatus | Select-Object IsTamperProtected

# Check real-time protection
Get-MpPreference | Select-Object DisableRealtimeMonitoring
```

---

## 3. BitLocker Drive Encryption

### Check BitLocker Status

```powershell
# Status for all volumes
Get-BitLockerVolume | Format-Table MountPoint, VolumeStatus, EncryptionPercentage, ProtectionStatus, KeyProtector

# Detailed status for C: drive
Get-BitLockerVolume -MountPoint "C:" | Select-Object *

# Check TPM status
Get-Tpm | Select-Object TpmPresent, TpmReady, TpmEnabled, TpmActivated
```

### Enable BitLocker

```powershell
# Enable on OS drive with TPM protector and recovery password
Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 `
    -TpmProtector
Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector

# Enable on data drive with password protector
Enable-BitLocker -MountPoint "D:" -EncryptionMethod XtsAes256 `
    -PasswordProtector -Password (Read-Host -AsSecureString "Enter BitLocker password")

# Enable with TPM + PIN (enhanced security)
$pin = Read-Host -AsSecureString "Enter BitLocker PIN"
Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 `
    -TpmAndPinProtector -Pin $pin
Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector

# Encrypt used space only (faster, good for new drives)
Enable-BitLocker -MountPoint "D:" -EncryptionMethod XtsAes256 `
    -UsedSpaceOnly -RecoveryPasswordProtector
```

### Backup Recovery Keys

```powershell
# Back up recovery key to Active Directory
$BLV = Get-BitLockerVolume -MountPoint "C:"
foreach ($kp in $BLV.KeyProtector) {
    if ($kp.KeyProtectorType -eq 'RecoveryPassword') {
        Backup-BitLockerKeyProtector -MountPoint "C:" -KeyProtectorId $kp.KeyProtectorId
        Write-Output "Backed up: $($kp.RecoveryPassword)"
    }
}

# Back up recovery key to Azure AD
BackupToAAD-BitLockerKeyProtector -MountPoint "C:" `
    -KeyProtectorId (Get-BitLockerVolume -MountPoint "C:").KeyProtector[1].KeyProtectorId

# Export all recovery keys to file
Get-BitLockerVolume | ForEach-Object {
    $vol = $_
    $vol.KeyProtector | Where-Object { $_.KeyProtectorType -eq 'RecoveryPassword' } | ForEach-Object {
        [PSCustomObject]@{
            Computer   = $env:COMPUTERNAME
            MountPoint = $vol.MountPoint
            KeyId      = $_.KeyProtectorId
            RecoveryPw = $_.RecoveryPassword
        }
    }
} | Export-Csv -Path "\\SecureShare\BitLockerKeys\$env:COMPUTERNAME-keys.csv" -NoTypeInformation
```

### Manage BitLocker

```powershell
# Suspend BitLocker for updates/BIOS changes (auto-resumes after 1 reboot)
Suspend-BitLocker -MountPoint "C:" -RebootCount 1

# Resume BitLocker protection
Resume-BitLocker -MountPoint "C:"

# Lock a data drive
Lock-BitLocker -MountPoint "D:"

# Unlock a data drive
Unlock-BitLocker -MountPoint "D:" -Password (Read-Host -AsSecureString "Password")

# Unlock with recovery password
Unlock-BitLocker -MountPoint "D:" -RecoveryPassword "123456-789012-345678-901234-567890-123456-789012-345678"

# Disable BitLocker (decrypts the drive)
Disable-BitLocker -MountPoint "D:"

# Monitor encryption progress
Get-BitLockerVolume -MountPoint "C:" | Select-Object MountPoint, EncryptionPercentage, VolumeStatus
```

---

## 4. Audit Policy and Event Log Analysis

### View and Configure Audit Policies

```powershell
# View all audit policy settings
auditpol /get /category:*

# View specific category
auditpol /get /category:"Logon/Logoff"
auditpol /get /category:"Account Management"

# Enable logon auditing (success and failure)
auditpol /set /subcategory:"Logon" /success:enable /failure:enable

# Enable account management auditing
auditpol /set /subcategory:"User Account Management" /success:enable /failure:enable
auditpol /set /subcategory:"Security Group Management" /success:enable /failure:enable

# Enable object access auditing
auditpol /set /subcategory:"File System" /success:enable /failure:enable
auditpol /set /subcategory:"Registry" /success:enable /failure:enable

# Enable process tracking
auditpol /set /subcategory:"Process Creation" /success:enable /failure:enable

# Enable privilege use auditing
auditpol /set /subcategory:"Sensitive Privilege Use" /success:enable /failure:enable

# Backup audit policy
auditpol /backup /file:C:\Backup\audit-policy.csv

# Restore audit policy
auditpol /restore /file:C:\Backup\audit-policy.csv
```

### Key Security Event IDs

```powershell
# Event ID Reference:
# 4624  — Successful logon
# 4625  — Failed logon attempt
# 4634  — Logoff
# 4648  — Logon using explicit credentials (RunAs)
# 4672  — Special privileges assigned (admin logon)
# 4720  — User account created
# 4722  — User account enabled
# 4725  — User account disabled
# 4726  — User account deleted
# 4732  — Member added to security-enabled local group
# 4733  — Member removed from security-enabled local group
# 4740  — User account locked out
# 4756  — Member added to universal security group
# 4768  — Kerberos TGT requested
# 4769  — Kerberos service ticket requested
# 4771  — Kerberos pre-authentication failed
# 1102  — Security log cleared
# 7045  — New service installed

# Query successful logons in last 24 hours
Get-WinEvent -FilterHashtable @{
    LogName   = 'Security'
    Id        = 4624
    StartTime = (Get-Date).AddHours(-24)
} -MaxEvents 50 | Select-Object TimeCreated,
    @{N='User';E={$_.Properties[5].Value}},
    @{N='LogonType';E={$_.Properties[8].Value}},
    @{N='SourceIP';E={$_.Properties[18].Value}}

# Query failed logon attempts
Get-WinEvent -FilterHashtable @{
    LogName   = 'Security'
    Id        = 4625
    StartTime = (Get-Date).AddDays(-7)
} | Select-Object TimeCreated,
    @{N='TargetUser';E={$_.Properties[5].Value}},
    @{N='SourceIP';E={$_.Properties[19].Value}},
    @{N='FailureReason';E={$_.Properties[8].Value}} |
    Format-Table -AutoSize

# Detect account lockouts
Get-WinEvent -FilterHashtable @{
    LogName = 'Security'
    Id      = 4740
} -MaxEvents 20 | Select-Object TimeCreated,
    @{N='LockedAccount';E={$_.Properties[0].Value}},
    @{N='CallerComputer';E={$_.Properties[1].Value}}

# Detect new user creation
Get-WinEvent -FilterHashtable @{
    LogName   = 'Security'
    Id        = 4720
    StartTime = (Get-Date).AddDays(-30)
} | Select-Object TimeCreated,
    @{N='NewUser';E={$_.Properties[0].Value}},
    @{N='CreatedBy';E={$_.Properties[4].Value}}

# Detect group membership changes
Get-WinEvent -FilterHashtable @{
    LogName = 'Security'
    Id      = 4732
} -MaxEvents 20 | Select-Object TimeCreated,
    @{N='MemberAdded';E={$_.Properties[0].Value}},
    @{N='GroupName';E={$_.Properties[2].Value}},
    @{N='ChangedBy';E={$_.Properties[6].Value}}

# Detect explicit credential use (RunAs, lateral movement)
Get-WinEvent -FilterHashtable @{
    LogName = 'Security'
    Id      = 4648
} -MaxEvents 20 | Select-Object TimeCreated,
    @{N='SubjectUser';E={$_.Properties[1].Value}},
    @{N='TargetUser';E={$_.Properties[5].Value}},
    @{N='TargetServer';E={$_.Properties[9].Value}}

# Detect security log cleared (possible cover-up)
Get-WinEvent -FilterHashtable @{
    LogName = 'Security'
    Id      = 1102
} | Select-Object TimeCreated,
    @{N='ClearedBy';E={$_.Properties[1].Value}}
```

### Event Log Management

```powershell
# List security log size and retention
Get-WinEvent -ListLog Security | Select-Object LogName, MaximumSizeInBytes,
    RecordCount, FileSize, IsLogFull, LogMode

# Increase security log size (recommended: 1 GB+)
wevtutil sl Security /ms:1073741824

# Set log to overwrite as needed (vs archive)
wevtutil sl Security /rt:false

# Export security log to file
wevtutil epl Security C:\Backup\SecurityLog.evtx

# Clear security log (exports first)
wevtutil cl Security /bu:C:\Backup\SecurityLog-archive.evtx
```

---

## 5. Credential Management

### SecureString and PSCredential

```powershell
# Create credential interactively
$cred = Get-Credential -Message "Enter admin credentials" -UserName "DOMAIN\AdminUser"

# Create SecureString from plain text (for automation only — key-protected)
$secPw = ConvertTo-SecureString "tempSetupPassword" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("DOMAIN\User", $secPw)

# Save credential to encrypted XML (DPAPI — tied to user + machine)
$cred | Export-Clixml -Path "$env:USERPROFILE\savedcred.xml"

# Load saved credential
$cred = Import-Clixml -Path "$env:USERPROFILE\savedcred.xml"

# Use credential with remote commands
Invoke-Command -ComputerName Server01 -Credential $cred -ScriptBlock { whoami }
Enter-PSSession -ComputerName Server01 -Credential $cred
```

### SecureString with Encryption Key (Cross-Machine)

```powershell
# Generate a 256-bit AES key
$key = New-Object byte[] 32
[System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($key)
$key | Set-Content -Path "C:\SecureKeys\aes.key" -Encoding Byte

# Encrypt password with key (portable across machines)
$secPw = Read-Host -AsSecureString "Enter password"
$encrypted = ConvertFrom-SecureString -SecureString $secPw -Key (Get-Content "C:\SecureKeys\aes.key" -Encoding Byte)
$encrypted | Set-Content "C:\SecureKeys\encpw.txt"

# Decrypt on another machine (with same key file)
$key = Get-Content "C:\SecureKeys\aes.key" -Encoding Byte
$secPw = Get-Content "C:\SecureKeys\encpw.txt" | ConvertTo-SecureString -Key $key
$cred = New-Object PSCredential("DOMAIN\SvcAccount", $secPw)
```

### Windows Credential Manager

```powershell
# Store credential in Windows Credential Manager
cmdkey /add:Server01 /user:DOMAIN\AdminUser /pass:SecurePass123

# Store generic credential
cmdkey /generic:MyAppCredential /user:appuser /pass:apppass

# List stored credentials
cmdkey /list

# Delete stored credential
cmdkey /delete:Server01

# PowerShell module for Credential Manager (install from PSGallery)
Install-Module -Name CredentialManager -Force
New-StoredCredential -Target "MyService" -UserName "svc_account" `
    -Password "P@ssw0rd" -Type Generic -Persist LocalMachine
Get-StoredCredential -Target "MyService"
Remove-StoredCredential -Target "MyService"
```

### Certificate-Based Authentication

```powershell
# Create self-signed certificate for authentication
$cert = New-SelfSignedCertificate -Type Custom `
    -Subject "CN=PowerShellAuth" `
    -KeyUsage DigitalSignature `
    -KeyAlgorithm RSA -KeyLength 2048 `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -NotAfter (Get-Date).AddYears(2)

# Export certificate for distribution
Export-Certificate -Cert $cert -FilePath "C:\Certs\PSAuth.cer"

# Use certificate for WinRM authentication
$thumbprint = $cert.Thumbprint
Enter-PSSession -ComputerName Server01 -CertificateThumbprint $thumbprint

# Map certificate to user account for WinRM
$credential = Get-Credential
New-Item -Path WSMan:\localhost\ClientCertificate `
    -Subject "admin@domain.com" `
    -URI * `
    -Issuer $thumbprint `
    -Credential $credential -Force
```

---

