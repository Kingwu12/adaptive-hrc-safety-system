@echo off
setlocal
cd /d "%~dp0"

where py.exe >nul 2>nul
if errorlevel 1 (
  echo SETUP FAILED: Python launcher py.exe is missing. Install Python 3.10 or newer.
  goto :fail
)
where node.exe >nul 2>nul
if errorlevel 1 (
  echo SETUP FAILED: Node is missing. Install Node 22.13 or newer.
  goto :fail
)
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo SETUP FAILED: npm.cmd is missing. Repair the Node installation.
  goto :fail
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the lab Python environment...
  py.exe -3 -m venv .venv
  if errorlevel 1 goto :fail
)

echo Installing the FYP Python environment...
".venv\Scripts\python.exe" -m pip install -e ".[dev,robot]"
if errorlevel 1 goto :fail

echo Installing the locked dashboard environment...
pushd dashboard
call npm.cmd ci --include=dev
set "NPM_EXIT=%ERRORLEVEL%"
popd
if not "%NPM_EXIT%"=="0" goto :fail

echo.
echo LAB SETUP COMPLETE. Double-click Check-Lab.cmd, then Start-Lab.cmd.
pause
exit /b 0

:fail
echo.
echo LAB SETUP FAILED. Keep this window open and use the error above.
pause
exit /b 1
