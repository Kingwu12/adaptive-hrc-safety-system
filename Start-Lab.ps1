param([switch]$CheckOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$labContract = 'adaptive-hrc-lab-backend-v1'
$labRoot = $PSScriptRoot
$labPython = Join-Path $labRoot '.venv/Scripts/python.exe'
$labDashboard = Join-Path $labRoot 'dashboard'
$labServerSource = Join-Path $labRoot 'scripts/dashboard_server.py'
$labLog = Join-Path $labRoot 'data/service-logs'

function Get-LabProperty {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-LabUrl {
    param([string]$Url, [int]$TimeoutSeconds = 3)
    try { return Invoke-RestMethod $Url -TimeoutSec $TimeoutSeconds }
    catch { return $null }
}

function Get-LabListener {
    param([int]$Port)
    try {
        # No matching port is distinct from an inspection failure.
        return Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $_.LocalPort -eq $Port } | Select-Object -First 1
    }
    catch { throw "BLOCKED: cannot inspect TCP port $Port. Existing service state is unknown. $($_.Exception.Message)" }
}

function Assert-LabBackendState {
    param($Status, $Listener, [string]$ExpectedHash, [string]$Contract)
    if ($null -eq $Status) {
        if ($null -ne $Listener) {
            throw "BLOCKED: port 8765 is occupied (PID $($Listener.OwningProcess)), but backend status is unavailable. An active trial cannot be ruled out. No process was stopped."
        }
        return
    }
    $service = Get-LabProperty $Status 'service'
    if ((Get-LabProperty $service 'contract') -ne $Contract -or
        (Get-LabProperty $service 'source_sha256') -ne $ExpectedHash) {
        throw 'BLOCKED: an older or unidentified backend is already running. Establish the rig and recording state, then arrange a deliberate shutdown before relaunching. No process was stopped.'
    }
    if ($null -eq $Listener -or
        (Get-LabProperty $service 'pid') -ne $Listener.OwningProcess) {
        throw 'BLOCKED: backend identity does not match the current port owner. No process was stopped.'
    }
    $automation = Get-LabProperty $Status 'automation'
    if ((Get-LabProperty $Status 'recording') -isnot [bool] -or
        (Get-LabProperty $automation 'active') -isnot [bool]) {
        throw 'BLOCKED: backend recording or automation state is unknown. No process was stopped.'
    }
    if ((Get-LabProperty $Status 'capture_mode') -ne 'automatic_streams' -or
        (Get-LabProperty $automation 'enabled') -ne $true -or
        (Get-LabProperty $Status 'controller_output_enabled') -ne $true -or
        (Get-LabProperty $automation 'supported_collection_modes') -notcontains 'participant_study') {
        throw 'BLOCKED: the running backend lacks required launch settings. Establish rig and recording state before a deliberate restart. No process was stopped.'
    }
}

if (-not (Test-Path -LiteralPath $labPython)) {
    throw 'LAB_NOT_READY: .venv is missing. Double-click Setup-Lab.cmd, then retry.'
}
if (-not (Test-Path -LiteralPath $labServerSource)) {
    throw 'LAB_NOT_READY: scripts/dashboard_server.py is missing. Pull the current repository before launching.'
}
$labNode = (Get-Command node -ErrorAction Stop).Source
$labNodeVersion = [version]((& $labNode -p 'process.versions.node').Trim())
if ($labNodeVersion -lt [version]'22.13.0') {
    throw "LAB_NOT_READY: Node $labNodeVersion is too old. Install Node 22.13 or newer."
}
$labPythonVersion = [version]((& $labPython -c 'import sys; print(sys.version.split()[0])').Trim())
if ($labPythonVersion -lt [version]'3.10.0') {
    throw "LAB_NOT_READY: Python $labPythonVersion is too old. Recreate .venv with Python 3.10 or newer."
}
if (-not (Test-Path -LiteralPath (Join-Path $labDashboard 'node_modules/vinext/dist/cli.js'))) {
    throw 'LAB_NOT_READY: dashboard dependencies are missing. Double-click Setup-Lab.cmd, then retry.'
}

$labExpectedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $labServerSource).Hash.ToLowerInvariant()
$labStatus = Get-LabUrl 'http://127.0.0.1:8765/api/status'
$labBackendListener = Get-LabListener 8765
Assert-LabBackendState $labStatus $labBackendListener $labExpectedHash $labContract
$labDashboardListener = Get-LabListener 3000
$labPage = Get-LabUrl 'http://127.0.0.1:3000/api/status'
if ($null -ne $labDashboardListener -and $null -eq $labPage) {
    throw "BLOCKED: port 3000 is occupied (PID $($labDashboardListener.OwningProcess)), but its API did not respond. No process was stopped."
}
if ($null -ne $labPage) {
    $labProxyService = Get-LabProperty $labPage 'service'
    $labDirectService = Get-LabProperty $labStatus 'service'
    if ($null -eq $labStatus -or
        (Get-LabProperty $labProxyService 'source_sha256') -ne $labExpectedHash -or
        (Get-LabProperty $labProxyService 'pid') -ne (Get-LabProperty $labDirectService 'pid')) {
        throw 'BLOCKED: the existing dashboard is connected to a different or unidentified backend. No process was stopped.'
    }
}
$labService = Get-LabProperty $labStatus 'service'
$labRecording = [bool](Get-LabProperty $labStatus 'recording')
$labAutomation = Get-LabProperty $labStatus 'automation'
$labAutomaticActive = [bool](Get-LabProperty $labAutomation 'active')
$labTrialActive = $labRecording -or $labAutomaticActive

if ($CheckOnly) {
    Write-Host 'LAB PREFLIGHT (no services changed)'
    Write-Host "  Repository: $labRoot"
    Write-Host "  Backend source: $($labExpectedHash.Substring(0, 12))"
    Write-Host "  Python: $labPythonVersion ($labPython)"
    Write-Host "  Node: $labNodeVersion ($labNode)"
    if ($null -eq $labStatus) {
        Write-Host '  Backend: stopped (TCP port available; hardware not assessed)'
    }
    else {
        Write-Host "  Backend: current (PID $((Get-LabProperty $labService 'pid')))"
        Write-Host "  Active trial: $labTrialActive"
    }
    Write-Host "  Dashboard proxy: $([bool]$labPage)"
    Write-Host 'PREFLIGHT COMPLETE'
    exit 0
}

if ($null -ne $labStatus) {
    Write-Host "Reusing the current backend. Active trial: $labTrialActive. No process will be restarted."
}

New-Item -ItemType Directory -Path $labLog -Force | Out-Null
$labStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if ($null -eq $labStatus) {
    $labServer = Start-Process -FilePath $labPython -ArgumentList @(
        '-u', 'scripts/dashboard_server.py',
        '--enable-research-speed-output', '--enable-automatic-trials'
    ) -WorkingDirectory $labRoot -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $labLog "$labStamp-sensors.log") `
      -RedirectStandardError (Join-Path $labLog "$labStamp-sensors.err.log")
    for ($try = 0; $try -lt 30; $try++) {
        Start-Sleep -Milliseconds 500
        if ($labServer.HasExited) { throw "BACKEND_FAILED: read data/service-logs/$labStamp-sensors.err.log" }
        $labStatus = Get-LabUrl 'http://127.0.0.1:8765/api/status' 2
        if ($null -ne $labStatus) { break }
    }
}

$labService = Get-LabProperty $labStatus 'service'
$labFoundContract = [string](Get-LabProperty $labService 'contract')
$labFoundHash = [string](Get-LabProperty $labService 'source_sha256')
$labAutomation = Get-LabProperty $labStatus 'automation'
if ($null -eq $labStatus -or $labFoundContract -ne $labContract -or $labFoundHash -ne $labExpectedHash) {
    throw 'BACKEND_FAILED: the service did not prove that it is running the current source. Inspect the sensor log.'
}
Assert-LabBackendState $labStatus (Get-LabListener 8765) $labExpectedHash $labContract
if ((Get-LabProperty $labStatus 'capture_mode') -ne 'automatic_streams' -or
    -not [bool](Get-LabProperty $labAutomation 'enabled') -or
    -not [bool](Get-LabProperty $labStatus 'controller_output_enabled') -or
    (Get-LabProperty $labAutomation 'supported_collection_modes') -notcontains 'participant_study') {
    throw 'BACKEND_FAILED: the current service did not confirm participant automation and automatic capture.'
}

$labPage = Get-LabUrl 'http://127.0.0.1:3000/api/status'
if ($null -eq $labPage) {
    $labWeb = Start-Process -FilePath $labNode -ArgumentList @(
        'scripts/run-vinext.mjs', 'dev', '--host', '127.0.0.1', '--port', '3000', '--strictPort'
    ) -WorkingDirectory $labDashboard -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $labLog "$labStamp-dashboard.log") `
      -RedirectStandardError (Join-Path $labLog "$labStamp-dashboard.err.log")
    for ($try = 0; $try -lt 60; $try++) {
        Start-Sleep -Milliseconds 500
        if ($labWeb.HasExited) { throw "DASHBOARD_FAILED: read data/service-logs/$labStamp-dashboard.err.log" }
        $labPage = Get-LabUrl 'http://127.0.0.1:3000/api/status' 2
        if ($null -ne $labPage) { break }
    }
}
if ($null -eq $labPage) { throw 'DASHBOARD_FAILED: the dashboard proxy did not become ready.' }
$labProxyService = Get-LabProperty $labPage 'service'
if ((Get-LabProperty $labProxyService 'contract') -ne $labContract -or
    (Get-LabProperty $labProxyService 'source_sha256') -ne $labExpectedHash -or
    (Get-LabProperty $labProxyService 'pid') -ne (Get-LabProperty $labService 'pid')) {
    throw 'DASHBOARD_FAILED: the dashboard is not connected to the backend launched from this checkout.'
}

Start-Process 'http://localhost:3000'
Write-Host 'SERVICES READY (hardware and trial preflight still required)'
Write-Host "  Backend source: $($labExpectedHash.Substring(0, 12))"
Write-Host "  Logs: data/service-logs/$labStamp-*"
Write-Host '  Participant and qualification automation: enabled'
Write-Host '  Starting services alone does not move the robot. Start trial still performs the guarded preflight.'
