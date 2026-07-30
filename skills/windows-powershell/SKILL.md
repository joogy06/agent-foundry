---
name: windows-powershell
description: Use when writing or debugging PowerShell scripts — PowerShell 7.x and Windows PowerShell 5.1 (including PS 5.1 BOM-less script encoding hazards, mojibake on non-ASCII chars, Windows-1252 default), pipeline and object manipulation, error handling (try/catch/ErrorAction, native-stderr silencing under $ErrorActionPreference='Stop'), advanced-function common-parameter conflicts (-Verbose / -v collision, "specified more than once"), native-command splatting (empty-string arg drop on PS 5.1), modules and package management (PSGallery), remoting (WinRM, SSH), Desired State Configuration (DSC), scheduled tasks, WMI/CIM queries, registry operations, file system operations (Split-Path -LiteralPath/-Parent parameter-set collision on PS 7.6), string/regex, JSON/XML/CSV handling, process management (Start-Process PID-without-health, tree-kill via Win32_Process BFS), and cross-platform considerations (Linux→Windows primitive porting, nohup / kill / pgrep equivalents). Parent skill for the windows-ps-* skill family.
family: windows
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

## 1.5 Encoding Hazards (PS 5.1 BOM-less trap)

The single most expensive parsing failure on Windows PowerShell 5.1: **PS 5.1 reads BOM-less `.ps1` files as Windows-1252, not UTF-8.** Any non-ASCII character (em-dash `—`, smart quotes `"" ''`, ellipsis `…`, non-breaking space) without a UTF-8 BOM produces mojibake and a cascade of parse errors:

```
Missing closing '}' in statement block
Unexpected token ')'
The string is missing the terminator: "
```

The actual root cause is hidden in the cascade noise — the FIRST error message names the right line; the parser then desyncs and reports 10+ irrelevant follow-ups. **Always look at the first error first.**

PowerShell 7+ defaults to UTF-8 even without a BOM, so the same file runs fine on `pwsh.exe`. Only Windows PowerShell 5.1 is affected.

### Diagnostic

```bash
# From Git Bash / WSL — find any non-ASCII bytes in your .ps1
grep -nP '[^\x00-\x7F]' install_helper.ps1
# Hit: 493:Write-Info "alembic stamp skipped (CLI not present yet — first boot ...
#                                                                       ^-- em-dash
```

```powershell
# From PowerShell itself — check for BOM
(Get-Content install_helper.ps1 -AsByteStream -TotalCount 4 | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
# 'EF BB BF ...' → file has UTF-8 BOM; PS 5.1 reads as UTF-8
# Anything else  → PS 5.1 reads as Windows-1252; any non-ASCII char will mojibake
```

### Recommended fix: ASCII-only

**ASCII-everywhere is the cheaper invariant.** Replace non-ASCII characters with ASCII equivalents:

```diff
- Write-Info "alembic stamp skipped (CLI not present yet — first boot will auto-upgrade)."
+ Write-Info "alembic stamp skipped (CLI not present yet -- first boot will auto-upgrade)."
```

**Do not "fix" by adding a UTF-8 BOM.** That works on the current file but masks the constraint — the next edit lands in a different `.ps1` without a BOM and the bug returns. ASCII-everywhere is one constraint defended once; BOM-everywhere requires defending it on every file touched.

### Probe ambiguity — "blocked by AppLocker" might be a parse error

When a `-ProbeOnly` / `--check` mode returns errorlevel 1, do NOT assume AppLocker / WDAC denial. A parse error in the probed helper (caused by mojibake, an unterminated string, or any other syntax issue) also fails the probe. If your caller silently `>nul 2>&1`'s the probe and routes through "execution blocked" remediation, the user never sees the real error.

When diagnosing a failed probe: temporarily drop `>nul 2>&1` and look at what the probed helper actually said. The first PS error message is the truth; the rest is desync noise.

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

### Advanced functions and the `-Verbose` collision trap

Adding `[Parameter()]` (or `[CmdletBinding()]`) to **any** parameter automatically promotes the script to an **advanced function**. PowerShell then auto-injects 11 common parameters:

```
-Verbose -Debug -ErrorAction -ErrorVariable -WarningAction -WarningVariable
-InformationAction -InformationVariable -OutVariable -OutBuffer -PipelineVariable
```

Any short flag you define that partial-matches one of these will be intercepted **before** your parameter sees it. The error message is misleading:

```
Cannot bind parameter because parameter 'v' is specified more than once.
```

What's actually happening: `-v` partial-matches `-Verbose`, gets bound once silently, then PS refuses the second occurrence — making it look like the user typed `-v` twice when they only typed it once.

**Unsafe custom flag names** (partial-match a common param):

| Custom flag | Conflicts with |
|---|---|
| `-v` | `-Verbose` |
| `-d` | `-Debug` |
| `-ea` | `-ErrorAction` |
| `-ev` | `-ErrorVariable` |
| `-wa` | `-WarningAction` |
| `-wv` | `-WarningVariable` |
| `-ia` | `-InformationAction` |
| `-iv` | `-InformationVariable` |
| `-ov` | `-OutVariable` |
| `-ob` | `-OutBuffer` |
| `-pv` | `-PipelineVariable` |

**Safe custom flag names** — pick names that don't prefix-match any common param: `-AppVerbose`, `-Quiet`, `-Loud`, `-DebugMode`, `-DryRun`, `-Strict`.

There is no opt-out: once a function is advanced, the common-param set is part of its surface. Plan flag names accordingly, or do parsing in a thin batch wrapper:

```batch
:: app.cmd — translate user-friendly -v to PowerShell-safe -AppVerbose
:parse_args
if "%~1"=="" goto run
if /I "%~1"=="-v"        ( set "PS_VERBOSE=-AppVerbose" & shift & goto parse_args )
if /I "%~1"=="--verbose" ( set "PS_VERBOSE=-AppVerbose" & shift & goto parse_args )
set "PS_REST=%PS_REST% %1"
shift
goto parse_args
```

### Empty-string arg drop on native splatting (PS 5.1)

Windows PowerShell 5.1 **silently drops** empty-string arguments when splatting to a native executable. Cmdlet splatting (`Get-ChildItem @params`) is unaffected — this hits only native exes:

```powershell
$a = @('-x', '', '-y', 'foo')
& cmd.exe /c echo @a
# Prints: -x -y foo
# Expected: -x  -y foo
```

PS 7+ does not have this bug. But if your script must run on PS 5.1 (and any installer script probably does), pass structured data via a **temp file**, not argv pairs:

```powershell
$tokens = @{
    '__SSL_KEY_FILE__'  = ''
    '__SSL_CERT_FILE__' = ''
    '__BIND_HOST__'     = '0.0.0.0'
}
$tokensFile = New-TemporaryFile
try {
    ($tokens | ConvertTo-Json -Depth 2) | Out-File -LiteralPath $tokensFile -Encoding utf8
    & $VenvPython -c $pyCode $ConfigTpl $ConfigFile $tokensFile.FullName
} finally {
    Remove-Item -LiteralPath $tokensFile -ErrorAction SilentlyContinue
}
```

Python-side: read with `encoding='utf-8-sig'` to absorb the BOM that PS 5.1 may inject when writing UTF-8 via `Out-File -Encoding utf8`.

Sidesteps both the empty-arg drop AND the ~32k argv-length ceiling on Windows.

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

### Silencing native-command stderr under `$ErrorActionPreference = 'Stop'`

Under `$ErrorActionPreference = 'Stop'`, any non-zero exit code or stderr write from a native command produces a `NativeCommandError` record that PowerShell promotes to a terminating error — aborting the script. This is correct most of the time, but hostile when calling a native tool whose stderr is noisy by design (e.g., `taskkill` writes to stderr even on successful kills).

**`2>$null` is NOT sufficient.** It redirects the stderr TEXT but the `NativeCommandError` record is still emitted to PS's error stream and still terminates under `Stop`.

The only reliable silencer in PS 5.1 is to **scope EAP locally AND redirect all streams to null**:

```powershell
&{
    $ErrorActionPreference = 'SilentlyContinue'
    & taskkill /F /PID $pid *>&1 | Out-Null
}
# Script continues here even if taskkill fails
```

The `&{...}` creates a temporary scope so the EAP change doesn't leak. `*>&1 | Out-Null` redirects EVERY stream (stdout, stderr, warning, info, debug, verbose) to the pipeline, then discards it. This is the canonical pattern for "I genuinely want to ignore this native tool's complaints."

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

### `Split-Path -LiteralPath … -Parent` parameter-set collision (PS 7.6)

On **PowerShell 7.6.x**, combining `-LiteralPath` with `-Parent` throws
`Parameter set cannot be resolved using the specified named parameters` —
the two parameters resolve to colliding parameter sets in this version
(field-confirmed on 7.6.1; positional/`-Path` form is unaffected).

```powershell
# BROKEN on PS 7.6.x:
$dir = Split-Path -LiteralPath $MyInvocation.MyCommand.Path -Parent

# Safe alternatives:
$dir = Split-Path $script:SomePath -Parent      # positional -Path binding
$dir = $PSScriptRoot                            # script's own directory — preferred
$dir = [System.IO.Path]::GetDirectoryName($p)   # .NET, no parameter sets at all
```

For "directory containing this script", always prefer `$PSScriptRoot` — it
sidesteps the collision entirely and works on PS 3.0+.

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

### Detached `Start-Process` exit code is not a health signal

`Start-Process` without `-Wait` returns as soon as the child has a **PID**. The child can crash microseconds later — exit code stays 0 and you never find out unless you check explicitly:

```powershell
$proc = Start-Process "myapp.exe" -PassThru -NoNewWindow
Start-Sleep -Seconds 2
if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
    Write-Error "myapp exited within 2 seconds — check the log"
}
# For HTTP services, also probe the endpoint:
try { Invoke-WebRequest "http://localhost:8080/health" -UseBasicParsing | Out-Null }
catch { Write-Error "myapp PID alive but not serving HTTP" }
```

Pair detached `Start-Process` (no `-Wait`) with a status + health probe in any wrapper script. The exit code is "the OS launched the process," not "the process is healthy."

### Killing a process tree on Windows

Windows has no POSIX-style process group; `kill -9 -<pgid>` has no direct equivalent. `taskkill /T /PID <pid>` walks the tree but **bails on the first child it can't terminate** — leaving the chain partially alive.

The reliable pattern is BFS over `Win32_Process` + bottom-up `Stop-Process -Force`:

```powershell
function Stop-ProcessTree {
    param([Parameter(Mandatory)][int]$RootPid, [int]$GraceSeconds = 5)

    # Phase 1: try the polite path first
    &{ $ErrorActionPreference = 'SilentlyContinue'; & taskkill /PID $RootPid *>&1 | Out-Null }

    # Phase 2: wait up to GraceSeconds for the root to exit
    $deadline = (Get-Date).AddSeconds($GraceSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $RootPid -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 200
    }

    # Phase 3: BFS the descendant tree, force-kill bottom-up
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($RootPid)
    $toKill = New-Object System.Collections.Generic.List[int]
    while ($queue.Count -gt 0) {
        $p = $queue.Dequeue()
        $toKill.Add($p) | Out-Null
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$p" |
            ForEach-Object { $queue.Enqueue([int]$_.ProcessId) }
    }
    # Reverse so leaves die before their parents (prevents re-spawn during sweep)
    $toKill.Reverse()
    foreach ($p in $toKill) {
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}
```

**Canonical case**: Werkzeug's reloader (`debug=True`) runs 3-4 processes — re-launcher → supervisor → worker → optionally a debugger child. Any process-management design that assumes a single PID under the `.pid` file leaks processes on debug. Tree-walk is mandatory on Windows, not optional. `debug=False` runs as a single process; the tree-walk pattern handles both correctly.

### Linux → Windows process primitive mapping

When porting a `.sh` / cron-style script to Windows, the mapping is rarely 1:1. Common substitutions:

| POSIX | Windows / PowerShell |
|---|---|
| `nohup foo &` | `Start-Process foo -WindowStyle Hidden` |
| `kill -0 $pid` (existence probe) | `Get-Process -Id $pid -ErrorAction SilentlyContinue` |
| `kill $pid` (TERM) | `taskkill /PID $pid` |
| `kill -9 $pid` (KILL) | `taskkill /F /PID $pid` (then `Stop-Process -Id $pid -Force` if persistent) |
| `pgrep -f 'pattern'` | `Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%pattern%'"` |
| `kill -9 -<pgid>` (kill group) | BFS via `Win32_Process` + `ParentProcessId`; see `Stop-ProcessTree` above |
| `source .env` | parse the file + `[Environment]::SetEnvironmentVariable($k, $v, 'Process')` |
| `which foo` | `Get-Command foo -ErrorAction SilentlyContinue` |
| `chmod +x foo` | n/a — Windows has no execute bit; file extension drives behavior |
| `ln -s` | `New-Item -ItemType SymbolicLink` (requires admin or developer-mode) |
| `xargs -P N` | `ForEach-Object -Parallel` (PS 7+ only) or `Start-Job` (PS 5.1) |

Don't assume parity — smoke-test each mapping before relying on it in a stop / restart / health script.

### Cross-language: `subprocess.Popen` and `.cmd` files

Python's `subprocess.Popen([script.cmd, ...], shell=False)` fails on Windows with `OSError: [WinError 193] %1 is not a valid Win32 application`. `CreateProcess` requires a PE-format executable; batch files only run through `cmd.exe`.

Two fixes:
```python
# Either (shell=True; convenient but shell-quoting hazards):
subprocess.Popen([script_path, *args], shell=True)

# Or (explicit; no shell-injection surface):
subprocess.Popen(['cmd', '/c', script_path, *args])
```

The `cmd /c start "" /B` quoting trick is fragile — the first quoted arg is the window TITLE, not the executable:

```batch
cmd /c start "" /B ""C:\path\with spaces\app.cmd"" arg1 arg2
::         ^^   ^^^^                                        ^^^^
::         |    +-- DOUBLE double-quotes inside cmd /c "..."
::         +-- empty title; without this, the path becomes the title and is swallowed
```

When the outer `cmd /c "..."` is itself quoted, embedded paths need **doubled** double-quotes to survive `cmd.exe`'s de-quoting pass. The `cmd /c start /B` pattern is the standard "spawn a detached grandchild" trick — useful when your own stop-walker would otherwise kill any direct child of your script.

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
