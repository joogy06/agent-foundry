#Requires -Version 5.1
# pre-commit-dep-currency.ps1 — Windows pre-commit hook (enterprise-hardened)
#
# Install: copy alongside .cmd wrapper to .git\hooks\
#   copy %USERPROFILE%\.claude\skills\dep-currency-check\scripts\pre-commit-dep-currency.cmd .git\hooks\pre-commit
#   copy %USERPROFILE%\.claude\skills\dep-currency-check\scripts\pre-commit-dep-currency.ps1 .git\hooks\pre-commit-dep-currency.ps1
#
# Hardening rules (mirror vs-code-foundry):
#   - NO -ExecutionPolicy Bypass
#   - NO dot-source
#   - NO -Command (always -File)
#   - -NoProfile -NonInteractive enforced via .cmd wrapper
#   - Prefer pwsh.exe (7+), fall back to powershell.exe (handled in .cmd wrapper)
#   - Use call operator & for Python invocation

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Find Python (try python, python3, py)
$Python = $null
foreach ($cand in @('python3', 'python', 'py')) {
    $cmd = Get-Command -Name $cand -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd; break }
}
if (-not $Python) {
    Write-Warning 'pre-commit-dep-currency: Python 3 not found; skipping check'
    exit 0
}

# Collect changed manifests
$changedRaw = git diff --cached --name-only --diff-filter=ACM 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'pre-commit-dep-currency: git diff failed; skipping check'
    exit 0
}
$pattern = 'package\.json|pyproject\.toml|requirements[^/]*\.txt|Cargo\.toml|go\.mod|Gemfile|pom\.xml|build\.gradle.*|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|Gemfile\.lock$'
$changed = $changedRaw | Select-String -Pattern $pattern | ForEach-Object { $_.Line }

if (-not $changed -or $changed.Count -eq 0) {
    exit 0
}

# Determine skill location
$skillDir = $env:DEP_CURRENCY_SKILL_DIR
if (-not $skillDir) {
    $skillDir = Join-Path $env:USERPROFILE '.claude\skills\dep-currency-check\scripts'
}
if (-not (Test-Path -LiteralPath $skillDir)) {
    Write-Warning "pre-commit-dep-currency: skill dir not found ($skillDir); skipping"
    exit 0
}

$root = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'pre-commit-dep-currency: not in a git repo; skipping'
    exit 0
}

$changedList = ($changed -join ',')
$parent = (Split-Path -Parent $skillDir)
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$parent;$env:PYTHONPATH" } else { $parent }

# Invoke via call operator (NEVER dot-source)
& $Python.Source -m dep_currency_check $root `
    --changed-manifests $changedList `
    --severity critical `
    --format json `
    --quiet `
    --render markdown

$rc = $LASTEXITCODE

# Map exit codes (mirror .sh)
switch ($rc) {
    0 { exit 0 }
    1 {
        Write-Warning 'pre-commit-dep-currency: STRICT BLOCK (unexpected in advisory mode)'
        exit 1
    }
    2 {
        Write-Warning 'pre-commit-dep-currency: advisory findings present (commit allowed)'
        exit 0
    }
    3 {
        Write-Warning 'pre-commit-dep-currency: environmental error; allowing commit'
        exit 0
    }
    4 {
        Write-Warning 'pre-commit-dep-currency: offline + cold cache; allowing commit'
        exit 0
    }
    default {
        Write-Warning "pre-commit-dep-currency: unexpected exit $rc; allowing commit"
        exit 0
    }
}
