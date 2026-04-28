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
Overwrite existing skills + agents at the target.

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
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$RepoRoot  = $PSScriptRoot
$SkillsDir = Join-Path $RepoRoot "skills"
$AgentsDir = Join-Path $RepoRoot "agents"

function Write-Banner {
    $line = "=" * 60
    Write-Host $line
    Write-Host " agent-foundry installer (PowerShell fallback — Claude only)"
    Write-Host $line
    Write-Host ""
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

Write-Host ("Repo root:    " + $RepoRoot)
Write-Host ("Platform:     Windows (PowerShell " + $PSVersionTable.PSVersion + ")")
Write-Host ("Skills found: " + $skills.Count)
Write-Host ("Agents found: " + $agents.Count)
Write-Host ""

if ($skills.Count -eq 0 -and $agents.Count -eq 0) {
    Write-Host "⚠ nothing to install (empty skills/ and agents/)." -ForegroundColor Red
    exit 1
}

Write-Host ("=" * 60)
Write-Host "Plan:"
Write-Host ("  Claude (" + $Mode + "): " + $SkillsDir + " → " + (Join-Path $ClaudeHome "skills"))
Write-Host ("                    " + $AgentsDir + " → " + (Join-Path $ClaudeHome "agents"))
Write-Host ("=" * 60)

if (-not $NonInteractive) {
    $confirm = Read-Host "Proceed? [y/N]"
    if ($confirm -notmatch "^(y|yes)$") {
        Write-Host "cancelled."
        exit 0
    }
}

$ClaudeSkills = Join-Path $ClaudeHome "skills"
$ClaudeAgents = Join-Path $ClaudeHome "agents"
foreach ($d in @($ClaudeSkills, $ClaudeAgents)) {
    if (-not (Test-Path -LiteralPath $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}

Write-Host ""
Write-Host "[Claude]"

$installed = 0
$skipped   = 0
foreach ($skill in $skills) {
    $dest = Join-Path $ClaudeSkills $skill.Name
    if ((Test-Path -LiteralPath $dest) -and (-not $Force)) {
        $skipped++
        continue
    }
    $null = Place-Item -Source $skill.FullName -Destination $dest -Mode $Mode
    $installed++
}

$agentInstalled = 0
foreach ($agent in $agents) {
    $dest = Join-Path $ClaudeAgents $agent.Name
    if ((Test-Path -LiteralPath $dest) -and (-not $Force)) {
        $skipped++
        continue
    }
    $null = Place-Item -Source $agent.FullName -Destination $dest -Mode $Mode
    $agentInstalled++
}

Write-Host ("  ✓ " + $installed + " skills, " + $agentInstalled +
            " agents installed (skipped " + $skipped + " existing)") -ForegroundColor Green

Write-Host ""
Write-Host "done."
Write-Host ""
Write-Host "Note: this PowerShell fallback installs Claude only. To install"
Write-Host "the Gemini and Copilot bridges, install Python and run install.py."
exit 0
