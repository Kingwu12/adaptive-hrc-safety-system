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
        $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
            Select-Object -First 1
        if ($null -eq $connection) { return $null }
        return Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction Stop
    }
    catch { return $null }
}

function Test-LabPathEqual {
    param([string]$Left, [string]$Right)
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) { return $false }
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Stop-VerifiedLabListener {
    param(
        [int]$Port,
        [string]$Kind,
        [string]$ExpectedExecutable,
        [string]$RequiredCommandText
    )
    $process = Get-LabListener $Port
    if ($null -eq $process) {
        throw "Port $Port answered as $Kind, but Windows would not reveal its owner. The launcher will not guess or start a conflicting service."
    }
    $commandLine = [string](Get-LabProperty $process 'CommandLine')
    $executable = [string](Get-LabProperty $process 'ExecutablePath')
    $owned = (Test-LabPathEqual $executable $ExpectedExecutable) -and
        ($commandLine.IndexOf($RequiredCommandText, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    if (-not $owned) {
        throw "Port $Port is held by an unknown process (PID $($process.ProcessId)). The launcher will not kill it. Close it manually, then retry."
    }
    Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    for ($try = 0; $try -lt 20; $try++) {
        Start-Sleep -Milliseconds 250
        if ($null -eq (Get-LabListener $Port)) {
            Write-Host "Stopped verified stale $Kind service on port $Port."
            return $true
        }
    }
    throw "The verified $Kind service on port $Port did not stop."
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
$labPythonVersion = [version]((& $labPython -c 'import sys; print(".".join(map(str, sys.version_info[:3])))').Trim())
if ($labPythonVersion -lt [version]'3.10.0') {
    throw "LAB_NOT_READY: Python $labPythonVersion is too old. Recreate .venv with Python 3.10 or newer."
}
if (-not (Test-Path -LiteralPath (Join-Path $labDashboard 'node_modules/vinext/dist/cli.js'))) {
    throw 'LAB_NOT_READY: dashboard dependencies are missing. Double-click Setup-Lab.cmd, then retry.'
}

$labExpectedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $labServerSource).Hash.ToLowerInvariant()
$labStatus = Get-LabUrl 'http://127.0.0.1:8765/api/status'
$labService = Get-LabProperty $labStatus 'service'
$labFoundContract = [string](Get-LabProperty $labService 'contract')
$labFoundHash = [string](Get-LabProperty $labService 'source_sha256')
$labRecording = [bool](Get-LabProperty $labStatus 'recording')
$labAutomation = Get-LabProperty $labStatus 'automation'
$labAutomaticActive = [bool](Get-LabProperty $labAutomation 'active')
$labTrialActive = $labRecording -or $labAutomaticActive
$labBackendCurrent = ($labFoundContract -eq $labContract) -and
    ($labFoundHash -eq $labExpectedHash)

if ($CheckOnly) {
    Write-Host 'LAB PREFLIGHT (no services changed)'
    Write-Host "  Repository: $labRoot"
    Write-Host "  Backend source: $($labExpectedHash.Substring(0, 12))"
    Write-Host "  Python: $labPythonVersion ($labPython)"
    Write-Host "  Node: $labNodeVersion ($labNode)"
    if ($null -eq $labStatus) {
        if ($null -ne (Get-LabListener 8765)) {
            throw 'BLOCKED: port 8765 is occupied but did not answer as the FYP backend.'
        }
        Write-Host '  Backend: stopped (ready to start)'
    }
    elseif (-not $labBackendCurrent) {
        Write-Host "  Backend: STALE (contract '$labFoundContract', source '$labFoundHash')"
        if ($labTrialActive) { throw 'BLOCKED: a stale backend has an active recording or automatic cycle. Finish or abort it before restarting.' }
        Write-Host '  Resolution: double-click Start-Lab.cmd to replace the verified stale FYP service.'
    }
    else {
        Write-Host "  Backend: current (PID $((Get-LabProperty $labService 'pid')))"
        Write-Host "  Active trial: $labTrialActive"
    }
    $labPage = Get-LabUrl 'http://127.0.0.1:3000/api/status'
    Write-Host "  Dashboard proxy: $([bool]$labPage)"
    Write-Host 'PREFLIGHT COMPLETE'
    exit 0
}

if ($labTrialActive) {
    if (-not $labBackendCurrent) {
        throw 'BLOCKED: the running backend is stale and a trial is active. Finish or abort the trial before restarting services.'
    }
    Write-Host 'Active trial detected. Reusing the verified current backend; no process will be restarted.'
}
else {
    # A clean launch always replaces only services proven to belong to this checkout.
    # This prevents an old hidden process from serving yesterday's code after a pull.
    if (($null -ne $labStatus) -or ($null -ne (Get-LabListener 8765))) {
        Stop-VerifiedLabListener 8765 'backend' $labPython 'dashboard_server.py' | Out-Null
    }
    if ($null -ne (Get-LabListener 3000)) {
        Stop-VerifiedLabListener 3000 'dashboard' $labNode $labDashboard | Out-Null
    }
    $labStatus = $null
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
    (Get-LabProperty $labProxyService 'source_sha256') -ne $labExpectedHash) {
    throw 'DASHBOARD_FAILED: the dashboard is not connected to the backend launched from this checkout.'
}

Start-Process 'http://localhost:3000'
Write-Host 'LAB READY'
Write-Host "  Backend source: $($labExpectedHash.Substring(0, 12))"
Write-Host "  Logs: data/service-logs/$labStamp-*"
Write-Host '  Participant and qualification automation: enabled'
Write-Host '  Starting services alone does not move the robot. Start trial still performs the guarded preflight.'
