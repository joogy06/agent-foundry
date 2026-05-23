#Requires -Version 5.1
# pre-commit-msosec.ps1 — Windows pre-commit hook (enterprise-hardened)
#
# Install: copy alongside .cmd wrapper to .git\hooks\
#   copy %USERPROFILE%\.claude\skills\ms-office-security-python\ms_office_security_check\pre-commit-msosec.cmd .git\hooks\pre-commit
#   copy %USERPROFILE%\.claude\skills\ms-office-security-python\ms_office_security_check\pre-commit-msosec.ps1 .git\hooks\pre-commit-msosec.ps1
#
# Hardening rules (mirror dep-currency-check):
#   - NO -ExecutionPolicy Bypass
#   - NO dot-source
#   - NO -Command (always -File)
#   - -NoProfile -NonInteractive enforced via .cmd wrapper
#   - Prefer pwsh.exe (7+), fall back to powershell.exe (5.1)
#   - Use call operator & for Python invocation

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$Python = $null
foreach ($cand in @('python3', 'python', 'py')) {
    $cmd = Get-Command -Name $cand -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd; break }
}
if (-not $Python) {
    Write-Warning 'pre-commit-msosec: Python 3 not found; skipping check'
    exit 0
}

$changedRaw = git diff --cached --name-only --diff-filter=ACM 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'pre-commit-msosec: git diff failed; skipping check'
    exit 0
}
$changed = $changedRaw | Select-String -Pattern '\.py$' | ForEach-Object { $_.Line }
if (-not $changed -or $changed.Count -eq 0) {
    exit 0
}

$skillDir = $env:MSOSEC_SKILL_DIR
if (-not $skillDir) {
    $skillDir = Join-Path $env:USERPROFILE '.claude\skills\ms-office-security-python'
}
if (-not (Test-Path -LiteralPath $skillDir)) {
    Write-Warning "pre-commit-msosec: skill dir not found ($skillDir); skipping"
    exit 0
}

$root = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'pre-commit-msosec: not in a git repo; skipping'
    exit 0
}

$changedList = ($changed -join ',')
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$skillDir;$env:PYTHONPATH" } else { $skillDir }

& $Python.Source -m ms_office_security_check $root `
    --changed-files $changedList `
    --severity high `
    --format md `
    --quiet

$rc = $LASTEXITCODE

switch ($rc) {
    0 { exit 0 }
    1 { Write-Warning 'pre-commit-msosec: STRICT BLOCK (unexpected in advisory mode)'; exit 1 }
    2 { Write-Warning 'pre-commit-msosec: advisory findings present (commit allowed)'; exit 0 }
    3 { Write-Warning 'pre-commit-msosec: environmental error; allowing commit'; exit 0 }
    default { Write-Warning "pre-commit-msosec: unexpected exit $rc; allowing commit"; exit 0 }
}
