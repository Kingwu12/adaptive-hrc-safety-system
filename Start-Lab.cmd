@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\Run-Lab.cmd" start %*
set "LAB_EXIT=%ERRORLEVEL%"
if not "%LAB_EXIT%"=="0" (
  echo.
  echo LAB START FAILED. The message above names the blocker.
  if not "%HRC_NONINTERACTIVE%"=="1" pause
)
exit /b %LAB_EXIT%
