@echo off
setlocal
rem agent-foundry installer - Windows entry point.
rem The installer is cross-platform Python (install.py). Python 3.8+ is required;
rem there is no PowerShell installer. Windows 11 ships Python (Store / winget):
rem   winget install Python.Python.3
rem Pass-through: any extra args are forwarded to install.py.

rem Prefer the Windows 'py' launcher, then python, then python3.
where py >/dev/null 2>&1
if %errorlevel% equ 0 (
    py -3 "%~dp0install.py" %*
    exit /b %errorlevel%
)
where python >/dev/null 2>&1
if %errorlevel% equ 0 (
    python "%~dp0install.py" %*
    exit /b %errorlevel%
)
where python3 >/dev/null 2>&1
if %errorlevel% equ 0 (
    python3 "%~dp0install.py" %*
    exit /b %errorlevel%
)

echo.
echo [ERROR] Python 3.8+ was not found on PATH.
echo The agent-foundry installer is pure Python ^(no PowerShell^).
echo Install Python, then re-run install.cmd:
echo   winget install Python.Python.3
echo   or download from https://www.python.org/downloads/
echo.
exit /b 1
