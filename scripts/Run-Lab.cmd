@echo off
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\lab_launcher.py" %*
  exit /b
)
where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -3 "scripts\lab_launcher.py" %*
  exit /b
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  python.exe "scripts\lab_launcher.py" %*
  exit /b
)
echo BLOCKED: no Python executable was found. Run Diagnose-Lab.cmd and retain its output.
echo Use the institution-approved Python 3.12 installation. No policy setting was changed.
exit /b 1
