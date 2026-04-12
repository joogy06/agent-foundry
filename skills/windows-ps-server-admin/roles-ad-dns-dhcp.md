# Server Roles, Active Directory, Group Policy, DNS, and DHCP

Reference file for the `windows-ps-server-admin` skill. Covers server roles/features, Active Directory administration, Group Policy, DNS Server, and DHCP Server.

## 1. Server Roles and Features

### Install and Query Roles

```powershell
# List all available roles and features
Get-WindowsFeature

# Filter to installed features
Get-WindowsFeature | Where-Object Installed

# Search for a feature by name
Get-WindowsFeature -Name *DNS*
Get-WindowsFeature -Name *Hyper*

# Install a role (with management tools)
Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools
Install-WindowsFeature -Name DNS -IncludeManagementTools
Install-WindowsFeature -Name DHCP -IncludeManagementTools
Install-WindowsFeature -Name Web-Server -IncludeAllSubFeature -IncludeManagementTools

# Install multiple roles
Install-WindowsFeature -Name File-Services, FS-FileServer, FS-DFS-Namespace

# Remove a role
Uninstall-WindowsFeature -Name Telnet-Client

# Install on a remote server
Install-WindowsFeature -Name Web-Server -ComputerName SERVER02 -IncludeManagementTools
```

### RSAT Tools (Remote Administration from Workstation)

```powershell
# Windows 10/11 — RSAT is a Windows Capability
Get-WindowsCapability -Name RSAT* -Online
Add-WindowsCapability -Online -Name Rsat.ActiveDirectory.DS-LDS.Tools~~~~0.0.1.0
Add-WindowsCapability -Online -Name Rsat.Dns.Tools~~~~0.0.1.0
Add-WindowsCapability -Online -Name Rsat.DHCP.Tools~~~~0.0.1.0
Add-WindowsCapability -Online -Name Rsat.GroupPolicy.Management.Tools~~~~0.0.1.0

# Install all RSAT tools at once
Get-WindowsCapability -Name RSAT* -Online | Add-WindowsCapability -Online
```

### Server Core Management

```powershell
# Configure Server Core remotely via WinRM
Enable-PSRemoting -Force    # on the Server Core machine
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "SERVER-CORE01"

# Enter remote session
Enter-PSSession -ComputerName SERVER-CORE01 -Credential (Get-Credential)

# Server Configuration tool (local on Server Core)
sconfig
```

---

## 2. Active Directory

<HARD-RULE>
Before bulk AD modifications (bulk user creation, OU restructuring, group membership changes), always test with -WhatIf first and export a backup of current state. Use `Get-ADObject -Filter * -SearchBase "OU=Target,DC=domain,DC=com"` to verify scope before changes.
</HARD-RULE>

### Promote a Domain Controller

```powershell
# Install AD DS role
Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools

# New forest
Install-ADDSForest `
    -DomainName "corp.example.com" `
    -DomainNetbiosName "CORP" `
    -ForestMode "WinThreshold" `
    -DomainMode "WinThreshold" `
    -InstallDns:$true `
    -SafeModeAdministratorPassword (ConvertTo-SecureString "P@ssw0rd!" -AsPlainText -Force)

# Additional DC in existing domain
Install-ADDSDomainController `
    -DomainName "corp.example.com" `
    -InstallDns:$true `
    -Credential (Get-Credential) `
    -SafeModeAdministratorPassword (ConvertTo-SecureString "P@ssw0rd!" -AsPlainText -Force)
```

### User Management

```powershell
# Create a single user
New-ADUser -Name "Jane Smith" `
    -SamAccountName "jsmith" `
    -UserPrincipalName "jsmith@corp.example.com" `
    -GivenName "Jane" `
    -Surname "Smith" `
    -DisplayName "Jane Smith" `
    -Title "Systems Engineer" `
    -Department "IT" `
    -Office "HQ" `
    -Path "OU=IT,OU=Users,DC=corp,DC=example,DC=com" `
    -AccountPassword (ConvertTo-SecureString "Temp@Pass1" -AsPlainText -Force) `
    -Enabled $true `
    -ChangePasswordAtLogon $true

# Query users
Get-ADUser -Identity jsmith
Get-ADUser -Identity jsmith -Properties *
Get-ADUser -Filter {Department -eq "IT"} -Properties Title, Department |
    Select-Object Name, SamAccountName, Title, Department

# Search by name (wildcard)
Get-ADUser -Filter {Name -like "*smith*"}

# Modify a user
Set-ADUser -Identity jsmith -Title "Senior Engineer" -Department "Engineering"
Set-ADUser -Identity jsmith -Replace @{extensionAttribute1 = "VPN-Enabled"}

# Disable / Enable / Unlock
Disable-ADAccount -Identity jsmith
Enable-ADAccount -Identity jsmith
Unlock-ADAccount -Identity jsmith

# Reset password
Set-ADAccountPassword -Identity jsmith `
    -NewPassword (ConvertTo-SecureString "NewP@ss1!" -AsPlainText -Force) `
    -Reset
Set-ADUser -Identity jsmith -ChangePasswordAtLogon $true

# Find locked, disabled, or expired accounts
Search-ADAccount -LockedOut | Select-Object Name, SamAccountName, LastLogonDate
Search-ADAccount -AccountDisabled | Select-Object Name, SamAccountName
Search-ADAccount -AccountExpired | Select-Object Name, SamAccountName
Search-ADAccount -PasswordExpired | Select-Object Name, SamAccountName, PasswordLastSet
Search-ADAccount -AccountInactive -TimeSpan 90.00:00:00 |
    Select-Object Name, LastLogonDate

# Remove a user (use with caution)
Remove-ADUser -Identity jsmith -Confirm:$true
```

### Bulk User Creation from CSV

CSV format (`users.csv`):
```
SamAccountName,GivenName,Surname,Department,Title,OU
jdoe,John,Doe,Sales,Account Manager,OU=Sales
alee,Alice,Lee,Engineering,Developer,OU=Engineering
```

```powershell
Import-Csv -Path C:\Scripts\users.csv | ForEach-Object {
    $password = ConvertTo-SecureString "Welcome1!" -AsPlainText -Force
    $ouPath = "$($_.OU),OU=Users,DC=corp,DC=example,DC=com"

    New-ADUser `
        -SamAccountName $_.SamAccountName `
        -UserPrincipalName "$($_.SamAccountName)@corp.example.com" `
        -GivenName $_.GivenName `
        -Surname $_.Surname `
        -Name "$($_.GivenName) $($_.Surname)" `
        -DisplayName "$($_.GivenName) $($_.Surname)" `
        -Department $_.Department `
        -Title $_.Title `
        -Path $ouPath `
        -AccountPassword $password `
        -Enabled $true `
        -ChangePasswordAtLogon $true

    Write-Host "Created user: $($_.SamAccountName)" -ForegroundColor Green
}
```

### Groups

```powershell
# Create groups
New-ADGroup -Name "VPN-Users" `
    -GroupScope Global `
    -GroupCategory Security `
    -Path "OU=Groups,DC=corp,DC=example,DC=com" `
    -Description "Users authorized for VPN access"

# Add / remove members
Add-ADGroupMember -Identity "VPN-Users" -Members jsmith, jdoe, alee
Remove-ADGroupMember -Identity "VPN-Users" -Members jdoe -Confirm:$false

# List group members
Get-ADGroupMember -Identity "VPN-Users" | Select-Object Name, SamAccountName
Get-ADGroupMember -Identity "Domain Admins" -Recursive

# Find which groups a user belongs to
Get-ADUser -Identity jsmith -Properties MemberOf |
    Select-Object -ExpandProperty MemberOf |
    Get-ADGroup | Select-Object Name
```

### Organizational Units

```powershell
# Create OU
New-ADOrganizationalUnit -Name "IT" `
    -Path "OU=Users,DC=corp,DC=example,DC=com" `
    -ProtectedFromAccidentalDeletion $true

# List OUs
Get-ADOrganizationalUnit -Filter * | Select-Object Name, DistinguishedName

# Move an object to a different OU
Move-ADObject -Identity "CN=Jane Smith,OU=IT,OU=Users,DC=corp,DC=example,DC=com" `
    -TargetPath "OU=Engineering,OU=Users,DC=corp,DC=example,DC=com"
```

### Computer Accounts

```powershell
# List all computers
Get-ADComputer -Filter * | Select-Object Name, DNSHostName, Enabled

# Find stale computers (not logged in for 90 days)
$cutoff = (Get-Date).AddDays(-90)
Get-ADComputer -Filter {LastLogonDate -lt $cutoff} -Properties LastLogonDate |
    Select-Object Name, LastLogonDate, Enabled

# Disable stale computer accounts
Get-ADComputer -Filter {LastLogonDate -lt $cutoff} -Properties LastLogonDate |
    Disable-ADAccount -WhatIf
```

### AD Replication

```powershell
# Check replication status
Get-ADReplicationPartnerMetadata -Target DC01 -Scope Server
Get-ADReplicationPartnerMetadata -Target "corp.example.com" -Scope Domain |
    Select-Object Server, Partner, LastReplicationSuccess, LastReplicationResult

# Force replication
Sync-ADObject -Source DC01 -Destination DC02 -Object "CN=Jane Smith,OU=IT,DC=corp,DC=example,DC=com"

# Replication health (repadmin equivalent)
repadmin /replsummary
repadmin /showrepl
repadmin /syncall /AdeP
```

---

## 3. Group Policy

```powershell
# Import the module
Import-Module GroupPolicy

# List all GPOs
Get-GPO -All | Select-Object DisplayName, Id, GpoStatus, CreationTime

# Get details of a specific GPO
Get-GPO -Name "Default Domain Policy"
Get-GPO -Name "Default Domain Policy" | Get-GPOReport -ReportType Html -Path C:\Reports\DDP.html

# Create a new GPO
New-GPO -Name "IT-Workstation-Policy" -Comment "Standard settings for IT workstations"

# Link GPO to an OU
New-GPLink -Name "IT-Workstation-Policy" `
    -Target "OU=IT,OU=Workstations,DC=corp,DC=example,DC=com" `
    -LinkEnabled Yes

# Set GPO permissions
Set-GPPermission -Name "IT-Workstation-Policy" `
    -PermissionLevel GpoApply `
    -TargetName "IT-Workstations" `
    -TargetType Group

# Force Group Policy update (remote)
Invoke-GPUpdate -Computer "WS01" -Force -RandomDelayInMinutes 0

# GPO Resultant Set of Policy (RSoP) — what policies apply
Get-GPResultantSetOfPolicy -Computer "WS01" -User "CORP\jsmith" `
    -ReportType Html -Path C:\Reports\RSoP-jsmith.html
gpresult /R                    # quick summary on local machine
gpresult /H C:\Reports\gp.html # HTML report

# Backup all GPOs
Backup-GPO -All -Path C:\GPOBackups

# Backup a specific GPO
Backup-GPO -Name "IT-Workstation-Policy" -Path C:\GPOBackups

# Restore a GPO
Restore-GPO -Name "IT-Workstation-Policy" -Path C:\GPOBackups

# Copy a GPO
Copy-GPO -SourceName "IT-Workstation-Policy" -TargetName "Dev-Workstation-Policy"
```

---

## 4. DNS Server

```powershell
# Import the module
Import-Module DnsServer

# List all DNS zones
Get-DnsServerZone
Get-DnsServerZone | Where-Object { $_.ZoneType -eq "Primary" }

# Create a primary forward lookup zone
Add-DnsServerPrimaryZone -Name "app.corp.example.com" `
    -ReplicationScope Domain `
    -DynamicUpdate Secure

# Create a reverse lookup zone
Add-DnsServerPrimaryZone -NetworkID "10.0.1.0/24" `
    -ReplicationScope Domain `
    -DynamicUpdate Secure

# Add DNS records
Add-DnsServerResourceRecordA -ZoneName "corp.example.com" `
    -Name "web01" -IPv4Address "10.0.1.50"

Add-DnsServerResourceRecordAAAA -ZoneName "corp.example.com" `
    -Name "web01" -IPv6Address "fd00::50"

Add-DnsServerResourceRecordCName -ZoneName "corp.example.com" `
    -Name "www" -HostNameAlias "web01.corp.example.com"

Add-DnsServerResourceRecordMX -ZoneName "corp.example.com" `
    -Name "." -MailExchange "mail.corp.example.com" -Preference 10

Add-DnsServerResourceRecord -ZoneName "corp.example.com" `
    -Name "." -Txt -DescriptiveText "v=spf1 mx -all"

# Query existing records
Get-DnsServerResourceRecord -ZoneName "corp.example.com" -RRType A
Get-DnsServerResourceRecord -ZoneName "corp.example.com" -Name "web01"

# Remove a record
Remove-DnsServerResourceRecord -ZoneName "corp.example.com" `
    -RRType A -Name "oldserver" -Force

# Forwarders
Add-DnsServerForwarder -IPAddress 8.8.8.8, 8.8.4.4
Get-DnsServerForwarder
Remove-DnsServerForwarder -IPAddress 8.8.4.4

# Conditional forwarders
Add-DnsServerConditionalForwarderZone -Name "partner.com" `
    -MasterServers 10.10.1.1, 10.10.1.2 `
    -ReplicationScope Domain

# DNS scavenging (clean stale records)
Set-DnsServerScavenging -ScavengingState $true `
    -RefreshInterval 7.00:00:00 `
    -NoRefreshInterval 7.00:00:00 `
    -ScavengingInterval 7.00:00:00

# Enable aging on a zone
Set-DnsServerZoneAging -Name "corp.example.com" -Aging $true

# Diagnostics
Get-DnsServerStatistics
Test-DnsServer -IPAddress 10.0.1.10 -ZoneName "corp.example.com"
Clear-DnsServerCache
```

---

## 5. DHCP Server

```powershell
# Import the module
Import-Module DhcpServer

# Authorize DHCP server in Active Directory (required)
Add-DhcpServerInDC -DnsName "dc01.corp.example.com" -IPAddress 10.0.1.10

# Create an IPv4 scope
Add-DhcpServerv4Scope -Name "Main-LAN" `
    -StartRange 10.0.1.100 `
    -EndRange 10.0.1.250 `
    -SubnetMask 255.255.255.0 `
    -LeaseDuration 8.00:00:00 `
    -State Active

# Set scope options (gateway, DNS, domain)
Set-DhcpServerv4OptionValue -ScopeId 10.0.1.0 `
    -Router 10.0.1.1 `
    -DnsServer 10.0.1.10, 10.0.1.11 `
    -DnsDomain "corp.example.com"

# Exclusion range
Add-DhcpServerv4ExclusionRange -ScopeId 10.0.1.0 `
    -StartRange 10.0.1.1 -EndRange 10.0.1.20

# Reservations
Add-DhcpServerv4Reservation -ScopeId 10.0.1.0 `
    -IPAddress 10.0.1.50 `
    -ClientId "AA-BB-CC-DD-EE-FF" `
    -Name "print-server" `
    -Description "Main floor printer"

# List leases and reservations
Get-DhcpServerv4Lease -ScopeId 10.0.1.0
Get-DhcpServerv4Reservation -ScopeId 10.0.1.0
Get-DhcpServerv4Scope
Get-DhcpServerv4ScopeStatistics

# DHCP failover (hot standby)
Add-DhcpServerv4Failover -Name "DHCP-Failover" `
    -PartnerServer "dc02.corp.example.com" `
    -ScopeId 10.0.1.0 `
    -SharedSecret "S3cretKey!" `
    -Mode HotStandby `
    -ServerRole Active `
    -ReservePercent 10 `
    -AutoStateTransition $true `
    -StateSwitchInterval (New-TimeSpan -Minutes 60)

# DHCP failover (load balance)
Add-DhcpServerv4Failover -Name "DHCP-LB" `
    -PartnerServer "dc02.corp.example.com" `
    -ScopeId 10.0.1.0 `
    -SharedSecret "S3cretKey!" `
    -Mode LoadBalance `
    -LoadBalancePercent 50

# Check failover status
Get-DhcpServerv4Failover

# Export / import DHCP configuration (migration)
Export-DhcpServer -File C:\DHCP\dhcp-export.xml -Leases
Import-DhcpServer -File C:\DHCP\dhcp-export.xml -BackupPath C:\DHCP\backup
```

---

