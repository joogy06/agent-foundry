@echo off
setlocal
rem agent-foundry bootstrap - Windows entry point.
rem Runs the cross-platform Python bootstrap (bootstrap-environment.py).
rem Python 3.8+ is required (winget install Python.Python.3). No PowerShell.
rem Pass-through: args forwarded (e.g. --dry-run, --skip-codex, --no-log).

where py >/dev/null 2>&1
if %errorlevel% equ 0 (
    py -3 "%~dp0bootstrap-environment.py" %*
    exit /b %errorlevel%
)
where python >/dev/null 2>&1
if %errorlevel% equ 0 (
    python "%~dp0bootstrap-environment.py" %*
    exit /b %errorlevel%
)
where python3 >/dev/null 2>&1
if %errorlevel% equ 0 (
    python3 "%~dp0bootstrap-environment.py" %*
    exit /b %errorlevel%
)

echo.
echo [ERROR] Python 3.8+ was not found on PATH.
echo Install Python and re-run: winget install Python.Python.3
echo   or https://www.python.org/downloads/
echo.
exit /b 1
