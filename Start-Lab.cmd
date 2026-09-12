@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Lab.ps1" %*
set "LAB_EXIT=%ERRORLEVEL%"
if not "%LAB_EXIT%"=="0" (
  echo.
  echo LAB START FAILED. The message above names the blocker.
  pause
)
exit /b %LAB_EXIT%
