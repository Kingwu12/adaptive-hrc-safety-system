@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\Run-Lab.cmd" check %*
set "LAB_EXIT=%ERRORLEVEL%"
echo.
if not "%HRC_NONINTERACTIVE%"=="1" pause
exit /b %LAB_EXIT%
