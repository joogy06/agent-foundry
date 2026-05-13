# bootstrap-environment.ps1 - Windows entry point for the bootstrap orchestrator.
#
# Mirrors install.ps1's enterprise-hardened pattern:
#   - #Requires -Version 5.1
#   - NO -ExecutionPolicy Bypass
#   - NO dot-source (call operator & only)
#   - NO -Command (this is the script body; subprocesses use -File)
#   - Probes python / python3 / py launcher in that order
#   - Pass-through args to the underlying Python orchestrator
#
# Usage (PowerShell 5.1 or pwsh 7+):
#   pwsh -NoProfile -NonInteractive -File installer\bootstrap-environment.ps1
#   pwsh -NoProfile -NonInteractive -File installer\bootstrap-environment.ps1 -DryRun
#   pwsh -NoProfile -NonInteractive -File installer\bootstrap-environment.ps1 -Force
#   pwsh -NoProfile -NonInteractive -File installer\bootstrap-environment.ps1 -SkipCodex -SkipGemini
#   pwsh -NoProfile -NonInteractive -File installer\bootstrap-environment.ps1 -ClaudeHome 'C:\custom\.claude'
#
# Exit codes mirror bootstrap-environment.py:
#   0 = all steps OK
#   1 = a step failed
#   2 = some steps skipped (e.g. existing files preserved, missing optional CLI)

#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$ClaudeHome,
    [switch]$DryRun,
    [switch]$Force,
    [switch]$SkipInstall,
    [switch]$SkipCodex,
    [switch]$SkipGemini,
    [switch]$Help
)

if ($Help) {
    Get-Help $PSCommandPath -Detailed
    exit 0
}

$ErrorActionPreference = 'Stop'

# Resolve the Python orchestrator next to this script.
$ScriptDir = Split-Path -Parent $PSCommandPath
$PyOrchestrator = Join-Path $ScriptDir 'bootstrap-environment.py'

if (-not (Test-Path -LiteralPath $PyOrchestrator -PathType Leaf)) {
    Write-Error "ERROR: bootstrap-environment.py not found at $PyOrchestrator"
    exit 1
}

# Find a Python interpreter. Prefer the py launcher (PEP 397) on Windows,
# then python3, then python. We probe each candidate by calling --version.
function Find-Python {
    foreach ($cand in @(
            @{ exe = 'py';      args = @('-3') },
            @{ exe = 'python3'; args = @() },
            @{ exe = 'python';  args = @() }
        )) {
        if ($null -eq (Get-Command $cand.exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $probeArgs = $cand.args + @('--version')
            & $cand.exe @probeArgs 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $cand
            }
        } catch {
            # try next candidate
        }
    }
    return $null
}

$Python = Find-Python
if ($null -eq $Python) {
    Write-Error "ERROR: no python / python3 / py found in PATH. Install Python 3.10+ first."
    exit 1
}

# Assemble args to forward to the Python script.
$PyArgs = @($PyOrchestrator)
if ($ClaudeHome) { $PyArgs += @('--claude-home', $ClaudeHome) }
if ($DryRun)     { $PyArgs += '--dry-run' }
if ($Force)      { $PyArgs += '--force' }
if ($SkipInstall){ $PyArgs += '--skip-install' }
if ($SkipCodex)  { $PyArgs += '--skip-codex' }
if ($SkipGemini) { $PyArgs += '--skip-gemini' }

# Compose full invocation: <exe> <launcher-args> <py-args>
$FullArgs = $Python.args + $PyArgs

Write-Host "Running: $($Python.exe) $($FullArgs -join ' ')"

# Use call operator (&) - NEVER dot-source.
& $Python.exe @FullArgs
$rc = $LASTEXITCODE

exit $rc
