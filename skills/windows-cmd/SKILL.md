---
name: windows-cmd
description: Use when writing CMD batch scripts or using Windows Command Prompt — batch file syntax (.bat/.cmd), CRLF line-ending requirements, .gitattributes last-match-wins traps, parser-error diagnostics ("X was unexpected at this time"), paren escaping inside IF/FOR blocks, environment variables, FOR loops, IF conditionals, pipes and redirection, common system commands (net, netsh, wmic, sfc, dism, robocopy, icacls, diskpart, bcdedit), file operations, networking diagnostics, and system administration from the command line. Part of the windows-* skill family.
family: windows
---

# Windows CMD / Batch Scripting

Reference for CMD.exe batch files (.bat/.cmd) and interactive Command Prompt usage on Windows 10/11 and Windows Server 2016+. For PowerShell equivalents, see companion skill `windows-powershell`.

<HARD-RULE>
Never run destructive commands (`del /s /q`, `rd /s /q`, `format`, `diskpart clean`, `bcdedit /delete`) without explicit user confirmation. Always verify target paths with `dir` and `echo` the command first.
</HARD-RULE>

<HARD-RULE>
Always test batch scripts with `echo` prefixed to destructive lines (dry-run) before live execution. Remove `echo` only after confirming correctness.
</HARD-RULE>

<HARD-RULE>
`.cmd` and `.bat` files MUST be checked into git with CRLF line endings. LF-only batch files silently fail with cryptic `X was unexpected at this time.` parser errors before any logic runs. See "Critical: Parsing Hazards & Line Endings" below.
</HARD-RULE>

---

## Critical: Parsing Hazards & Line Endings (read first)

Two failure modes account for the vast majority of `X was unexpected at this time.` errors from `cmd.exe`. Diagnose them BEFORE inspecting logic.

### CRLF requirement

`cmd.exe` requires **CR+LF (`\r\n`)** line endings to recognize line boundaries inside multi-line constructs (`IF (...) (...) ELSE (...)`, label blocks, parenthesized groups). LF-only files silently concatenate lines and trip the parser on the next token — usually a `.` from a path or filename — producing the cryptic `X was unexpected at this time.` error.

PowerShell `.ps1` files tolerate both endings. Batch `.cmd` / `.bat` files do not.

**Diagnostic** (run from Git Bash or WSL):
```bash
git ls-files --eol install.cmd
# Healthy:  i/lf    w/crlf    attr/text eol=crlf      install.cmd
# Broken:   i/lf    w/lf      attr/text=auto eol=lf   install.cmd
```

Or check the raw bytes:
```bash
head -c 200 install.cmd | xxd | head -5
# Healthy ends each line with: ... 0d 0a
# Broken ends with: ... 0a
```

### `.gitattributes` last-match-wins trap

A common cross-platform `.gitattributes` includes a catch-all like:
```
* text=auto eol=lf
```

This forces EVERY text file — including `.cmd` and `.bat` — to LF on checkout. Add explicit overrides **AFTER** the catch-all (gitattributes evaluates rules in order, last match wins):

```
* text=auto eol=lf

# Windows scripts MUST be CRLF — override the catch-all above
*.cmd  text eol=crlf
*.bat  text eol=crlf
*.ps1  text eol=crlf
```

After fixing `.gitattributes`, force the working tree to re-materialize the file:
```bash
rm install.cmd
git checkout -- install.cmd
git ls-files --eol install.cmd   # Verify w/crlf
```

`git add --renormalize install.cmd` is **NOT sufficient** — it updates the index but leaves the working-tree copy at the old EOL. `cmd.exe` reads the working copy, so the delete-and-checkout is mandatory.

### "X was unexpected at this time" — diagnostic order

When `cmd.exe` prints `. was unexpected at this time.` / `or was unexpected at this time.` / similar:

1. **Check EOL first.** `git ls-files --eol script.cmd`. If `w/lf`, fix per above.
2. **Check for unescaped `(` / `)` inside `echo` / `set` inside an `IF (...)` or `FOR (...)` body.** A bare `)` inside the body closes the outer block prematurely. See §3 IF Conditionals for the worked example.
3. **Check for orphan `:` labels inside parenthesized blocks.** `:label` lines do not exist inside `(...)` groups; they're parsed differently.
4. **Only after ruling out 1-3, suspect logic.** The error is almost never a logic bug.

---

## 1. Batch File Fundamentals

### Minimal Template

```bat
@echo off
setlocal enabledelayedexpansion
rem ── Script: deploy.bat ──
rem Purpose: <describe>
rem Author:  <name>  Date: %DATE%

:: --- main logic ---
call :Main %*
exit /b %ERRORLEVEL%

:Main
    echo Running from: %~dp0
    echo Script name:  %~nx0
    pause
    exit /b 0
```

### Key Directives

```bat
@echo off                  &rem Suppress command echoing
echo on                    &rem Re-enable echoing (debugging)
rem This is a comment      &rem Official comment keyword
:: This is also a comment  &rem Label-style comment (do NOT use inside FOR/IF blocks)
pause                      &rem "Press any key to continue..."
pause >nul                 &rem Pause without message text
exit /b 0                  &rem Exit script/subroutine with return code 0
exit /b 1                  &rem Exit with error code
```

### setlocal / endlocal

```bat
@echo off
set OUTER=hello
setlocal
    set INNER=world
    echo %OUTER% %INNER%   &rem hello world
endlocal
echo %OUTER%               &rem hello
echo %INNER%               &rem (empty — INNER is gone)
```

### Delayed Expansion

```bat
@echo off
setlocal enabledelayedexpansion
set COUNT=0
for %%F in (*.txt) do (
    set /a COUNT+=1
    echo !COUNT!: %%F       &rem !VAR! reads current value inside block
)
echo Total: !COUNT!
endlocal
```

### Path Expansion Modifiers (`%~` syntax)

```bat
rem Given: call script.bat "C:\Users\admin\report.docx"
echo Full path:      %~f1       &rem C:\Users\admin\report.docx
echo Drive:          %~d1       &rem C:
echo Path only:      %~p1       &rem \Users\admin\
echo Drive+Path:     %~dp1      &rem C:\Users\admin\
echo Filename only:  %~n1       &rem report
echo Extension:      %~x1       &rem .docx
echo Name+Ext:       %~nx1      &rem report.docx
echo Script dir:     %~dp0      &rem Directory where THIS script lives
echo File size:      %~z1       &rem Size in bytes
```

### Labels, GOTO, and CALL

```bat
@echo off
goto :Start

:Usage
    echo Usage: %~nx0 [install^|uninstall]
    exit /b 1

:Start
    if "%~1"=="" goto :Usage
    if /i "%~1"=="install"   call :Install
    if /i "%~1"=="uninstall" call :Uninstall
    exit /b 0

:Install
    echo Installing...
    exit /b 0

:Uninstall
    echo Uninstalling...
    exit /b 0
```

### ERRORLEVEL Handling

```bat
@echo off
some_command.exe
if %ERRORLEVEL% neq 0 (
    echo ERROR: Command failed with code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

rem Shorthand — "if errorlevel N" means >= N
if errorlevel 1 echo Failed

rem Combined with logical operators
command1.exe && echo Success || echo Failed
command1.exe && command2.exe && command3.exe
```

---

## 2. Variables

### SET Basics

```bat
rem Simple assignment (no spaces around =)
set MYVAR=Hello World
echo %MYVAR%

rem Prompt user for input
set /p USERNAME=Enter your name:
echo Hello, %USERNAME%

rem Arithmetic
set /a RESULT=5+3
set /a RESULT=%RESULT%*2
set /a X=10, Y=20, SUM=X+Y
echo %SUM%

rem Clear a variable
set MYVAR=
```

### Common Environment Variables

```bat
echo Computer:   %COMPUTERNAME%
echo User:       %USERNAME%
echo Domain:     %USERDOMAIN%
echo Profile:    %USERPROFILE%
echo Home drive: %HOMEDRIVE%%HOMEPATH%
echo AppData:    %APPDATA%
echo LocalApp:   %LOCALAPPDATA%
echo Temp:       %TEMP%
echo WinDir:     %WINDIR%
echo SysRoot:    %SYSTEMROOT%
echo SysDrive:   %SYSTEMDRIVE%
echo ProgramW6432: %ProgramW6432%
echo ProgramFiles: %ProgramFiles%
echo ProgramX86: %ProgramFiles(x86)%
echo PATH:       %PATH%
echo PATHEXT:    %PATHEXT%
echo Processor:  %PROCESSOR_ARCHITECTURE%
echo NumCPUs:    %NUMBER_OF_PROCESSORS%
echo Date:       %DATE%
echo Time:       %TIME%
```

### String Operations

```bat
set STR=Hello World

rem Substring: %VAR:~start,length%
echo %STR:~0,5%        &rem Hello
echo %STR:~6%          &rem World
echo %STR:~-5%         &rem World
echo %STR:~0,-6%       &rem Hello

rem Substitution: %VAR:old=new%
echo %STR:World=Earth%  &rem Hello Earth
echo %STR: =%           &rem HelloWorld (remove spaces)

rem String length (common trick)
setlocal enabledelayedexpansion
set "S=Hello"
set "LEN=0"
for /l %%i in (0,1,255) do if "!S:~%%i,1!" neq "" set /a LEN+=1
echo Length: %LEN%
endlocal
```

---

## 3. Control Flow

### IF Conditionals

```bat
rem String comparison (case-sensitive by default)
if "%VAR%"=="value" echo Match
if /i "%VAR%"=="VALUE" echo Case-insensitive match
if not "%VAR%"=="value" echo No match

rem Numeric comparison
if %NUM% equ 10 echo Equal
if %NUM% neq 10 echo Not equal
if %NUM% gtr 5  echo Greater
if %NUM% geq 5  echo Greater or equal
if %NUM% lss 5  echo Less
if %NUM% leq 5  echo Less or equal

rem File/directory existence
if exist "C:\file.txt" echo File found
if exist "C:\folder\" echo Directory found
if not exist "C:\file.txt" echo Not found

rem Defined check
if defined MYVAR echo Variable is set
if not defined MYVAR echo Variable is not set

rem ERRORLEVEL
if %ERRORLEVEL% equ 0 (
    echo Success
) else (
    echo Failure: %ERRORLEVEL%
)

rem Combined with else (parentheses placement matters)
if exist "config.ini" (
    echo Loading config...
    call :LoadConfig
) else (
    echo No config found, using defaults.
    call :UseDefaults
)
```

### Parens inside echo inside IF blocks — the silent killer

`cmd.exe`'s parser treats an unescaped `)` inside an IF/FOR body as the closing paren of the **outer** block, exiting prematurely. This is one of the most frequent causes of `X was unexpected at this time.`

**Broken** (real-world example):
```bat
if errorlevel 1 (
    echo Try these workarounds:
    echo   1. Ask IT to allow-list the script in AppLocker.
    echo   2. Use the pure-batch installer pattern from process-assistent-ai
    echo      (not currently shipped for smart-analyst — file an issue).
    exit /b 1
)
```

The `(` and `)` in `(not currently shipped ... file an issue)` close the outer IF at the inner `)`, leaving the trailing `.` as a stray token → `. was unexpected at this time.` The actual remediation message is never printed.

**Fix A** — caret-escape the parens:
```bat
echo      ^(not currently shipped for smart-analyst -- file an issue^).
```

**Fix B** (preferred — more readable) — rephrase to remove parens:
```bat
echo      not currently shipped for smart-analyst -- file an issue.
```

The same hazard applies to `set` lines and any inner command containing literal `(` / `)`. When in doubt, caret-escape or rephrase.

### FOR Loops

```bat
rem Iterate over a set of values
for %%V in (alpha beta gamma) do echo %%V

rem Iterate over files in a directory
for %%F in (C:\logs\*.log) do echo %%F

rem /L — numeric range: (start, step, end)
for /l %%i in (1,1,10) do echo %%i

rem /R — recursive file search
for /r "C:\projects" %%F in (*.txt) do echo %%F

rem /D — directories only
for /d %%D in (C:\Users\*) do echo %%D

rem /F — parse command output
for /f "tokens=*" %%L in ('dir /b *.txt') do echo File: %%L

rem /F — parse with delimiters and multiple tokens
for /f "tokens=1,2,3 delims=," %%A in (data.csv) do (
    echo Col1=%%A  Col2=%%B  Col3=%%C
)

rem /F — skip header lines
for /f "skip=1 tokens=1-3 delims=," %%A in (data.csv) do echo %%A %%B %%C

rem /F — parse command output (usebackq for commands in backticks)
for /f "usebackq tokens=*" %%L in (`hostname`) do set HOSTNAME=%%L

rem /F — iterate over lines in a string variable
set "LIST=one two three"
for %%W in (%LIST%) do echo %%W
```

---

## 4. File Operations

### Basic File Commands

```bat
rem Copy files
copy "source.txt" "dest.txt"
copy "source.txt" "C:\backup\" /y        &rem /y suppress overwrite prompt
copy /b file1+file2 combined.bin          &rem Binary concatenation

rem Move / rename
move "old.txt" "new.txt"
move "C:\temp\*.log" "C:\archive\"

rem Create directories
mkdir "C:\data\reports\2024"              &rem Creates full path

rem Delete files
del "C:\temp\*.tmp" /q                    &rem /q quiet mode
del "C:\temp\*.log" /f /q                 &rem /f force read-only deletion
```

<HARD-RULE>
`del /s /q` and `rd /s /q` are recursive and irreversible. Always echo the target path and confirm before execution.
```bat
rem SAFE: echo first to verify
echo Will delete: C:\temp\old_data
rd /s /q "C:\temp\old_data"
```
</HARD-RULE>

```bat
rem Remove directory tree
rd /s /q "C:\temp\old_data"

rem Directory listing
dir                                       &rem Current directory
dir /b                                    &rem Bare format (names only)
dir /s /b "C:\projects\*.py"             &rem Recursive bare listing
dir /a:d                                  &rem Directories only
dir /a:h                                  &rem Hidden files
dir /o:d                                  &rem Sorted by date
dir /o:-s                                 &rem Sorted by size descending

rem File attributes
attrib +r "file.txt"                      &rem Set read-only
attrib -r "file.txt"                      &rem Remove read-only
attrib +h +s "hidden.dat"                 &rem Hidden + system
attrib -h -s "hidden.dat" /s /d           &rem Recursive removal

rem Compare files
fc /b file1.bin file2.bin                 &rem Binary comparison
comp file1.txt file2.txt                  &rem Byte-by-byte

rem Symbolic links (requires elevation)
mklink "link.txt" "C:\real\target.txt"              &rem File symlink
mklink /d "linkdir" "C:\real\targetdir"              &rem Directory symlink
mklink /h "hardlink.txt" "C:\real\target.txt"        &rem Hard link
mklink /j "junction" "C:\real\targetdir"             &rem Junction (directory)
```

### XCOPY

```bat
rem Copy directory tree
xcopy "C:\source" "D:\dest" /e /i /h /y
rem /e include empty dirs  /i assume dest is dir  /h hidden files  /y no prompt
```

### ROBOCOPY (Robust File Copy)

```bat
rem Mirror a directory (destination matches source exactly)
robocopy "C:\source" "D:\dest" /mir /r:3 /w:5 /log:"copy.log"

rem Copy with retries and multithreading
robocopy "C:\source" "D:\dest" /e /r:3 /w:5 /mt:16 /np
rem /e subdirs  /r:N retries  /w:N wait sec  /mt:N threads  /np no progress

rem Copy only specific file types
robocopy "C:\source" "D:\dest" *.docx *.xlsx /s

rem Exclude directories and files
robocopy "C:\source" "D:\dest" /e /xd "node_modules" ".git" /xf "*.tmp" "thumbs.db"

rem Move files (copy then delete source)
robocopy "C:\source" "D:\dest" /move /e

rem Common exit codes: 0=no files copied, 1=files copied, 2=extras in dest
rem Codes 0-7 are generally success; 8+ indicate errors
if %ERRORLEVEL% geq 8 echo ROBOCOPY ERROR: %ERRORLEVEL%
```

---

## 5. Networking

### Diagnostics

```bat
rem IP configuration
ipconfig                                  &rem Basic IP info
ipconfig /all                             &rem Full adapter details
ipconfig /release                         &rem Release DHCP lease
ipconfig /renew                           &rem Renew DHCP lease
ipconfig /flushdns                        &rem Clear DNS cache
ipconfig /displaydns                      &rem Show cached DNS entries

rem Connectivity tests
ping 8.8.8.8 -n 4                         &rem 4 pings
ping -t 192.168.1.1                       &rem Continuous ping (Ctrl+C to stop)
ping -a 192.168.1.100                     &rem Resolve hostname

rem Route tracing
tracert 8.8.8.8
tracert -d 10.0.0.1                       &rem Skip DNS resolution (faster)
pathping 8.8.8.8                          &rem Combined ping+tracert statistics

rem DNS lookup
nslookup example.com
nslookup -type=MX example.com
nslookup example.com 8.8.8.8             &rem Query specific DNS server

rem Connection table
netstat -an                               &rem All connections, numeric
netstat -ano                              &rem Include PID
netstat -ab                               &rem Show owning process (elevated)
netstat -s                                &rem Protocol statistics

rem ARP and routing
arp -a                                    &rem Show ARP cache
route print                               &rem Full routing table
route add 10.10.0.0 mask 255.255.0.0 192.168.1.1    &rem Add static route
route delete 10.10.0.0                    &rem Remove route
```

### NETSH

```bat
rem Show firewall rules
netsh advfirewall firewall show rule name=all

rem Add firewall rule (allow inbound port 8080)
netsh advfirewall firewall add rule name="Allow 8080" ^
    dir=in action=allow protocol=tcp localport=8080

rem Remove firewall rule
netsh advfirewall firewall delete rule name="Allow 8080"

rem Turn firewall on/off (all profiles)
netsh advfirewall set allprofiles state on
netsh advfirewall set allprofiles state off

rem Show interface configuration
netsh interface ipv4 show config
netsh interface ipv4 show addresses

rem Set static IP
netsh interface ipv4 set address name="Ethernet" ^
    static 192.168.1.100 255.255.255.0 192.168.1.1

rem Set DNS
netsh interface ipv4 set dns name="Ethernet" static 8.8.8.8 primary
netsh interface ipv4 add dns name="Ethernet" 8.8.4.4 index=2

rem Set back to DHCP
netsh interface ipv4 set address name="Ethernet" dhcp
netsh interface ipv4 set dns name="Ethernet" dhcp

rem Wi-Fi profiles
netsh wlan show profiles
netsh wlan show profile name="MyNetwork" key=clear
netsh wlan disconnect
netsh wlan connect name="MyNetwork"

rem Export/import netsh config
netsh advfirewall export "C:\backup\firewall.wfw"
netsh advfirewall import "C:\backup\firewall.wfw"
```

### NET Commands

```bat
rem Map network drive
net use Z: \\server\share /user:DOMAIN\user password /persistent:yes
net use Z: /delete

rem List mapped drives
net use

rem User management (local)
net user                                  &rem List users
net user jdoe /add /passwordreq:yes       &rem Create user
net user jdoe NewP@ssw0rd                 &rem Change password
net user jdoe /active:no                  &rem Disable account
net user jdoe /delete                     &rem Delete user

rem Group management
net localgroup                            &rem List groups
net localgroup Administrators             &rem Show members
net localgroup Administrators jdoe /add   &rem Add user to group
net localgroup Administrators jdoe /delete

rem Shared folders
net share                                 &rem List shares
net share Data=C:\SharedData /grant:Everyone,READ
net share Data /delete

rem Sessions and open files
net session                               &rem Active SMB sessions
net file                                  &rem Open shared files
```

---

## 6. System Administration

### System Info

```bat
systeminfo                                &rem Full system details
systeminfo | findstr /i "boot time"       &rem Last boot
hostname
ver                                       &rem Windows version string
```

### SFC and DISM (System Repair)

```bat
rem System File Checker — scan and repair protected files
sfc /scannow
sfc /verifyonly                           &rem Scan but do not repair

rem DISM — service the Windows image
dism /online /cleanup-image /scanhealth       &rem Quick scan
dism /online /cleanup-image /checkhealth      &rem Check for flagged corruption
dism /online /cleanup-image /restorehealth    &rem Repair from Windows Update

rem DISM — specify a source for repairs (install media)
dism /online /cleanup-image /restorehealth /source:D:\sources\install.wim

rem DISM — optional features
dism /online /get-features | more
dism /online /enable-feature /featurename:TelnetClient /all
dism /online /disable-feature /featurename:TelnetClient
```

### CHKDSK

```bat
rem Check disk (read-only)
chkdsk C:

rem Fix errors (requires reboot for system volume)
chkdsk C: /f

rem Full surface scan + fix
chkdsk D: /r
```

### DISKPART (Scripted)

<HARD-RULE>
DISKPART operations are DESTRUCTIVE and IRREVERSIBLE. `clean` wipes the entire partition table. Always verify the disk number with `list disk` before running any write operation. Never script `select disk` + `clean` without explicit user confirmation.
</HARD-RULE>

```bat
rem List disks interactively
echo list disk | diskpart

rem Scripted: create a partition on disk 2
(
echo select disk 2
echo clean
echo create partition primary
echo format fs=ntfs label="Data" quick
echo assign letter=E
) > "%TEMP%\dp_script.txt"
diskpart /s "%TEMP%\dp_script.txt"

rem Extend a volume
(
echo select volume 3
echo extend
) > "%TEMP%\dp_extend.txt"
diskpart /s "%TEMP%\dp_extend.txt"
```

### BCDEDIT (Boot Configuration)

```bat
rem View current boot configuration
bcdedit /enum

rem Set default OS (use identifier from /enum)
bcdedit /default {current}

rem Set boot timeout
bcdedit /timeout 10

rem Enable Safe Mode on next boot
bcdedit /set {current} safeboot minimal
rem Revert:
bcdedit /deletevalue {current} safeboot
```

### WMIC (Windows Management Instrumentation) — DEPRECATED

> **DEPRECATION (verified 2026-06-10):** WMIC is deprecated since Windows 10 21H1. On
> Windows 11 24H2 it is a Feature on Demand that is **NOT installed by default**, and it is
> **removed entirely in Windows 11 25H2**. Do NOT write new scripts that call `wmic` — they
> will fail with `'wmic' is not recognized` on current Windows. The replacement from batch
> is PowerShell's `Get-CimInstance`, invoked via `powershell -NoProfile -Command "..."`.
> The legacy commands further below are reference for READING/maintaining old scripts only.

```bat
rem ── Batch-callable replacements (use these in NEW scripts) ──────────────
rem OS info (replaces: wmic os get Caption,Version,BuildNumber,OSArchitecture)
powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture | Format-List"

rem Capture a single CIM value into a batch variable
rem (replaces the old `for /f ... ('wmic ... /format:list')` parsing pattern)
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).Version"') do set OSVER=%%I
echo %OSVER%
```

> **HAZARD — `wmic product get` / `Win32_Product`:** enumerating the `Win32_Product` class
> (via `wmic product get ...` OR `Get-CimInstance Win32_Product`) triggers msiexec
> consistency checks that RECONFIGURE/repair every MSI package on the machine — it is slow,
> floods the event log, and can break installations. **NEVER query `Win32_Product` in
> production.** List installed software from the registry Uninstall keys instead:
>
> ```bat
> rem Installed software — safe replacements for "wmic product get"
> powershell -NoProfile -Command "Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where-Object DisplayName | Select-Object DisplayName,DisplayVersion,Publisher | Sort-Object DisplayName"
> rem Pure-CMD variant:
> reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /v DisplayName
> ```

Legacy WMIC commands — for reading/maintaining OLD scripts only. Each line shows the
`Get-CimInstance` class to migrate to:

```bat
rem OS info                       -> Get-CimInstance Win32_OperatingSystem
wmic os get Caption,Version,BuildNumber,OSArchitecture /format:list

rem BIOS info                     -> Get-CimInstance Win32_BIOS
wmic bios get Manufacturer,SMBIOSBIOSVersion,ReleaseDate

rem CPU info                      -> Get-CimInstance Win32_Processor
wmic cpu get Name,NumberOfCores,NumberOfLogicalProcessors

rem Disk info                     -> Get-CimInstance Win32_DiskDrive / Win32_LogicalDisk
wmic diskdrive get Model,Size,MediaType,Status
wmic logicaldisk get DeviceID,FreeSpace,Size,FileSystem,VolumeName

rem Memory                        -> Get-CimInstance Win32_PhysicalMemory
wmic memorychip get Capacity,Speed,Manufacturer,PartNumber

rem Process management            -> Get-CimInstance Win32_Process / Stop-Process
wmic process list brief
wmic process where "name='notepad.exe'" get ProcessId,CommandLine
wmic process where "ProcessId=1234" call terminate

rem Installed software — DO NOT RUN (Win32_Product hazard above; use registry keys)
rem wmic product get Name,Version,Vendor /format:csv > software.csv

rem Services                      -> Get-CimInstance Win32_Service / Get-Service
wmic service where "state='running'" get Name,DisplayName,State

rem Startup programs              -> Get-CimInstance Win32_StartupCommand
wmic startup get Caption,Command,Location
```

### Shutdown and Restart

```bat
shutdown /s /t 0                          &rem Immediate shutdown
shutdown /r /t 0                          &rem Immediate restart
shutdown /r /t 300 /c "Restarting in 5 minutes for updates"
shutdown /a                               &rem Abort pending shutdown
shutdown /l                               &rem Log off current user
shutdown /r /o /t 0                       &rem Restart to Advanced Startup Options
```

### Group Policy

```bat
gpupdate /force                           &rem Force policy refresh
gpresult /r                               &rem Summary of applied policies
gpresult /h "C:\temp\gp_report.html"      &rem HTML report
gpresult /user DOMAIN\jdoe /r             &rem For specific user
```

---

## 7. Permissions

### ICACLS

```bat
rem View permissions
icacls "C:\Data"
icacls "C:\Data" /t                       &rem Recursive

rem Grant permissions
rem Rights: F=Full, M=Modify, RX=Read+Execute, R=Read, W=Write
icacls "C:\Data" /grant Users:(OI)(CI)M          &rem Modify, inherit to children
icacls "C:\Data" /grant "DOMAIN\jdoe":(OI)(CI)F  &rem Full control

rem Deny permissions
icacls "C:\Data" /deny "Guest":(OI)(CI)W

rem Remove permissions
icacls "C:\Data" /remove "Guest"

rem Inheritance flags
rem (OI) = Object Inherit   — files in folder inherit
rem (CI) = Container Inherit — subfolders inherit
rem (IO) = Inherit Only      — does not apply to this folder itself
rem (NP) = No Propagate     — only immediate children inherit

rem Reset to inherited permissions
icacls "C:\Data" /reset /t /c             &rem /t recursive  /c continue on error

rem Save and restore permissions
icacls "C:\Data" /save "perms.txt" /t
icacls "C:\" /restore "perms.txt"

rem Replace owner
icacls "C:\Data" /setowner "Administrators" /t /c
```

### TAKEOWN

```bat
rem Take ownership of a file
takeown /f "C:\LockedFile.txt"

rem Take ownership recursively
takeown /f "C:\LockedFolder" /r /d y

rem Take ownership as Administrators group
takeown /f "C:\LockedFolder" /a /r /d y
```

---

## 8. Services

### SC (Service Control)

```bat
rem Query services
sc query                                  &rem All running services
sc query state= all                       &rem All services (running + stopped)
sc query "wuauserv"                       &rem Specific service (Windows Update)
sc qc "wuauserv"                          &rem Configuration details

rem Start / Stop / Restart
sc start "wuauserv"
sc stop "wuauserv"
rem No native restart — stop then start:
sc stop "MyService" && timeout /t 3 >nul && sc start "MyService"

rem Change startup type
sc config "wuauserv" start= auto          &rem Automatic
sc config "wuauserv" start= delayed-auto  &rem Delayed auto
sc config "wuauserv" start= demand        &rem Manual
sc config "wuauserv" start= disabled      &rem Disabled

rem Create a new service
sc create "MySvc" binpath= "C:\Services\myapp.exe" ^
    displayname= "My Service" start= auto obj= "LocalSystem"

rem Delete a service (stop first)
sc stop "MySvc"
sc delete "MySvc"

rem Set service failure actions (restart on failure)
sc failure "MySvc" reset= 86400 actions= restart/60000/restart/60000/restart/60000

rem Service dependencies
sc config "MySvc" depend= "Tcpip/Afd"
```

---

## 9. Pipes and Redirection

### Redirection Operators

```bat
rem Standard output to file (overwrite)
dir > listing.txt

rem Standard output to file (append)
echo %DATE% %TIME% >> logfile.txt

rem Stderr to file
command.exe 2> errors.txt

rem Stdout and stderr to same file
command.exe > output.txt 2>&1

rem Discard all output
command.exe >nul 2>&1

rem Redirect input from file
sort < unsorted.txt > sorted.txt
```

### Piping and Filters

```bat
rem Pipe output to another command
dir /s | find /c "File(s)"               &rem Count files recursively
type "data.txt" | sort                    &rem Sort lines
type "data.txt" | more                    &rem Page output

rem FIND — simple text search
find /i "error" "logfile.txt"             &rem Case-insensitive
find /c "warning" "logfile.txt"           &rem Count matching lines
find /n "TODO" "source.bat"              &rem Show line numbers
find /v "comment" "data.txt"              &rem Lines NOT containing string

rem FINDSTR — regex-capable search
findstr /i "error" *.log                  &rem Case-insensitive across files
findstr /r "^[0-9]" data.txt              &rem Lines starting with digit
findstr /s /i "password" *.config         &rem Recursive search
findstr /n /r "error\|warning" app.log    &rem Multiple patterns with line numbers
findstr /m "TODO" *.bat                   &rem List filenames only (like grep -l)

rem SORT
sort /r data.txt                          &rem Reverse sort
sort /+15 data.txt                        &rem Sort starting at column 15

rem Chaining filters
type access.log | find /i "404" | sort | find /c /v ""
```

---

## 10. Task Scheduling

### SCHTASKS

```bat
rem Create a daily task at 2:00 AM
schtasks /create /tn "NightlyBackup" /tr "C:\scripts\backup.bat" ^
    /sc daily /st 02:00 /ru SYSTEM

rem Create a task running every 5 minutes
schtasks /create /tn "HealthCheck" /tr "C:\scripts\check.bat" ^
    /sc minute /mo 5 /ru SYSTEM

rem Create a weekly task (Monday and Friday)
schtasks /create /tn "WeeklyReport" /tr "C:\scripts\report.bat" ^
    /sc weekly /d MON,FRI /st 08:00 /ru "DOMAIN\svcaccount" /rp "P@ssw0rd"

rem Run at system startup
schtasks /create /tn "StartupTask" /tr "C:\scripts\init.bat" ^
    /sc onstart /ru SYSTEM /rl HIGHEST

rem Run at user logon
schtasks /create /tn "LogonScript" /tr "C:\scripts\logon.bat" ^
    /sc onlogon /ru "DOMAIN\user"

rem Query tasks
schtasks /query /tn "NightlyBackup" /v /fo list
schtasks /query /fo table                 &rem All tasks, table format

rem Run a task immediately
schtasks /run /tn "NightlyBackup"

rem Modify an existing task
schtasks /change /tn "NightlyBackup" /st 03:00

rem Delete a task
schtasks /delete /tn "NightlyBackup" /f   &rem /f no confirmation prompt

rem End a running task
schtasks /end /tn "NightlyBackup"
```

---

## 11. Registry (REG)

### REG Commands

```bat
rem Query a key
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" /v ProductName
reg query "HKCU\Software\MyApp" /s        &rem Recursive

rem Add / modify a value
reg add "HKCU\Software\MyApp" /v Setting1 /t REG_SZ /d "Hello" /f
reg add "HKCU\Software\MyApp" /v Port /t REG_DWORD /d 8080 /f
reg add "HKLM\SOFTWARE\MyApp" /v Paths /t REG_MULTI_SZ /d "C:\one\0C:\two" /f
reg add "HKLM\SOFTWARE\MyApp" /v InstallDir /t REG_EXPAND_SZ /d "%%ProgramFiles%%\MyApp" /f

rem Value types: REG_SZ, REG_DWORD, REG_QWORD, REG_BINARY,
rem              REG_EXPAND_SZ, REG_MULTI_SZ, REG_NONE

rem Delete a value
reg delete "HKCU\Software\MyApp" /v Setting1 /f

rem Delete an entire key (and subkeys)
reg delete "HKCU\Software\MyApp" /f

rem Export a key to .reg file
reg export "HKCU\Software\MyApp" "C:\backup\myapp.reg" /y

rem Import a .reg file
reg import "C:\backup\myapp.reg"

rem Compare two keys
reg compare "HKLM\SOFTWARE\MyApp" "HKLM\SOFTWARE\MyApp_Old" /s

rem Common useful queries
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" /v CurrentBuild
reg query "HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters" /v Hostname
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /v DisplayName
```

---

## 12. Common Patterns

### Logging

```bat
@echo off
set LOGFILE=%~dp0logs\%~n0_%DATE:~-4%%DATE:~4,2%%DATE:~7,2%.log
if not exist "%~dp0logs" mkdir "%~dp0logs"

call :Log "Script started"
rem ... main logic ...
call :Log "Script finished"
exit /b 0

:Log
    echo [%DATE% %TIME%] %~1
    echo [%DATE% %TIME%] %~1 >> "%LOGFILE%"
    exit /b 0
```

### Error Handling Pattern

```bat
@echo off
setlocal
set EXITCODE=0

call :Step1 || goto :Failed
call :Step2 || goto :Failed
call :Step3 || goto :Failed

echo All steps completed successfully.
goto :Cleanup

:Failed
    set EXITCODE=1
    echo ERROR: Script failed at a step. Check log for details.

:Cleanup
    rem Clean up temp files, etc.
    if exist "%TEMP%\workfile.tmp" del "%TEMP%\workfile.tmp"
    endlocal & exit /b %EXITCODE%

:Step1
    echo Running Step 1...
    some_command.exe
    exit /b %ERRORLEVEL%

:Step2
    echo Running Step 2...
    another_command.exe
    exit /b %ERRORLEVEL%

:Step3
    echo Running Step 3...
    final_command.exe
    exit /b %ERRORLEVEL%
```

### Self-Elevating Batch File (Run as Admin)

```bat
@echo off
rem Check for admin rights
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Requesting administrative privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\" %*' -Verb RunAs"
    exit /b
)

echo Running with admin privileges.
rem --- Admin commands go here ---
pause
```

### Interactive Menu System

```bat
@echo off
:Menu
    cls
    echo =============================
    echo        MAIN MENU
    echo =============================
    echo  1. Show System Info
    echo  2. Check Disk Space
    echo  3. Flush DNS
    echo  4. Ping Test
    echo  0. Exit
    echo =============================
    set /p CHOICE=Select option:

    if "%CHOICE%"=="1" goto :SysInfo
    if "%CHOICE%"=="2" goto :DiskSpace
    if "%CHOICE%"=="3" goto :FlushDNS
    if "%CHOICE%"=="4" goto :PingTest
    if "%CHOICE%"=="0" exit /b 0
    echo Invalid option.
    timeout /t 2 >nul
    goto :Menu

:SysInfo
    systeminfo | findstr /i "host os version"
    pause
    goto :Menu

:DiskSpace
    rem wmic is deprecated/removed (gone by Windows 11 25H2) — call CIM from batch instead
    powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,FreeSpace,Size | Format-Table -AutoSize"
    pause
    goto :Menu

:FlushDNS
    ipconfig /flushdns
    pause
    goto :Menu

:PingTest
    set /p HOST=Enter host:
    ping %HOST% -n 4
    pause
    goto :Menu
```

### Date/Time Variables

```bat
rem Extract components from %DATE% and %TIME%
rem NOTE: Format depends on locale. Below assumes MM/DD/YYYY.
set YEAR=%DATE:~10,4%
set MONTH=%DATE:~4,2%
set DAY=%DATE:~7,2%
set HOUR=%TIME:~0,2%
set MINUTE=%TIME:~3,2%
set SECOND=%TIME:~6,2%

rem Remove leading space from hour (single-digit hours)
set HOUR=%HOUR: =0%

set TIMESTAMP=%YEAR%%MONTH%%DAY%_%HOUR%%MINUTE%%SECOND%
echo %TIMESTAMP%

rem Locale-safe alternative — PowerShell from batch
rem (the old `wmic os get localdatetime` recipe is dead: wmic is deprecated since
rem  Win10 21H1 and removed in Windows 11 25H2 — see the WMIC section)
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
echo %TODAY%

rem Full timestamp variant
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%I
echo %TS%
```

### Wait for a Process to Finish

```bat
rem Wait for a process to exit (poll every 5 seconds)
:WaitLoop
    tasklist /fi "imagename eq setup.exe" 2>nul | find /i "setup.exe" >nul
    if %ERRORLEVEL% equ 0 (
        timeout /t 5 >nul
        goto :WaitLoop
    )
    echo Process has exited.
```

### Batch File Argument Handling

```bat
@echo off
rem %0 = script name,  %1-%9 = arguments,  %* = all arguments
if "%~1"=="" (
    echo Usage: %~nx0 ^<source^> ^<destination^> [/log]
    exit /b 1
)

set SRC=%~1
set DST=%~2
set LOG=%~3

echo Source:      %SRC%
echo Destination: %DST%
if /i "%LOG%"=="/log" echo Logging enabled

rem SHIFT moves arguments: %2 becomes %1, %3 becomes %2, etc.
rem Useful for processing variable number of arguments
:ArgLoop
    if "%~1"=="" goto :ArgDone
    echo Arg: %~1
    shift
    goto :ArgLoop
:ArgDone
```

### Temporary Files

```bat
rem Create a unique temp file
set TMPFILE=%TEMP%\%~n0_%RANDOM%.tmp
echo data > "%TMPFILE%"
rem ... use it ...
del "%TMPFILE%" 2>nul
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using CMD for complex scripting instead of PowerShell | CMD lacks structured error handling, object pipeline, proper string manipulation, and modern API access | Use PowerShell for anything beyond simple file operations; CMD only for legacy compatibility or boot-time scripts |
| Not quoting file paths with spaces | `cd C:\Program Files` fails silently; operates on wrong directory; data written to wrong location | Always quote paths: `cd "C:\Program Files"`; use `%%~dp0` for script directory references |
| Using `del /s /q *.*` without careful path verification | One wrong directory and you delete everything recursively; no undo in CMD | Always `echo` the path first; use `rd` with explicit paths; consider `robocopy /mir` to an empty folder for safer deletion |
| Ignoring ERRORLEVEL after commands | Scripts continue after failures; downstream commands operate on missing files or wrong state | Check `if %ERRORLEVEL% NEQ 0` after critical commands; use `&&` to chain dependent commands |
| Hardcoding drive letters and absolute paths | Scripts break on different machines; different Windows installations use different drive letters | Use environment variables (%USERPROFILE%, %TEMP%, %SYSTEMROOT%); use `pushd/popd` for UNC paths |

---

## Related Skills

| Skill | Scope |
|---|---|
| `windows-powershell` | PowerShell scripting, modules, remoting, DSC |
| `windows-ps-security` | Windows security hardening, auditing, GPO |
| `windows-ps-server-admin` | Windows Server roles (AD, DNS, DHCP, IIS, Hyper-V) |

<!-- FRESHNESS:v1
anchors:
  - kind: status_snapshot
    subject: wmic-lifecycle
    verified_on: "2026-06-10"
    review_by: "2027-06"
volatility: low
-->

