@echo off
setlocal
rem agent-foundry installer — Windows entry point.
rem
rem Tries Python first (cross-platform install.py with all 3 targets).
rem Falls back to PowerShell (install.ps1, Claude install only) if Python
rem is not on PATH. The PowerShell call passes -ExecutionPolicy Bypass
rem so it works on locked-down enterprise machines that block dot-sourcing.
rem
rem Pass-through: any extra args after this script's name are forwarded.

where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%~dp0install.py" %*
    exit /b %errorlevel%
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    python3 "%~dp0install.py" %*
    exit /b %errorlevel%
)

echo.
echo Python not found on PATH; falling back to PowerShell installer.
echo (PowerShell fallback supports Claude install only. Install Python
echo  to use Gemini and Copilot bridges via install.py.)
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %errorlevel%
