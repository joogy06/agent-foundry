<#
.SYNOPSIS
agent-foundry installer — PowerShell fallback for Claude Code CLI install only.

.DESCRIPTION
This script is invoked when Python isn't available on a Windows machine. It
installs Claude Code skills + agents from the local agent-foundry clone into
~/.claude/. For Gemini and Copilot bridges, install Python and run install.py.

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
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$RepoRoot   = $PSScriptRoot
$SkillsDir  = Join-Path $RepoRoot "skills"
$AgentsDir  = Join-Path $RepoRoot "agents"
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

    if ($Mode -eq "link") {
        try {
            $null = New-Item -ItemType SymbolicLink -Path $Destination -Target $Source -ErrorAction Stop
            return "link"
        } catch {
            Write-Host ("    ⚠ symlink failed for " + (Split-Path -Leaf $Source) +
                        ": " + $_.Exception.Message + "; copying instead") -ForegroundColor Yellow
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

Write-Banner

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
Write-Host "Note: this PowerShell fallback installs Claude only. To install"
Write-Host "the Gemini and Copilot bridges, install Python and run install.py."
exit 0
