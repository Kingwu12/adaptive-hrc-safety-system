@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Lab.ps1" -CheckOnly
set "LAB_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %LAB_EXIT%
