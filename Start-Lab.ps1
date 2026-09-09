param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$labRoot = $PSScriptRoot
$labPython = Join-Path $labRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    throw 'The lab Python environment is missing. Create .venv and install this project before launching.'
}
$labDashboard = Join-Path $labRoot 'dashboard'
$labNode = (Get-Command node -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $labDashboard 'node_modules/vinext/dist/cli.js'))) {
    throw 'Dashboard dependencies are missing. Run npm ci --include=dev in dashboard once.'
}
try { $labStatus = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 3 }
catch { $labStatus = $null }
if ($labStatus) {
    if (-not $labStatus.automation.enabled -or -not $labStatus.controller_output_enabled) {
        throw 'A sensor service is already running without automatic trials enabled. Finish/abort any trial, stop that service, then run this launcher again. It will not kill an unknown service.'
    }
    if ($labStatus.automation.supported_collection_modes -notcontains 'participant_study') {
        throw 'The running backend is an older rehearsal-only version. Finish/abort any trial, stop that service, then run this launcher again.'
    }
    Write-Host 'Existing sensor service: participant and rehearsal automation enabled.'
}
if ($CheckOnly) {
    Write-Host ('Dependencies ready. Sensor service running: ' + [bool]$labStatus)
    exit 0
}
$labLog = Join-Path $labRoot 'data/service-logs'
New-Item -ItemType Directory -Path $labLog -Force | Out-Null
$labStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $labStatus) {
    $labServer = Start-Process -FilePath $labPython -ArgumentList @('-u', 'scripts/dashboard_server.py', '--enable-research-speed-output', '--enable-automatic-trials') -WorkingDirectory $labRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $labLog "$labStamp-sensors.log") -RedirectStandardError (Join-Path $labLog "$labStamp-sensors.err.log")
    for ($labTry = 0; $labTry -lt 30; $labTry++) {
        Start-Sleep -Milliseconds 500
        if ($labServer.HasExited) { throw "Sensor service exited. Read data/service-logs/$labStamp-sensors.err.log" }
        try { $labStatus = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 2; break } catch {}
    }
    if (-not $labStatus -or -not $labStatus.automation.enabled -or -not $labStatus.controller_output_enabled) {
        throw 'Sensor service did not confirm automatic trials. Inspect the service logs.'
    }
}
try { $labPage = Invoke-WebRequest 'http://localhost:3000' -UseBasicParsing -TimeoutSec 3 }
catch { $labPage = $null }
if (-not $labPage) {
    $labWeb = Start-Process -FilePath $labNode -ArgumentList @('scripts/run-vinext.mjs', 'dev', '--host', '127.0.0.1', '--port', '3000', '--strictPort') -WorkingDirectory $labDashboard -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $labLog "$labStamp-dashboard.log") -RedirectStandardError (Join-Path $labLog "$labStamp-dashboard.err.log")
    for ($labTry = 0; $labTry -lt 60; $labTry++) {
        Start-Sleep -Milliseconds 500
        if ($labWeb.HasExited) { throw "Dashboard exited. Read data/service-logs/$labStamp-dashboard.err.log" }
        try { $labPage = Invoke-WebRequest 'http://localhost:3000' -UseBasicParsing -TimeoutSec 2; break } catch {}
    }
}
if (-not $labPage) { throw 'Dashboard did not become ready. Sensor service remains running; inspect the logs.' }
$labProxy = Invoke-RestMethod 'http://localhost:3000/api/status' -TimeoutSec 5
if (-not $labProxy.automation.enabled -or $labProxy.automation.supported_collection_modes -notcontains 'participant_study') { throw 'The dashboard is not connected to the updated automatic-trial service.' }
Start-Process 'http://localhost:3000'
Write-Host 'Automatic trials enabled. Choose Participant study for P-codes or Qualification for Q-codes.'
Write-Host 'Start trial begins the guarded cycle. Starting the service alone does not move the robot.'
