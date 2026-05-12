# Windows `.ps1` enterprise hardening rules

Authoritative source for the `pre-commit-dep-currency.ps1` template. Same hardening pattern as enterprise-grade VS Code Foundry installers (`-NoProfile -NonInteractive -File`, no `-ExecutionPolicy Bypass`, no dot-source).

## NON-NEGOTIABLE rules

1. **NO `-ExecutionPolicy Bypass`** — enterprise machines block this at GPO. Hook silently fails.
2. **NO dot-source** (`. .\script.ps1`) — security risk + parsing surprises.
3. **NO `-Command`** — always use `-File`. `-Command` is interpreted as raw PowerShell input; `-File` is a script path.
4. **Always pass `-NoProfile -NonInteractive`** to skip profile loading + prevent stuck prompts.
5. **CRLF line endings** — `.gitattributes` should already set `*.ps1 text eol=crlf`; verify on commit.
6. **Prefer `pwsh.exe`** (7+); fall back to `powershell.exe` (5.1). Both ship with most enterprise images.
7. **Use call operator `&`** for Python invocation, NEVER dot-source.
8. **Set `$ErrorActionPreference = 'Stop'`** so errors fail the script instead of silently continuing.
9. **`#Requires -Version 5.1`** at top — minimum compatible PowerShell version.
10. **`[CmdletBinding()]`** — gives the script standard parameter binding behavior.
11. **`param()` even if empty** — declares the script as a script, not a workflow.

## Why these rules

| Rule | Why |
|---|---|
| No `-ExecutionPolicy Bypass` | Group Policy blocks this at most enterprises; silent fail with no diagnostic |
| No dot-source | Script's variables/functions leak into caller's session; parsing oddities |
| Use `-File` | `-Command` interprets input as PowerShell code (injection surface); `-File` is path-only |
| `-NoProfile -NonInteractive` | Profile loading delays + interactive prompts hang automation |
| CRLF | PowerShell on Windows expects CRLF; LF causes "is not recognized" errors |
| `pwsh.exe` first | PS 7 has better cross-platform behavior, faster startup, fixed bugs |
| Call operator `&` | Invokes a string as a command without dot-sourcing |
| `$ErrorActionPreference = 'Stop'` | Default is `Continue`; silent error → wrong exit code |

## `.cmd` wrapper

git invokes `.git/hooks/pre-commit` (no extension) on Windows by trying `.bat`/`.cmd`. The wrapper must:

```cmd
@echo off
REM Find pwsh.exe first, fall back to powershell.exe
where pwsh.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    pwsh.exe -NoProfile -NonInteractive -File "%~dp0pre-commit-dep-currency.ps1" %*
) else (
    powershell.exe -NoProfile -NonInteractive -File "%~dp0pre-commit-dep-currency.ps1" %*
)
exit /b %ERRORLEVEL%
```

`%~dp0` resolves to the directory of the `.cmd` file, so the `.ps1` must sit alongside.

## Python discovery in `.ps1`

```powershell
$Python = $null
foreach ($cand in @('python', 'python3', 'py')) {
    $cmd = Get-Command -Name $cand -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd; break }
}
if (-not $Python) {
    Write-Error 'Python 3.10+ required. Install Python and retry.'
    exit 3
}
```

Use `Get-Command -ErrorAction SilentlyContinue` (not `Test-Path`) — it correctly handles PATH lookups, aliases, and executables in non-standard locations.

## Invocation

```powershell
& $Python.Source -m dep_currency_check $root `
    --changed-manifests ($changed.Line -join ',') `
    --severity critical --format json --quiet
exit $LASTEXITCODE
```

`$Python.Source` is the full path to the `.exe`. `-Source` is preferred over `.Name` because PATH ambiguity can otherwise pick a different `python.exe`.

`exit $LASTEXITCODE` propagates the child process's exit code to git.

## Verifying

```powershell
# Should pass:
$PSVersionTable.PSVersion                   # >= 5.1
$ExecutionContext.SessionState.LanguageMode  # FullLanguage (or ConstrainedLanguage on JEA)
# Should fail (intentionally):
. .\pre-commit-dep-currency.ps1              # dot-source — DON'T
pwsh -Command "& .\pre-commit-dep-currency.ps1"  # use -File, not -Command
```
