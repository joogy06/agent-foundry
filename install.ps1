<#
.SYNOPSIS
agent-foundry installer — PowerShell fallback for Claude Code CLI install only.

.DESCRIPTION
This script is invoked when Python isn't available on a Windows machine. It
installs Claude Code skills + agents from the local agent-foundry clone into
~/.claude/, after a LIMITED native scan (name-only PATH check, no version
probes). The full adaptive scan (probed versions, agy host directive, Copilot/
VS Code wiring, legacy Gemini bridge) is Python-canonical — install Python and
run install.py for it. This asymmetry is intentional, not drift.

The companion install.cmd already handles the ExecutionPolicy issue — it
invokes this script with -ExecutionPolicy Bypass, so dot-sourcing isn't
required.

.PARAMETER ClaudeHome
Override the Claude config dir. Default: $env:USERPROFILE\.claude

.PARAMETER Mode
'link' (symbolic link, recommended) or 'move' (copy). Default: link.
Note: symbolic links on Windows require admin OR Developer Mode; if the
attempt fails, the script falls back to copy.

.PARAMETER Force
(no-op; replace-existing is now the default — kept for backward compat)

.PARAMETER SkipExisting
Leave existing skills/agents/commands at the target untouched (old default).

.PARAMETER NonInteractive
Skip the confirmation prompt; use defaults.

.PARAMETER NoLog
Disable the run-log transcript (logging is on by default — see §8b). The
transcript is written to installer\logs\install-<UTC-ts>.log.

.PARAMETER LogPath
Write the run-log transcript to this path instead of the default
installer\logs\install-<UTC-ts>.log.

.EXAMPLE
.\install.ps1
.EXAMPLE
.\install.ps1 -Mode move -Force
.EXAMPLE
.\install.cmd -NonInteractive -ClaudeHome C:\Tools\.claude
#>
param(
    [string]$ClaudeHome = (Join-Path $env:USERPROFILE ".claude"),
    [ValidateSet("link", "move")][string]$Mode = "link",
    [switch]$Force,
    [switch]$SkipExisting,
    [switch]$NonInteractive,
    [switch]$NoLog,
    [string]$LogPath
)

$ErrorActionPreference = "Stop"

# --- §8b run-log (Start-Transcript; the Python-absent equivalent of the tee) ---
# NEVER break the install: transcript start is wrapped; an unwritable logs\ dir
# falls back to $env:TEMP, and total failure just disables logging.
function Start-RunTranscript {
    param([string]$ScriptDir, [string]$Explicit)
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH-mm-ssZ")
    $target = $null
    if ($Explicit) {
        $target = $Explicit
    } else {
        $logDir = Join-Path $ScriptDir "logs"
        try {
            if (-not (Test-Path -LiteralPath $logDir)) {
                New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
            }
            $target = Join-Path $logDir "install-$stamp.log"
        } catch {
            $target = $null  # fall through to temp
        }
    }
    if (-not $target) {
        try {
            $target = Join-Path $env:TEMP "agent-foundry-install-$stamp.log"
        } catch { return $null }
    }
    try {
        Start-Transcript -Path $target -Force -ErrorAction Stop | Out-Null
        return $target
    } catch {
        # As a last resort try temp; if even that fails, give up on logging.
        try {
            $fb = Join-Path $env:TEMP "agent-foundry-install-$stamp.log"
            Start-Transcript -Path $fb -Force -ErrorAction Stop | Out-Null
            Write-Host ("  ! run-log: " + $target + " unwritable; logging to " + $fb) -ForegroundColor Yellow
            return $fb
        } catch {
            Write-Host "  ! run-log: could not start a transcript; continuing without a log." -ForegroundColor Yellow
            return $null
        }
    }
}

# RepoRoot auto-detection:
# - Bundled mode (public agent-foundry): install.ps1 lives next to skills/agents/commands.
# - Dev mode (skill_factory/installer/): those siblings live in the parent directory.
$_Here = $PSScriptRoot
$_HereHasContent = @('skills','agents','commands') | Where-Object { Test-Path -LiteralPath (Join-Path $_Here $_) }
$_ParentDir = Split-Path -Parent $_Here
$_ParentHasContent = @('skills','agents','commands') | Where-Object { Test-Path -LiteralPath (Join-Path $_ParentDir $_) }
if ($_HereHasContent.Count -gt 0) {
    $RepoRoot = $_Here
} elseif ($_ParentHasContent.Count -gt 0) {
    $RepoRoot = $_ParentDir
} else {
    $RepoRoot = $_Here   # fall back; the "skills/ not found" check below will warn cleanly
}

$SkillsDir   = Join-Path $RepoRoot "skills"
$AgentsDir   = Join-Path $RepoRoot "agents"
$CommandsDir = Join-Path $RepoRoot "commands"

function Write-Banner {
    $line = "=" * 60
    Write-Host $line
    Write-Host " agent-foundry installer (PowerShell fallback — Claude only)"
    Write-Host $line
    Write-Host ""
}

function Get-ClaudeCli {
    $cmd = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $cmd) { return @{ Found = $false; Version = $null } }
    try {
        $out = & $cmd.Source --version 2>&1 | Select-Object -First 1
        return @{ Found = $true; Version = "$out".Trim() }
    } catch {
        return @{ Found = $true; Version = "(version probe failed)" }
    }
}

function Show-DegradedScan {
    # DEGRADED native probe — this PowerShell path is the Python-ABSENT fallback,
    # so it CANNOT run the canonical Python scanner (scan_environment() in
    # install.py). It does a name-only PATH check (NO version probes, NO known-
    # location arrays) and tells the user to install Python for full detection +
    # agy/Copilot wiring. This asymmetry is intentional, not drift: the full
    # adaptive scan is Python-canonical (single source of truth).
    Write-Host ("=" * 60)
    Write-Host "Environment scan (LIMITED — Python absent)"
    Write-Host ("=" * 60)
    foreach ($tool in @('claude','agy','copilot','code','git')) {
        $found = $null -ne (Get-Command $tool -ErrorAction SilentlyContinue)
        $mark  = if ($found) { 'yes' } else { 'no ' }
        Write-Host ("  {0,-9} {1}" -f $tool, $mark)
    }
    Write-Host ""
    Write-Host "  Note: this is a LIMITED scan (Python not on PATH). For full detection"
    Write-Host "  (probed versions, ~/.local/bin + npm-global + GUI-app shims, agy host"
    Write-Host "  directive, Copilot/VS Code wiring), install Python and run install.py:"
    Write-Host "      python install.py            # interactive, full adaptive scan"
    Write-Host "      python install.py --auto     # install into all detected CLIs"
    Write-Host ""
    Write-Host "  This PowerShell fallback installs Claude skills/agents/commands only."
    Write-Host ("=" * 60)
    Write-Host ""
}

# Script-level flag: once a symlink fails with a privilege/unsupported error,
# stop trying for the rest of the run and copy directly. Avoids a wall of 160
# identical warnings on a non-admin Windows host without Developer Mode.
$script:SymlinkDisabledForRun = $false

function Place-Item {
    param(
        [Parameter(Mandatory)] [string]$Source,
        [Parameter(Mandatory)] [string]$Destination,
        [Parameter(Mandatory)] [string]$Mode
    )

    if (Test-Path -LiteralPath $Destination) {
        try { Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction Stop }
        catch { Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue }
    }

    if ($Mode -eq "link" -and -not $script:SymlinkDisabledForRun) {
        try {
            $null = New-Item -ItemType SymbolicLink -Path $Destination -Target $Source -ErrorAction Stop
            return "link"
        } catch {
            $msg = $_.Exception.Message
            $isPriv = ($msg -match "1314") -or ($msg -match "privilege is not held")
            if ($isPriv) {
                # First privilege failure: one actionable note, suppress the rest.
                $script:SymlinkDisabledForRun = $true
                Write-Host ""
                Write-Host "    ⚠ Windows symlink privilege missing (WinError 1314)." -ForegroundColor Yellow
                Write-Host "      Falling back to COPY for all remaining items." -ForegroundColor Yellow
                Write-Host "      To enable symlinks, EITHER:"
                Write-Host "        • run this installer from an elevated (Administrator) PowerShell, OR"
                Write-Host "        • enable Developer Mode: Settings → Privacy & Security → For developers"
                Write-Host "        • or just rerun with -Mode move to skip symlinks entirely"
                Write-Host ""
            } else {
                Write-Host ("    ⚠ symlink failed for " + (Split-Path -Leaf $Source) +
                            ": " + $msg + "; copying instead") -ForegroundColor Yellow
            }
        }
    }

    if ((Get-Item -LiteralPath $Source).PSIsContainer) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    } else {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
    return "copy"
}

# ---------- main ----------

# §8b: start the run-log transcript (unless -NoLog). Wrapped so it never aborts.
$script:RunLogTarget = $null
if (-not $NoLog) {
    $script:RunLogTarget = Start-RunTranscript -ScriptDir $_Here -Explicit $LogPath
}

try {

Write-Banner

Show-DegradedScan

if (-not (Test-Path -LiteralPath $SkillsDir)) {
    Write-Host "⚠ skills/ not found at $SkillsDir." -ForegroundColor Red
    Write-Host "  Run this script from the cloned agent-foundry root." -ForegroundColor Red
    exit 1
}

$skills = @(Get-ChildItem -LiteralPath $SkillsDir -Directory |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md") })
$agents = @()
if (Test-Path -LiteralPath $AgentsDir) {
    $agents = @(Get-ChildItem -LiteralPath $AgentsDir -Filter "*.md")
}
$commands = @()
if (Test-Path -LiteralPath $CommandsDir) {
    $commands = @(Get-ChildItem -LiteralPath $CommandsDir -Filter "*.md")
}

$claude = Get-ClaudeCli

Write-Host ("Repo root:      " + $RepoRoot)
Write-Host ("Platform:       Windows (PowerShell " + $PSVersionTable.PSVersion + ")")
if ($claude.Found) {
    Write-Host ("Claude CLI:     " + $claude.Version)
} else {
    Write-Host ("Claude CLI:     NOT FOUND on PATH") -ForegroundColor Yellow
}
Write-Host ("Skills found:   " + $skills.Count)
Write-Host ("Agents found:   " + $agents.Count)
Write-Host ("Commands found: " + $commands.Count)
Write-Host ""

if (-not $claude.Found) {
    Write-Host "⚠ ``claude`` CLI not on PATH. Install with:" -ForegroundColor Yellow
    Write-Host "    irm https://claude.ai/install.ps1 | iex"
    Write-Host "  (or see https://docs.claude.com/en/docs/claude-code/setup)"
    Write-Host "  Continuing — files will land at ~/.claude/ and be picked up once ``claude`` is installed."
    Write-Host ""
}

if ($skills.Count -eq 0 -and $agents.Count -eq 0 -and $commands.Count -eq 0) {
    Write-Host "⚠ nothing to install (empty skills/, agents/, and commands/)." -ForegroundColor Red
    exit 1
}

Write-Host ("=" * 60)
Write-Host "Plan:"
Write-Host ("  Claude (" + $Mode + "): " + $SkillsDir + "   → " + (Join-Path $ClaudeHome "skills"))
Write-Host ("                    " + $AgentsDir + "   → " + (Join-Path $ClaudeHome "agents"))
Write-Host ("                    " + $CommandsDir + " → " + (Join-Path $ClaudeHome "commands"))
if ($SkipExisting) {
    Write-Host "  Existing entries at the target will be KEPT (-SkipExisting)."
} else {
    Write-Host "  Existing entries at the target will be REPLACED. Pass -SkipExisting to keep them."
}
Write-Host ("=" * 60)

if (-not $NonInteractive) {
    $confirm = Read-Host "Proceed? [y/N]"
    if ($confirm -notmatch "^(y|yes)$") {
        Write-Host "cancelled."
        exit 0
    }
}

$ClaudeSkills   = Join-Path $ClaudeHome "skills"
$ClaudeAgents   = Join-Path $ClaudeHome "agents"
$ClaudeCommands = Join-Path $ClaudeHome "commands"
foreach ($d in @($ClaudeSkills, $ClaudeAgents, $ClaudeCommands)) {
    if (-not (Test-Path -LiteralPath $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}

Write-Host ""
Write-Host "[Claude]"

$installed       = 0
$agentInstalled  = 0
$commandInstalled = 0
$touchedExisting = 0

function Install-Item {
    param(
        [Parameter(Mandatory)] [string]$Source,
        [Parameter(Mandatory)] [string]$Destination
    )
    $existed = Test-Path -LiteralPath $Destination
    if ($SkipExisting -and $existed) {
        $script:touchedExisting++
        return $false
    }
    if ($existed) { $script:touchedExisting++ }
    $null = Place-Item -Source $Source -Destination $Destination -Mode $Mode
    return $true
}

foreach ($skill in $skills) {
    if (Install-Item -Source $skill.FullName -Destination (Join-Path $ClaudeSkills $skill.Name)) {
        $installed++
    }
}
foreach ($agent in $agents) {
    if (Install-Item -Source $agent.FullName -Destination (Join-Path $ClaudeAgents $agent.Name)) {
        $agentInstalled++
    }
}
foreach ($command in $commands) {
    if (Install-Item -Source $command.FullName -Destination (Join-Path $ClaudeCommands $command.Name)) {
        $commandInstalled++
    }
}

$verb = if ($SkipExisting) { "kept" } else { "replaced" }
Write-Host ("  ✓ " + $installed + " skills, " + $agentInstalled +
            " agents, " + $commandInstalled +
            " commands installed (" + $touchedExisting + " " + $verb + " existing)") -ForegroundColor Green

Write-Host ""
Write-Host "done."
Write-Host ""
Write-Host "Note: this PowerShell fallback installs Claude only. For the full"
Write-Host "adaptive install (agy host directive, Copilot/VS Code wiring, and the"
Write-Host "legacy Gemini bridge), install Python and run install.py."
exit 0

}
finally {
    # §8b: always stop the transcript and echo the log path (mirrors the Python
    # tee footer). Wrapped so cleanup never throws.
    if ($script:RunLogTarget) {
        try { Stop-Transcript | Out-Null } catch { }
        Write-Host ("`n" + [char]0x1F4DD + " Full log: " + $script:RunLogTarget)
    }
}
