@echo off
setlocal
cd /d "%~dp0"
if not exist "data\service-logs" mkdir "data\service-logs"
set "LAB_REPORT=data\service-logs\bootstrap-%RANDOM%-%RANDOM%.txt"
call :collect > "%LAB_REPORT%" 2>&1
set "LAB_EXIT=%ERRORLEVEL%"
type "%LAB_REPORT%"
echo.
echo Diagnostic output: %LAB_REPORT%
echo Keep the original failed command and full error too. No services or policy were changed.
if not "%HRC_NONINTERACTIVE%"=="1" pause
exit /b %LAB_EXIT%

:collect
ver
where py.exe
where python.exe
where node.exe
where npm.cmd
where powershell.exe
echo --- Effective PowerShell scopes, read-only ---
powershell.exe -NoLogo -NoProfile -NonInteractive -Command "Get-ExecutionPolicy -List"
echo --- Python preflight, including program execution errors ---
call "%~dp0scripts\Run-Lab.cmd" diagnose
exit /b
