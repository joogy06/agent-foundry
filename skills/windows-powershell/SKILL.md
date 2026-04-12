---
name: windows-powershell
description: Use when writing or debugging PowerShell scripts — PowerShell 7.x and Windows PowerShell 5.1, pipeline and object manipulation, error handling (try/catch/ErrorAction), modules and package management (PSGallery), remoting (WinRM, SSH), Desired State Configuration (DSC), scheduled tasks, WMI/CIM queries, registry operations, file system operations, string/regex, JSON/XML/CSV handling, and cross-platform considerations. Parent skill for the windows-ps-* skill family.
---

# Windows PowerShell Administration

Core PowerShell scripting skill. Server admin topics live in `windows-ps-server-admin`; security topics in `windows-ps-security`.

---

## 1. PowerShell Versions

```powershell
$PSVersionTable.PSVersion          # Check version
```

| Feature | Windows PS 5.1 | PS 7.x |
|---|---|---|
| Executable | `powershell.exe` | `pwsh.exe` / `pwsh` |
| .NET runtime | .NET Framework 4.x | .NET 6/7/8+ |
| Cross-platform | Windows only | Windows, Linux, macOS |
| Ternary / null-coalesce / `&&` `\|\|` | No | Yes |
| `ForEach-Object -Parallel` | No | Yes |
| Default encoding | UTF-16LE | UTF-8 NoBOM |

```powershell
# Install PS 7 on Windows
winget install Microsoft.PowerShell
```

- **Use 5.1** for modules that require .NET Framework (older Exchange, SharePoint) or systems without PS 7.
- **Use 7.x** for new scripts, cross-platform, modern language features.
- Both coexist side by side.

---

## 2. Core Syntax

### Variables and Data Types

```powershell
$name = "Server01"
[int]$port = 5985
[datetime]$cutoff = "2025-01-01"

# Key automatic variables
$_             # Current pipeline object (alias: $PSItem)
$?             # Success of last command
$LASTEXITCODE  # Exit code of last native command
$null          # Null value
```

### Arrays and Hashtables

```powershell
$servers = @("DC01", "DC02", "WEB01")
$numbers = 1..10
$servers += "SQL01"                           # Creates new array (slow in loops)
$list = [System.Collections.Generic.List[string]]::new()  # Preferred in loops
$list.Add("DC01")

$servers -contains "DC01"   # $true
$servers.Count              # Element count

# Hashtable
$config = @{ Server = "DC01"; Port = 5985; Protocol = "HTTPS" }
$config["Server"]
$config.Port = 443

# Ordered hashtable
$ordered = [ordered]@{ First = 1; Second = 2; Third = 3 }
```

### Splatting and Here-Strings

```powershell
$params = @{
    Path        = "C:\Logs"
    Filter      = "*.log"
    Recurse     = $true
    ErrorAction = "SilentlyContinue"
}
Get-ChildItem @params

# Expanding here-string (variables interpolated)
$body = @"
Server $name is on port $port. Date: $(Get-Date -Format 'yyyy-MM-dd').
"@

# Literal here-string (no interpolation)
$pattern = @'
^(?<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(?<host>\S+)
'@
```

### PS 7+ Language Features

```powershell
$status = ($svc.Status -eq "Running") ? "Healthy" : "Down"   # Ternary
$name = $env:COMPUTERNAME ?? "Unknown"                         # Null-coalescing
$config ??= Get-DefaultConfig                                  # Null-coalescing assignment
Get-Process notepad && Write-Host "Running"                    # Pipeline chain
Get-Process fake 2>$null || Write-Host "Not found"
```

---

## 3. Pipeline and Objects

```powershell
Get-Service | Where-Object Status -eq "Running"
Get-Process | Select-Object Name, CPU, WorkingSet -First 10
Get-Process | Select-Object Name, @{N="MemMB"; E={[math]::Round($_.WorkingSet/1MB,1)}}
1..5 | ForEach-Object { $_ * 2 }
Get-Process | Sort-Object CPU -Descending | Select-Object -First 5
Get-Service | Group-Object Status
Get-ChildItem -Recurse | Measure-Object -Property Length -Sum -Average -Maximum
```

### Custom Objects

```powershell
$report = [PSCustomObject]@{
    ServerName = $env:COMPUTERNAME
    OS         = (Get-CimInstance Win32_OperatingSystem).Caption
    CPUCount   = (Get-CimInstance Win32_Processor).NumberOfCores
}
$report | Add-Member -NotePropertyName "CheckedAt" -NotePropertyValue (Get-Date)

# Build collection
$results = foreach ($server in $servers) {
    [PSCustomObject]@{ Name = $server; Online = Test-Connection $server -Count 1 -Quiet }
}
```

### Formatting

```powershell
Get-Process | Format-Table Name, CPU, WorkingSet -AutoSize
Get-Service WinRM | Format-List *
# IMPORTANT: Format-* produces display objects. Never pipe to Export-Csv/ConvertTo-Json.
# Use Select-Object for data extraction before export.
```

---

## 4. Functions and Scripts

```powershell
function Get-DiskReport {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string[]]$ComputerName,

        [Parameter()]
        [ValidateSet("GB", "MB", "TB")]
        [string]$Unit = "GB",

        [Parameter()]
        [switch]$IncludeRemovable
    )

    begin { $divisor = switch ($Unit) { "TB" {1TB} "GB" {1GB} "MB" {1MB} } }

    process {
        foreach ($computer in $ComputerName) {
            try {
                $disks = Get-CimInstance Win32_LogicalDisk -ComputerName $computer -ErrorAction Stop
                if (-not $IncludeRemovable) { $disks = $disks | Where-Object DriveType -eq 3 }
                foreach ($disk in $disks) {
                    [PSCustomObject]@{
                        Computer  = $computer
                        Drive     = $disk.DeviceID
                        SizeTotal = [math]::Round($disk.Size / $divisor, 2)
                        FreeSpace = [math]::Round($disk.FreeSpace / $divisor, 2)
                        PctFree   = [math]::Round(($disk.FreeSpace / $disk.Size) * 100, 1)
                    }
                }
            } catch { Write-Warning "Failed to query $computer : $_" }
        }
    }
}
```

### Pipeline Input and ShouldProcess

```powershell
function Stop-OldProcess {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory, ValueFromPipeline, ValueFromPipelineByPropertyName)]
        [string]$Name,
        [int]$MaxCpuSeconds = 3600
    )
    process {
        Get-Process -Name $Name -EA SilentlyContinue |
            Where-Object { $_.CPU -gt $MaxCpuSeconds } | ForEach-Object {
                if ($PSCmdlet.ShouldProcess("$($_.Name) (PID $($_.Id))", "Stop")) {
                    $_ | Stop-Process -Force
                }
            }
    }
}
# Supports -WhatIf and -Confirm automatically
```

### Script Modules

```powershell
# MyModule.psm1
function Get-PublicFunction { [CmdletBinding()] param(); Write-Output "Exported" }
function HelperInternal { Write-Output "Not exported" }
Export-ModuleMember -Function Get-PublicFunction

# Dot-source all ps1 files in a folder
Get-ChildItem "$PSScriptRoot\Functions\*.ps1" | ForEach-Object { . $_.FullName }
```

---

## 5. Error Handling

```powershell
try {
    $result = Get-Content "C:\missing.txt" -ErrorAction Stop
} catch [System.IO.FileNotFoundException] {
    Write-Warning "File not found: $($_.Exception.Message)"
} catch [System.UnauthorizedAccessException] {
    Write-Warning "Access denied: $($_.Exception.Message)"
} catch {
    Write-Warning "Error: $($_.Exception.GetType().FullName) - $($_.Exception.Message)"
    Write-Warning $_.ScriptStackTrace
} finally {
    Write-Verbose "Cleanup complete."
}
```

### ErrorAction and Error Inspection

```powershell
Get-Item "C:\nope" -ErrorAction SilentlyContinue    # Suppress
Get-Item "C:\nope" -ErrorAction Stop                 # Make terminating
$ErrorActionPreference = "Stop"                       # Session-wide

$Error[0]                    # Most recent error
$Error[0].Exception.Message  # Message text
$Error[0].InvocationInfo     # Where it happened
$Error.Clear()               # Reset history
```

### Terminating vs Non-Terminating

```powershell
throw "Critical failure"                          # Terminating
Write-Error "Something failed but continues"      # Non-terminating
# Use -ErrorAction Stop on cmdlets to convert non-terminating to terminating
```

---

## 6. Modules and Packages

```powershell
Find-Module -Name "*ActiveDirectory*"
Install-Module -Name Az -Scope CurrentUser -Force
Update-Module -Name Az
Get-InstalledModule
Get-Module -ListAvailable
Import-Module ActiveDirectory

# PSResourceGet (PS 7.4+ modern replacement)
Install-PSResource -Name Az -Scope CurrentUser
Find-PSResource -Name "*SQL*" -Repository PSGallery

# Create manifest
New-ModuleManifest -Path "C:\Modules\MyModule\MyModule.psd1" `
    -RootModule "MyModule.psm1" -ModuleVersion "1.0.0" `
    -FunctionsToExport @("Get-ServerReport", "Set-ServerConfig")
Test-ModuleManifest -Path "C:\Modules\MyModule\MyModule.psd1"
```

---

## 7. Remoting

<HARD-RULE>
Always use HTTPS or SSH-based remoting in production. Never enable remoting with `-SkipNetworkProfileCheck` on untrusted networks without compensating controls. Use constrained endpoints (JEA) to limit remote execution. Never hardcode passwords — use `Get-Credential` or `PSCredential` objects.
</HARD-RULE>

```powershell
# Enable (run as Admin)
Enable-PSRemoting -Force
Test-WSMan -ComputerName "DC01"

# Interactive session
Enter-PSSession -ComputerName DC01 -Credential (Get-Credential)

# Run on multiple remote machines
Invoke-Command -ComputerName DC01, DC02, WEB01 -ScriptBlock {
    Get-Service W32Time | Select-Object Name, Status, MachineName
}

# Persistent session
$session = New-PSSession -ComputerName DC01 -Credential $cred
Invoke-Command -Session $session -ScriptBlock { Get-Process }
Copy-Item -Path "C:\Scripts\Deploy.ps1" -Destination "C:\Scripts\" -ToSession $session
Remove-PSSession $session

# Run local script remotely
Invoke-Command -ComputerName DC01 -FilePath "C:\Scripts\Audit.ps1"

# SSH-based remoting (PS 7+ -- requires OpenSSH on target)
New-PSSession -HostName server01 -UserName admin -SSHTransport
```

---

## 8. WMI/CIM

<HARD-RULE>
Always prefer `Get-CimInstance` over the deprecated `Get-WmiObject`. `Get-WmiObject` is removed in PS 7.
</HARD-RULE>

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, LastBootUpTime
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, MaxClockSpeed
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
    Select-Object DeviceID, @{N="SizeGB";E={[math]::Round($_.Size/1GB,1)}},
        @{N="FreeGB";E={[math]::Round($_.FreeSpace/1GB,1)}}
Get-CimInstance Win32_Service -Filter "State='Running'" | Select-Object Name, DisplayName
Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=$true" |
    Select-Object Description, IPAddress, DefaultIPGateway

# Remote CIM session
$cimSession = New-CimSession -ComputerName DC01 -Credential $cred
Get-CimInstance Win32_OperatingSystem -CimSession $cimSession
Remove-CimSession $cimSession

# Invoke CIM method
$proc = Get-CimInstance Win32_Process -Filter "Name='notepad.exe'"
Invoke-CimMethod -InputObject $proc -MethodName Terminate
```

---

## 9. File System

<HARD-RULE>
Always use `-WhatIf` when testing `Remove-Item`, `Move-Item`, or recursive deletions. Never run `Remove-Item -Recurse -Force` on root or user profile paths without explicit confirmation. Validate paths with `Test-Path` before destructive operations.
</HARD-RULE>

```powershell
Get-ChildItem C:\Logs -Recurse -Filter "*.log"
Get-ChildItem C:\Logs -File                        # Files only
Get-ChildItem C:\Logs -Directory                   # Dirs only
Get-ChildItem C:\ -Force -Hidden                   # Hidden/system files

Test-Path "C:\Logs\app.log"                        # $true/$false
Test-Path "C:\Logs" -PathType Container            # Must be directory

# Read/Write
$content = Get-Content "C:\Logs\app.log"
$raw = Get-Content "C:\Logs\app.log" -Raw          # Single string
$last20 = Get-Content "C:\Logs\app.log" -Tail 20
Set-Content "C:\output.txt" -Value "Hello" -Encoding UTF8
Add-Content "C:\output.txt" -Value "Appended"
Get-Process | Out-File "C:\procs.txt" -Width 200

# Copy/Move/Remove
Copy-Item "C:\Source\*" "C:\Dest\" -Recurse
Move-Item "C:\Temp\*.log" "C:\Archive\"
Remove-Item "C:\Temp\OldFolder" -Recurse -Force -WhatIf   # Test first!

# Create
New-Item "C:\Logs\Archive" -ItemType Directory -Force
New-Item "C:\Logs\new.log" -ItemType File -Force
```

---

## 10. Registry

<HARD-RULE>
Always back up registry keys before modification. Incorrect registry changes can render the system unbootable.
</HARD-RULE>

```powershell
# Read
Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion"
Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion"
Get-ItemPropertyValue "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion" -Name "ProgramFilesDir"
Test-Path "HKLM:\SOFTWARE\MyApp"

# Write
New-Item "HKLM:\SOFTWARE\MyApp" -Force
Set-ItemProperty "HKLM:\SOFTWARE\MyApp" -Name "Version" -Value "2.0"
New-ItemProperty "HKLM:\SOFTWARE\MyApp" -Name "Port" -Value 8080 -PropertyType DWord
New-ItemProperty "HKLM:\SOFTWARE\MyApp" -Name "Servers" -Value @("DC01","DC02") -PropertyType MultiString
Remove-ItemProperty "HKLM:\SOFTWARE\MyApp" -Name "OldSetting"
Remove-Item "HKLM:\SOFTWARE\MyApp" -Recurse -Force
```

Common paths: `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` (startup), `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*` (installed programs 64-bit), `HKLM:\SOFTWARE\WOW6432Node\...\Uninstall\*` (32-bit on 64-bit), `HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion` (Windows version).

---

## 11. String and Regex

```powershell
"Hello $name"                                    # Interpolation (double quotes)
'Hello $name'                                    # Literal (single quotes)
"Count: $((Get-Process).Count)"                  # Sub-expression
"Disk {0}: {1:N2} GB free" -f "C:", 42.567       # Format operator

"Hello World".ToUpper()
"Hello World".Replace("World", "PS")
"Hello World".Split(" ")
"  spaces  ".Trim()
$servers -join ", "

# Regex
"Server-DC01-Prod" -match "(\w+)-(\w+)-(\w+)"
$Matches[1]    # Server
$Matches[2]    # DC01

"2025-01-15" -match "(?<year>\d{4})-(?<month>\d{2})-(?<day>\d{2})"
$Matches.year  # 2025

"Log_2025_01_15.txt" -replace "\d{4}_\d{2}_\d{2}", "DATED"
"one;two,,three  four" -split "[;,\s]+"

# Select-String (grep equivalent)
Select-String -Path "C:\Logs\*.log" -Pattern "ERROR|CRITICAL"
Select-String -Path "C:\Logs\app.log" -Pattern "Exception" -Context 2,5
Get-ChildItem C:\Projects -Recurse -Filter "*.ps1" |
    Select-String "ConvertTo-SecureString"
```

---

## 12. Data Formats

### JSON

```powershell
$data = @{ Name = "Server01"; IP = "10.0.0.5"; Roles = @("DC","DNS"); Enabled = $true }
$json = $data | ConvertTo-Json -Depth 5
$config = Get-Content "C:\config.json" -Raw | ConvertFrom-Json
$data | ConvertTo-Json -Depth 5 | Set-Content "C:\config.json" -Encoding UTF8

# REST API
$response = Invoke-RestMethod -Uri "https://api.example.com/servers" `
    -Headers @{Authorization = "Bearer $token"}
$body = @{Name="NewServer"} | ConvertTo-Json
Invoke-RestMethod -Uri "https://api.example.com/servers" -Method Post `
    -Body $body -ContentType "application/json"
```

### CSV

```powershell
$users = Import-Csv "C:\Data\users.csv"
$data = Import-Csv "C:\Data\export.txt" -Delimiter "`t"
Get-Process | Select-Object Name, CPU, WorkingSet |
    Export-Csv "C:\Reports\processes.csv" -NoTypeInformation -Encoding UTF8
```

### XML

```powershell
[xml]$xml = Get-Content "C:\Data\config.xml"
$xml.configuration.appSettings.add | ForEach-Object { "$($_.key) = $($_.value)" }
$xml.SelectNodes("//server[@role='web']")
$xml.Save("C:\Data\servers.xml")
```

### Web Requests

```powershell
$response = Invoke-WebRequest -Uri "https://example.com" -UseBasicParsing
$response.StatusCode; $response.Headers; $response.Content
Invoke-WebRequest -Uri "https://example.com/file.zip" -OutFile "C:\Downloads\file.zip"
```

---

## 13. DSC (Desired State Configuration)

```powershell
Configuration WebServerSetup {
    param([string[]]$NodeName = "localhost")
    Import-DscResource -ModuleName PSDesiredStateConfiguration
    Node $NodeName {
        WindowsFeature IIS { Name = "Web-Server"; Ensure = "Present" }
        WindowsFeature IISMgmt {
            Name = "Web-Mgmt-Console"; Ensure = "Present"; DependsOn = "[WindowsFeature]IIS"
        }
        File WebContent {
            DestinationPath = "C:\inetpub\wwwroot\index.html"
            Contents = "<h1>Hello from DSC</h1>"; Ensure = "Present"; Type = "File"
            DependsOn = "[WindowsFeature]IIS"
        }
        Service W3SVC {
            Name = "W3SVC"; State = "Running"; StartupType = "Automatic"
            DependsOn = "[WindowsFeature]IIS"
        }
    }
}

WebServerSetup -NodeName "WEB01" -OutputPath "C:\DSC\WebServer"
Start-DscConfiguration -Path "C:\DSC\WebServer" -Wait -Verbose -Force
Get-DscConfigurationStatus
Test-DscConfiguration -Detailed
```

### LCM Settings

```powershell
[DSCLocalConfigurationManager()]
Configuration LCMSettings {
    Node "localhost" {
        Settings {
            RefreshMode = "Push"; ConfigurationMode = "ApplyAndAutoCorrect"
            ConfigurationModeFrequencyMins = 30; RebootNodeIfNeeded = $false
        }
    }
}
LCMSettings -OutputPath "C:\DSC\LCM"
Set-DscLocalConfigurationManager -Path "C:\DSC\LCM" -Verbose
```

---

## 14. Scheduled Tasks

```powershell
$trigger  = New-ScheduledTaskTrigger -Daily -At "02:00AM"
$action   = New-ScheduledTaskAction -Execute "pwsh.exe" `
    -Argument "-NoProfile -NonInteractive -File C:\Scripts\Backup.ps1"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -StartWhenAvailable

Register-ScheduledTask -TaskName "NightlyBackup" -TaskPath "\CustomTasks\" `
    -Trigger $trigger -Action $action -Settings $settings `
    -User "SYSTEM" -RunLevel Highest -Description "Nightly backup script"

# Manage
Get-ScheduledTask -TaskName "NightlyBackup"
Get-ScheduledTaskInfo -TaskName "NightlyBackup"
Start-ScheduledTask -TaskName "NightlyBackup"
Disable-ScheduledTask -TaskName "NightlyBackup"
Enable-ScheduledTask -TaskName "NightlyBackup"
Set-ScheduledTask -TaskName "NightlyBackup" `
    -Trigger (New-ScheduledTaskTrigger -Daily -At "03:00AM")
Unregister-ScheduledTask -TaskName "NightlyBackup" -Confirm:$false
```

---

## 15. Services

```powershell
Get-Service -Name "WinRM"
Get-Service -DisplayName "*Remote*"
Get-Service | Where-Object Status -eq "Running" | Sort-Object DisplayName

Start-Service "Spooler"
Stop-Service "Spooler" -Force
Restart-Service "W3SVC" -Force
Set-Service "Spooler" -StartupType Automatic

Get-Service "WinRM" -DependentServices
Get-Service "WinRM" -RequiredServices
Get-Service -ComputerName DC01 -Name "DNS"

New-Service -Name "MyService" -BinaryPathName "C:\Services\MyApp.exe" `
    -DisplayName "My Custom Service" -StartupType Automatic
Remove-Service -Name "MyService"           # PS 6+
# On 5.1: sc.exe delete "MyService"
```

---

## 16. Processes

```powershell
Get-Process -Name "chrome"
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10
Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 10 |
    Select-Object Name, @{N="MemMB";E={[math]::Round($_.WorkingSet/1MB)}}

Stop-Process -Name "notepad"
Stop-Process -Id 5678 -Force

Start-Process "notepad.exe"
Start-Process "setup.exe" -ArgumentList "/quiet /norestart" -Wait -Verb RunAs

$proc = Start-Process "ping.exe" -ArgumentList "8.8.8.8 -n 4" `
    -Wait -PassThru -NoNewWindow -RedirectStandardOutput "C:\output.txt"
$proc.ExitCode
```

---

## 17. Common Patterns

<HARD-RULE>
Never set `ExecutionPolicy` to `Unrestricted` on production servers. Prefer `RemoteSigned` for servers and `AllSigned` for locked-down environments. Use `Set-ExecutionPolicy -Scope Process` for temporary changes.
</HARD-RULE>

```powershell
Get-ExecutionPolicy -List
Set-ExecutionPolicy RemoteSigned -Scope LocalMachine
Set-ExecutionPolicy Bypass -Scope Process        # Current session only
```

<HARD-RULE>
Never hardcode passwords in scripts or store them in plain text. Use `Get-Credential`, Windows Credential Manager, Azure Key Vault, or `Export-Clixml` (DPAPI-protected, same user + machine only). `ConvertTo-SecureString -AsPlainText` with a hardcoded string defeats the purpose of SecureString.
</HARD-RULE>

```powershell
$cred = Get-Credential -UserName "DOMAIN\admin" -Message "Enter password"

# Export/import (DPAPI encrypted -- same user, same machine only)
Get-Credential | Export-Clixml "C:\Secure\cred.xml"
$cred = Import-Clixml "C:\Secure\cred.xml"

Invoke-Command -ComputerName DC01 -Credential $cred -ScriptBlock { hostname }
```

### Logging Function

```powershell
function Write-Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)]
        [string]$Message,
        [ValidateSet("INFO","WARN","ERROR","DEBUG")]
        [string]$Level = "INFO",
        [string]$LogPath = "C:\Logs\script.log"
    )
    process {
        $entry = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] [$Level] $Message"
        $dir = Split-Path $LogPath -Parent
        if (-not (Test-Path $dir)) { New-Item $dir -ItemType Directory -Force | Out-Null }
        Add-Content -Path $LogPath -Value $entry -Encoding UTF8
        switch ($Level) {
            "ERROR" { Write-Error $Message }
            "WARN"  { Write-Warning $Message }
            "DEBUG" { Write-Debug $Message }
            default { Write-Verbose $Message }
        }
    }
}
```

### Parameter Validation

```powershell
function Deploy-Application {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$AppName,
        [Parameter(Mandatory)][ValidateSet("Dev","Staging","Production")][string]$Environment,
        [ValidateRange(1,65535)][int]$Port = 8080,
        [ValidateScript({ Test-Path $_ -PathType Container })][string]$DeployPath = "C:\Apps",
        [ValidatePattern("^\d+\.\d+\.\d+$")][string]$Version = "1.0.0",
        [ValidateLength(1,50)][string]$Description,
        [ValidateCount(1,10)][string[]]$Servers
    )
    if ($PSCmdlet.ShouldProcess("$AppName v$Version", "Deploy to $Environment")) {
        # Deployment logic
    }
}
```

### Progress Bars

```powershell
$total = $servers.Count
for ($i = 0; $i -lt $total; $i++) {
    Write-Progress -Activity "Scanning" -Status "$($servers[$i]) ($($i+1)/$total)" `
        -PercentComplete ([math]::Round(($i/$total)*100))
    Get-CimInstance Win32_OperatingSystem -ComputerName $servers[$i] -EA SilentlyContinue
}
Write-Progress -Activity "Scanning" -Completed
```

### Parallel Execution (PS 7+)

```powershell
$results = $servers | ForEach-Object -Parallel {
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ComputerName $_ -EA Stop
        [PSCustomObject]@{ Server=$_; OS=$os.Caption; Status="Online" }
    } catch {
        [PSCustomObject]@{ Server=$_; OS="N/A"; Status="Offline" }
    }
} -ThrottleLimit 5

# Pass variables with $using:
$credential = Get-Credential
$servers | ForEach-Object -Parallel {
    Invoke-Command -ComputerName $_ -Credential $using:credential -ScriptBlock { hostname }
} -ThrottleLimit 10
```

### Script Template

```powershell
#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Brief description.
.PARAMETER ComputerName
    Target computers.
.EXAMPLE
    .\MyScript.ps1 -ComputerName DC01, DC02 -Verbose
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory, ValueFromPipeline)][string[]]$ComputerName,
    [string]$LogPath = "C:\Logs\MyScript_$(Get-Date -Format 'yyyyMMdd').log"
)
begin {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = "Stop"
}
process {
    foreach ($computer in $ComputerName) {
        try {
            if ($PSCmdlet.ShouldProcess($computer, "Run audit")) {
                Write-Verbose "Processing $computer"
            }
        } catch { Write-Warning "Failed on $computer : $($_.Exception.Message)" }
    }
}
end { Write-Verbose "Complete at $(Get-Date)" }
```

---

## Quick Reference: Comparison Operators

| Operator | Description | Example |
|---|---|---|
| `-eq` / `-ne` | Equal / Not equal | `5 -eq 5` |
| `-gt` / `-ge` | Greater than / Greater or equal | `5 -gt 3` |
| `-lt` / `-le` | Less than / Less or equal | `3 -lt 5` |
| `-like` / `-notlike` | Wildcard match | `"hello" -like "hel*"` |
| `-match` / `-notmatch` | Regex match | `"hello" -match "^hel"` |
| `-contains` / `-notcontains` | Array contains value | `@(1,2,3) -contains 2` |
| `-in` / `-notin` | Value in array | `2 -in @(1,2,3)` |
| `-is` / `-isnot` | Type check | `42 -is [int]` |
| `-replace` | Regex replace | `"abc" -replace "b","X"` |
| `-split` / `-join` | Split / Join | `"a,b" -split ","` |

All string operators are case-insensitive by default. Prefix with `c` for case-sensitive: `-ceq`, `-cmatch`, `-creplace`.

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `Write-Host` for output instead of `Write-Output` | Write-Host bypasses the pipeline; output cannot be captured, piped, or tested; breaks automation | Use Write-Output (or implicit output) for data; Write-Host only for interactive console formatting |
| Not using `-ErrorAction Stop` with try/catch | Non-terminating errors skip the catch block; script continues with corrupt state; errors go unhandled | Set `$ErrorActionPreference = 'Stop'` or use `-ErrorAction Stop` on cmdlets within try blocks |
| String concatenation instead of format operators | `"User " + $name + " created"` is fragile, hard to read, and breaks with null values | Use string interpolation: `"User $name created"` or `-f` operator: `"User {0} created" -f $name` |
| Running scripts without `Set-StrictMode -Version Latest` | Typos in variable names silently create new variables; missing properties return $null instead of error | Enable strict mode at script top; catches typos, uninitialized variables, and nonexistent properties |
| Using `Invoke-Expression` for dynamic commands | Security risk (code injection); difficult to debug; breaks when input contains special characters | Use splatting (`@params`), `Start-Process`, or the call operator (`&`) for dynamic execution |

---

## Related Skills

| Skill | Scope |
|---|---|
| `windows-ps-server-admin` | AD, DNS, DHCP, GPO, Hyper-V, IIS, failover clustering, storage, Windows Update management |
| `windows-ps-security` | ACLs, firewall rules, certificates, auditing, JEA, AppLocker, Defender, credential guard, security baselines |
| `windows-cmd` | Legacy CMD/batch scripting, native Windows commands, interop with PowerShell |
