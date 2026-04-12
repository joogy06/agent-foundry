# IIS, Hyper-V, File Server, WSUS, Certificates, and Monitoring

Reference file for the `windows-ps-server-admin` skill. Covers IIS web server, Hyper-V VM management, file server/SMB, WSUS, Certificate Services, and server monitoring.

## 6. IIS (Web Server)

### Installation and Basic Setup

```powershell
# Install IIS with common sub-features
Install-WindowsFeature -Name Web-Server -IncludeAllSubFeature -IncludeManagementTools

# Or install specific sub-features
Install-WindowsFeature -Name Web-Server, Web-Asp-Net45, Web-Mgmt-Console,
    Web-Scripting-Tools, Web-Mgmt-Service

# Import IIS module
Import-Module WebAdministration
# Or the newer IISAdministration module (Server 2016+)
Import-Module IISAdministration
```

### Sites

```powershell
# List all sites
Get-Website
Get-IISSite   # IISAdministration module

# Create a new website
New-Website -Name "MyApp" `
    -PhysicalPath "C:\inetpub\myapp" `
    -Port 80 `
    -HostHeader "myapp.corp.example.com" `
    -ApplicationPool "MyAppPool"

# Stop / Start / Remove
Stop-Website -Name "MyApp"
Start-Website -Name "MyApp"
Remove-Website -Name "MyApp"

# Change binding
Set-WebBinding -Name "MyApp" -BindingInformation "*:80:myapp.corp.example.com" `
    -PropertyName Port -Value 8080
```

### SSL Binding

```powershell
# Import a PFX certificate
$certPassword = ConvertTo-SecureString "CertP@ss!" -AsPlainText -Force
Import-PfxCertificate -FilePath C:\Certs\myapp.pfx `
    -CertStoreLocation Cert:\LocalMachine\My `
    -Password $certPassword

# Get the certificate thumbprint
$cert = Get-ChildItem Cert:\LocalMachine\My |
    Where-Object { $_.Subject -like "*myapp.corp.example.com*" }

# Add HTTPS binding
New-WebBinding -Name "MyApp" -Protocol https -Port 443 `
    -HostHeader "myapp.corp.example.com" -SslFlags 1

# Bind the certificate
$binding = Get-WebBinding -Name "MyApp" -Protocol https
$binding.AddSslCertificate($cert.Thumbprint, "My")
```

### Application Pools

```powershell
# Create an application pool
New-WebAppPool -Name "MyAppPool"

# Configure the pool
Set-ItemProperty IIS:\AppPools\MyAppPool -Name managedRuntimeVersion -Value "v4.0"
Set-ItemProperty IIS:\AppPools\MyAppPool -Name processModel.identityType -Value "ApplicationPoolIdentity"
Set-ItemProperty IIS:\AppPools\MyAppPool -Name recycling.periodicRestart.time -Value "02:00:00"

# Start / Stop / Recycle
Start-WebAppPool -Name "MyAppPool"
Stop-WebAppPool -Name "MyAppPool"
Restart-WebAppPool -Name "MyAppPool"

# List all app pools
Get-ChildItem IIS:\AppPools
```

### Virtual Directories and Applications

```powershell
# Create a web application under an existing site
New-WebApplication -Name "api" -Site "MyApp" `
    -PhysicalPath "C:\inetpub\myapp\api" `
    -ApplicationPool "MyAppPool"

# Create a virtual directory
New-WebVirtualDirectory -Site "MyApp" -Name "docs" `
    -PhysicalPath "D:\SharedDocs"
```

### URL Rewrite (Requires URL Rewrite Module)

```powershell
# HTTP to HTTPS redirect via web.config
$webConfig = @"
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="HTTP to HTTPS" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTPS}" pattern="off" ignoreCase="true" />
          </conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@
$webConfig | Set-Content C:\inetpub\myapp\web.config
```

---

## 7. Hyper-V

### Installation

```powershell
Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart
```

### VM Creation and Management

```powershell
# Create a Generation 2 VM
New-VM -Name "WEB01" `
    -Generation 2 `
    -MemoryStartupBytes 4GB `
    -NewVHDPath "D:\Hyper-V\VHDs\WEB01.vhdx" `
    -NewVHDSizeBytes 60GB `
    -SwitchName "External-vSwitch"

# Configure VM settings
Set-VM -Name "WEB01" `
    -ProcessorCount 4 `
    -DynamicMemory `
    -MemoryMinimumBytes 2GB `
    -MemoryMaximumBytes 8GB `
    -AutomaticStartAction Start `
    -AutomaticStopAction ShutDown `
    -AutomaticStartDelay 30

# Attach an ISO for OS installation
Add-VMDvdDrive -VMName "WEB01" -Path "D:\ISOs\WindowsServer2022.iso"
Set-VMFirmware -VMName "WEB01" -FirstBootDevice (Get-VMDvdDrive -VMName "WEB01")

# Start / Stop / Restart
Start-VM -Name "WEB01"
Stop-VM -Name "WEB01"
Stop-VM -Name "WEB01" -TurnOff          # force power off
Restart-VM -Name "WEB01" -Force

# Get VM status
Get-VM
Get-VM -Name "WEB01" | Select-Object Name, State, CPUUsage, MemoryAssigned, Uptime
Get-VM | Where-Object { $_.State -eq "Running" }
```

### Virtual Hard Disks

```powershell
# Create a new VHD
New-VHD -Path "D:\Hyper-V\VHDs\Data01.vhdx" -SizeBytes 100GB -Dynamic
New-VHD -Path "D:\Hyper-V\VHDs\Data02.vhdx" -SizeBytes 50GB -Fixed

# Attach a VHD to a VM
Add-VMHardDiskDrive -VMName "WEB01" -Path "D:\Hyper-V\VHDs\Data01.vhdx"

# Resize a VHD
Resize-VHD -Path "D:\Hyper-V\VHDs\Data01.vhdx" -SizeBytes 200GB

# Get VHD info
Get-VHD -Path "D:\Hyper-V\VHDs\WEB01.vhdx"
```

### Virtual Switches

```powershell
# List existing switches
Get-VMSwitch

# External switch (bridged to physical NIC)
New-VMSwitch -Name "External-vSwitch" `
    -NetAdapterName "Ethernet" `
    -AllowManagementOS $true

# Internal switch (host <-> VMs only)
New-VMSwitch -Name "Internal-vSwitch" -SwitchType Internal

# Private switch (VMs only, no host)
New-VMSwitch -Name "Private-vSwitch" -SwitchType Private

# Connect VM to switch
Connect-VMNetworkAdapter -VMName "WEB01" -SwitchName "External-vSwitch"
```

### Checkpoints (Snapshots)

<HARD-RULE>
Checkpoints are NOT backups. They increase disk usage and degrade performance over time. Use checkpoints for short-term testing only. Remove checkpoints promptly after testing.
</HARD-RULE>

```powershell
# Create a checkpoint
Checkpoint-VM -Name "WEB01" -SnapshotName "Pre-Update"

# List checkpoints
Get-VMCheckpoint -VMName "WEB01"

# Restore to a checkpoint
Restore-VMCheckpoint -Name "Pre-Update" -VMName "WEB01" -Confirm:$false

# Remove a checkpoint
Remove-VMCheckpoint -VMName "WEB01" -Name "Pre-Update"

# Remove all checkpoints
Get-VMCheckpoint -VMName "WEB01" | Remove-VMCheckpoint
```

### Live Migration

```powershell
# Enable live migration
Enable-VMMigration
Set-VMMigrationNetwork -Subnet 10.0.1.0/24

# Move a VM to another host
Move-VM -Name "WEB01" -DestinationHost "HVHOST02" `
    -IncludeStorage `
    -DestinationStoragePath "D:\Hyper-V\VHDs"

# Move only the storage (storage migration)
Move-VMStorage -VMName "WEB01" -DestinationStoragePath "E:\Hyper-V\VHDs"
```

### VM Replication

```powershell
# Enable replication on the replica server
Set-VMReplicationServer -ReplicationEnabled $true `
    -AllowedAuthenticationType Kerberos `
    -DefaultStorageLocation "D:\Hyper-V\Replicas"

# Enable replication for a VM
Enable-VMReplication -VMName "WEB01" `
    -ReplicaServerName "HVHOST02.corp.example.com" `
    -ReplicaServerPort 80 `
    -AuthenticationType Kerberos `
    -RecoveryHistory 4 `
    -ReplicationFrequencySec 300

# Start initial replication
Start-VMInitialReplication -VMName "WEB01"

# Check replication health
Get-VMReplication | Select-Object VMName, State, Health, LastReplicationTime
Measure-VMReplication -VMName "WEB01"
```

---

## 8. File Server / SMB

### SMB Shares

```powershell
# Install File Server role (usually already installed)
Install-WindowsFeature -Name FS-FileServer

# Create a new SMB share
New-SmbShare -Name "SharedDocs" `
    -Path "D:\Shares\Documents" `
    -Description "Shared documents" `
    -FullAccess "CORP\IT-Admins" `
    -ChangeAccess "CORP\All-Staff" `
    -ReadAccess "CORP\Contractors"

# List shares
Get-SmbShare
Get-SmbShare -Name "SharedDocs"

# Modify share permissions
Grant-SmbShareAccess -Name "SharedDocs" -AccountName "CORP\HR" -AccessRight Change -Force
Revoke-SmbShareAccess -Name "SharedDocs" -AccountName "CORP\Contractors" -Force

# Get current share permissions
Get-SmbShareAccess -Name "SharedDocs"

# View current sessions and open files
Get-SmbSession
Get-SmbOpenFile

# Close a specific open file
Close-SmbOpenFile -FileId <id> -Force

# Remove a share
Remove-SmbShare -Name "OldShare" -Force
```

### NTFS Permissions (icacls)

```powershell
# View current permissions
icacls "D:\Shares\Documents"

# Grant full control
icacls "D:\Shares\Documents" /grant "CORP\IT-Admins:(OI)(CI)F"

# Grant modify (read, write, modify, delete)
icacls "D:\Shares\Documents" /grant "CORP\All-Staff:(OI)(CI)M"

# Grant read-only
icacls "D:\Shares\Documents" /grant "CORP\Contractors:(OI)(CI)R"

# Remove permissions
icacls "D:\Shares\Documents" /remove "CORP\TempUser"

# Reset inheritance
icacls "D:\Shares\Documents" /reset /T /C

# Disable inheritance and copy existing permissions
icacls "D:\Shares\Documents" /inheritance:d

# Permission flags reference:
# F  = Full Control       OI = Object Inherit (files)
# M  = Modify             CI = Container Inherit (folders)
# RX = Read & Execute     IO = Inherit Only
# R  = Read               NP = No Propagate
# W  = Write
```

### DFS Namespaces

```powershell
# Install DFS features
Install-WindowsFeature -Name FS-DFS-Namespace, FS-DFS-Replication -IncludeManagementTools

# Create a domain-based namespace
New-DfsnRoot -TargetPath "\\DC01\DFSRoot" `
    -Type DomainV2 `
    -Path "\\corp.example.com\shared"

# Add a folder target
New-DfsnFolder -Path "\\corp.example.com\shared\docs" `
    -TargetPath "\\FS01\SharedDocs"

# Add replication target (DFS-R)
New-DfsnFolderTarget -Path "\\corp.example.com\shared\docs" `
    -TargetPath "\\FS02\SharedDocs"

# List namespace folders
Get-DfsnFolder -Path "\\corp.example.com\shared\*"
Get-DfsnFolderTarget -Path "\\corp.example.com\shared\docs"
```

### FSRM (File Server Resource Manager) — Storage Quotas

```powershell
# Install FSRM
Install-WindowsFeature -Name FS-Resource-Manager -IncludeManagementTools

# Create a quota template
New-FsrmQuotaTemplate -Name "5GB-Limit" `
    -Size 5GB `
    -SoftLimit:$false `
    -Threshold (New-FsrmQuotaThreshold -Percentage 85 `
        -Action (New-FsrmAction -Type Event -EventType Warning `
            -Body "Quota usage at [Quota Threshold]% on [Quota Path]"))

# Apply quota to a path
New-FsrmQuota -Path "D:\Shares\UserHome\jsmith" -Template "5GB-Limit"

# File screening (block certain file types)
New-FsrmFileScreen -Path "D:\Shares\Documents" `
    -Template "Block Audio and Video Files"

# List quotas
Get-FsrmQuota -Path "D:\Shares\*"
```

### BranchCache

```powershell
# Install BranchCache for file servers
Install-WindowsFeature -Name FS-BranchCache -IncludeManagementTools

# Enable BranchCache on a share
Set-SmbShare -Name "SharedDocs" -CachingMode BranchCache

# Enable via Group Policy for clients (netsh on client side)
netsh branchcache set service mode=distributed
netsh branchcache show status all
```

---

## 9. WSUS (Windows Server Update Services)

### Installation and Configuration

```powershell
# Install WSUS
Install-WindowsFeature -Name UpdateServices -IncludeManagementTools

# Post-install configuration (run once)
& "C:\Program Files\Update Services\Tools\wsusutil.exe" postinstall CONTENT_DIR=D:\WSUS

# Connect to WSUS server
$wsus = Get-WsusServer -Name "WSUS01" -PortNumber 8530

# Or connect to local WSUS
[reflection.assembly]::LoadWithPartialName("Microsoft.UpdateServices.Administration") | Out-Null
$wsus = [Microsoft.UpdateServices.Administration.AdminProxy]::GetUpdateServer()
```

### Managing Updates

```powershell
# Get WSUS updates with filters
Get-WsusUpdate -Approval Unapproved -Status FailedOrNeeded |
    Select-Object -First 20 Update, Classification, Approval

# Approve updates for a group
Get-WsusUpdate -Approval Unapproved -Classification "Security Updates" |
    Approve-WsusUpdate -Action Install -TargetGroupName "Production Servers"

# Decline superseded updates
Get-WsusUpdate -Status Superseded | Deny-WsusUpdate

# Get available classifications
Get-WsusClassification

# Get available products (for subscription)
Get-WsusProduct
```

### Computer Groups

```powershell
# Create a computer group
$wsus.CreateComputerTargetGroup("Production Servers")
$wsus.CreateComputerTargetGroup("Test Servers")

# List computer groups
$wsus.GetComputerTargetGroups() | Select-Object Name, Id

# List computers and their status
Get-WsusComputer -NameIncludes "WEB" |
    Select-Object FullDomainName, LastReportedStatusTime, UpdateInstallationStatus
```

### WSUS Reporting and Maintenance

```powershell
# WSUS server cleanup
Invoke-WsusServerCleanup -CleanupObsoleteUpdates `
    -CleanupUnneededContentFiles `
    -CompressUpdates `
    -DeclineExpiredUpdates `
    -DeclineSupersededUpdates

# Force a client to check in
# (Run on the client machine)
wuauclt /detectnow /reportnow
# Or in PowerShell
(New-Object -ComObject Microsoft.Update.AutoUpdate).DetectNow()
usoclient StartScan     # Windows 10/11 and Server 2019+
```

---

## 10. Certificate Services

### Self-Signed Certificates

```powershell
# Create a self-signed certificate
New-SelfSignedCertificate `
    -DnsName "myapp.corp.example.com", "myapp" `
    -CertStoreLocation "Cert:\LocalMachine\My" `
    -NotAfter (Get-Date).AddYears(2) `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -FriendlyName "MyApp SSL"

# Create a wildcard self-signed certificate
New-SelfSignedCertificate `
    -DnsName "*.corp.example.com" `
    -CertStoreLocation "Cert:\LocalMachine\My" `
    -NotAfter (Get-Date).AddYears(1) `
    -FriendlyName "Corp Wildcard"
```

### Certificate Store Management

```powershell
# List certificates
Get-ChildItem Cert:\LocalMachine\My
Get-ChildItem Cert:\LocalMachine\Root    # Trusted Root CAs
Get-ChildItem Cert:\CurrentUser\My

# Find certificates by subject
Get-ChildItem Cert:\LocalMachine\My |
    Where-Object { $_.Subject -like "*corp.example.com*" } |
    Select-Object Thumbprint, Subject, NotAfter

# Find expiring certificates (within 30 days)
$cutoff = (Get-Date).AddDays(30)
Get-ChildItem Cert:\LocalMachine\My |
    Where-Object { $_.NotAfter -lt $cutoff } |
    Select-Object Subject, NotAfter, Thumbprint

# Export a certificate (public key only)
Export-Certificate -Cert (Get-ChildItem Cert:\LocalMachine\My\<thumbprint>) `
    -FilePath C:\Certs\myapp.cer

# Export with private key (PFX)
$pfxPassword = ConvertTo-SecureString "ExportP@ss!" -AsPlainText -Force
Export-PfxCertificate -Cert (Get-ChildItem Cert:\LocalMachine\My\<thumbprint>) `
    -FilePath C:\Certs\myapp.pfx `
    -Password $pfxPassword

# Import a PFX certificate
Import-PfxCertificate -FilePath C:\Certs\myapp.pfx `
    -CertStoreLocation Cert:\LocalMachine\My `
    -Password (ConvertTo-SecureString "ExportP@ss!" -AsPlainText -Force)

# Import a CA certificate to Trusted Root
Import-Certificate -FilePath C:\Certs\CorpCA.cer `
    -CertStoreLocation Cert:\LocalMachine\Root

# Remove a certificate
Remove-Item Cert:\LocalMachine\My\<thumbprint>
```

### AD Certificate Services (ADCS)

```powershell
# Install AD CS (Enterprise Root CA)
Install-WindowsFeature -Name AD-Certificate -IncludeManagementTools

# Configure the CA
Install-AdcsCertificationAuthority `
    -CAType EnterpriseRootCA `
    -CACommonName "Corp-Root-CA" `
    -KeyLength 4096 `
    -HashAlgorithmName SHA256 `
    -ValidityPeriod Years `
    -ValidityPeriodUnits 10 `
    -Force

# Install Certificate Enrollment Web Service (optional)
Install-WindowsFeature -Name ADCS-Enroll-Web-Svc
Install-AdcsEnrollmentPolicyWebService -AuthenticationType Kerberos

# Request a certificate from the CA
Get-Certificate -Template "WebServer" `
    -DnsName "myapp.corp.example.com" `
    -CertStoreLocation Cert:\LocalMachine\My

# List certificate templates
certutil -CATemplates

# View CA configuration
certutil -config - -ping
certutil -CA
```

---

## 11. Server Monitoring

### Performance Counters

```powershell
# Get available counter sets
Get-Counter -ListSet * | Select-Object CounterSetName | Sort-Object CounterSetName

# CPU usage
Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 2 -MaxSamples 5

# Memory
Get-Counter "\Memory\Available MBytes"
Get-Counter "\Memory\% Committed Bytes In Use"

# Disk
Get-Counter "\PhysicalDisk(_Total)\% Disk Time"
Get-Counter "\PhysicalDisk(_Total)\Avg. Disk Queue Length"
Get-Counter "\LogicalDisk(*)\% Free Space"

# Network
Get-Counter "\Network Interface(*)\Bytes Total/sec"

# Multiple counters at once
Get-Counter -Counter @(
    "\Processor(_Total)\% Processor Time",
    "\Memory\Available MBytes",
    "\PhysicalDisk(_Total)\% Disk Time",
    "\Network Interface(*)\Bytes Total/sec"
) -SampleInterval 5 -MaxSamples 10 |
    Export-Counter -Path C:\PerfLogs\baseline.csv -FileFormat CSV
```

### Event Log Monitoring

```powershell
# Classic event log (Get-EventLog — older but simpler)
Get-EventLog -LogName System -Newest 50
Get-EventLog -LogName Application -EntryType Error -Newest 20
Get-EventLog -LogName Security -InstanceId 4625 -Newest 10  # failed logons

# Modern event log (Get-WinEvent — preferred)
Get-WinEvent -LogName System -MaxEvents 50
Get-WinEvent -LogName Application -MaxEvents 50

# Filter by level (1=Critical, 2=Error, 3=Warning, 4=Info)
Get-WinEvent -FilterHashtable @{
    LogName   = "System"
    Level     = 1,2           # Critical and Error
    StartTime = (Get-Date).AddHours(-24)
}

# Filter by Event ID
Get-WinEvent -FilterHashtable @{
    LogName = "Security"
    Id      = 4625            # Failed logon attempts
} -MaxEvents 50 | Select-Object TimeCreated, Message

# Filter by provider
Get-WinEvent -FilterHashtable @{
    LogName      = "Application"
    ProviderName = "MSSQLSERVER"
    Level        = 2
}

# Export events
Get-WinEvent -FilterHashtable @{
    LogName   = "System"
    Level     = 1,2
    StartTime = (Get-Date).AddDays(-7)
} | Export-Csv C:\Reports\errors-week.csv -NoTypeInformation
```

### Disk Space Monitoring

```powershell
# Check disk space on local server
Get-PSDrive -PSProvider FileSystem |
    Select-Object Name,
        @{N="Used(GB)"; E={[math]::Round($_.Used/1GB,2)}},
        @{N="Free(GB)"; E={[math]::Round($_.Free/1GB,2)}},
        @{N="Total(GB)"; E={[math]::Round(($_.Used+$_.Free)/1GB,2)}},
        @{N="%Free"; E={[math]::Round($_.Free/($_.Used+$_.Free)*100,1)}}

# Using WMI/CIM for more detail
Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=3" |
    Select-Object DeviceID,
        @{N="Size(GB)"; E={[math]::Round($_.Size/1GB,2)}},
        @{N="Free(GB)"; E={[math]::Round($_.FreeSpace/1GB,2)}},
        @{N="%Free"; E={[math]::Round($_.FreeSpace/$_.Size*100,1)}}

# Alert on low disk space (< 10% free)
Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=3" |
    Where-Object { ($_.FreeSpace / $_.Size) -lt 0.10 } |
    ForEach-Object {
        Write-Warning "LOW DISK: $($_.DeviceID) — $([math]::Round($_.FreeSpace/1GB,1)) GB free ($([math]::Round($_.FreeSpace/$_.Size*100,1))%)"
    }

# Check disk space on multiple servers
$servers = "DC01", "WEB01", "FS01"
Invoke-Command -ComputerName $servers -ScriptBlock {
    Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
        Select-Object @{N="Server"; E={$env:COMPUTERNAME}}, DeviceID,
            @{N="Free(GB)"; E={[math]::Round($_.FreeSpace/1GB,1)}},
            @{N="%Free"; E={[math]::Round($_.FreeSpace/$_.Size*100,1)}}
} | Sort-Object "%Free"
```

### Service Health Checks

```powershell
# Check critical services
$criticalServices = @(
    "DNS", "NTDS", "kdc", "Netlogon", "DFSR",   # AD / DC services
    "DHCPServer", "W3SVC", "WAS",                 # DHCP / IIS
    "vmms", "vmcompute"                            # Hyper-V
)

$criticalServices | ForEach-Object {
    $svc = Get-Service -Name $_ -ErrorAction SilentlyContinue
    if ($svc) {
        [PSCustomObject]@{
            Name   = $svc.Name
            Display = $svc.DisplayName
            Status = $svc.Status
        }
    }
} | Format-Table -AutoSize

# Restart a stopped critical service
Get-Service -Name "W3SVC" | Where-Object { $_.Status -ne "Running" } | Start-Service

# Monitor service restarts
Get-WinEvent -FilterHashtable @{
    LogName = "System"
    Id      = 7036    # service state change
} -MaxEvents 20 | Select-Object TimeCreated, Message

# Remote service check
Invoke-Command -ComputerName DC01, WEB01 -ScriptBlock {
    Get-Service -Name DNS, W3SVC, DHCPServer -ErrorAction SilentlyContinue |
        Select-Object @{N="Server";E={$env:COMPUTERNAME}}, Name, Status
}

# Uptime check
Get-CimInstance Win32_OperatingSystem |
    Select-Object @{N="LastBoot";E={$_.LastBootUpTime}},
        @{N="Uptime";E={(Get-Date) - $_.LastBootUpTime}}

# Quick server health summary
function Get-ServerHealth {
    param([string]$ComputerName = $env:COMPUTERNAME)

    Invoke-Command -ComputerName $ComputerName -ScriptBlock {
        [PSCustomObject]@{
            Server     = $env:COMPUTERNAME
            Uptime     = (New-TimeSpan -Start (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).ToString("dd\.hh\:mm")
            CPU        = [math]::Round((Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue, 1)
            MemFreeGB  = [math]::Round((Get-Counter "\Memory\Available MBytes").CounterSamples.CookedValue / 1024, 1)
            DiskFree   = (Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
                "$($_.DeviceID) $([math]::Round($_.FreeSpace/1GB,1))GB"
            }) -join "; "
            FailedSvcs = (Get-Service | Where-Object {
                $_.StartType -eq "Automatic" -and $_.Status -ne "Running"
            } | Select-Object -ExpandProperty Name) -join ", "
        }
    }
}

# Usage
Get-ServerHealth -ComputerName "DC01"
"DC01","WEB01","FS01" | ForEach-Object { Get-ServerHealth -ComputerName $_ } | Format-Table
```

---

## Quick Reference — Common Module Imports

```powershell
Import-Module ActiveDirectory          # AD cmdlets
Import-Module GroupPolicy              # GPO cmdlets
Import-Module DnsServer                # DNS cmdlets
Import-Module DhcpServer               # DHCP cmdlets
Import-Module WebAdministration        # IIS (legacy)
Import-Module IISAdministration        # IIS (modern)
Import-Module Hyper-V                  # Hyper-V cmdlets
Import-Module SmbShare                 # SMB share cmdlets
Import-Module UpdateServices           # WSUS cmdlets (partial)
Import-Module PKI                      # Certificate cmdlets
Import-Module DFSn                     # DFS Namespace
Import-Module DFSR                     # DFS Replication
Import-Module FileServerResourceManager # FSRM quotas/screens
```

---

## Related Skills

| Scope | Skill |
|---|---|
| PowerShell fundamentals (parent) | `windows-powershell` |
| Windows security (firewall, BitLocker, Defender, auditing) | `windows-ps-security` |
| CMD / batch scripting | `windows-cmd` |
