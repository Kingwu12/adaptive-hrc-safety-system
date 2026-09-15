@echo off
setlocal
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
cd /d "%~dp0"
echo SETUP: use only during a confirmed maintenance window with an idle rig.
call "%~dp0scripts\Run-Lab.cmd" maintenance-check
if errorlevel 1 goto :fail
where node.exe >nul 2>nul
if errorlevel 1 (
  echo SETUP FAILED: install institution-approved Node 22.13 or newer.
  goto :fail
)
where npm.cmd >nul 2>nul
if errorlevel 1 goto :fail
node.exe -e "const v=process.versions.node.split('.').map(Number); if(v[0]<22 || (v[0]===22 && v[1]<13)) { console.error('Node 22.13 or newer required'); process.exit(1); }"
if errorlevel 1 goto :fail
if exist ".venv\Scripts\python.exe" goto :install
where py.exe >nul 2>nul
if errorlevel 1 goto :pythonexe
py.exe -3.12 -m venv .venv
if errorlevel 1 goto :fail
goto :install
:pythonexe
python.exe -c "import sys; assert sys.version_info[:2] == (3,12), 'Python 3.12 required for the prepared environment'"
if errorlevel 1 goto :fail
python.exe -m venv .venv
if errorlevel 1 goto :fail
:install
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] == (3,12), 'Setup requires Python 3.12. Existing environment was preserved; Check-Lab may already pass without setup.'"
if errorlevel 1 goto :fail
set "LAB_PIP_SOURCE="
if exist ".lab-offline\wheels" set "LAB_PIP_SOURCE=--no-index --find-links .lab-offline\wheels"
".venv\Scripts\python.exe" -m pip install %LAB_PIP_SOURCE% -r requirements-lab-py312.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install %LAB_PIP_SOURCE% --no-deps --no-build-isolation -e .
if errorlevel 1 goto :fail
pushd dashboard
if exist "..\.lab-offline\npm" (
  call npm.cmd ci --offline --cache "..\.lab-offline\npm" --include=dev
) else (
  call npm.cmd ci --include=dev
)
set "LAB_NPM_EXIT=%ERRORLEVEL%"
popd
if not "%LAB_NPM_EXIT%"=="0" goto :fail
echo LAB SETUP COMPLETE. Run Check-Lab.cmd, then Start-Lab.cmd.
if not "%HRC_NONINTERACTIVE%"=="1" pause
exit /b 0
:fail
echo LAB SETUP FAILED. Keep the exact error above. No existing service was stopped.
if not "%HRC_NONINTERACTIVE%"=="1" pause
exit /b 1
