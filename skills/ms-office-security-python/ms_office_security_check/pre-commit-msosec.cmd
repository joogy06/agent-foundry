@echo off
REM pre-commit-msosec.cmd — Windows wrapper that invokes .ps1 with hardened flags
REM
REM Install: copy this to .git\hooks\pre-commit (no extension) and .ps1 alongside.
REM
REM Hardening rules (mirror dep-currency-check installer):
REM   - Try pwsh.exe (PS 7+) first, fall back to powershell.exe (5.1)
REM   - -NoProfile -NonInteractive -File enforced
REM   - NO -ExecutionPolicy Bypass

where pwsh.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    pwsh.exe -NoProfile -NonInteractive -File "%~dp0pre-commit-msosec.ps1" %*
) else (
    powershell.exe -NoProfile -NonInteractive -File "%~dp0pre-commit-msosec.ps1" %*
)
exit /b %ERRORLEVEL%
