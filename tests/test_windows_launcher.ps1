param([Parameter(Mandatory = $true)][string]$LauncherPath)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Parse the real launcher, then load only its pure/diagnostic function definitions.
# This never runs its startup flow or talks to hardware.
$labTokens = $null
$labParseErrors = $null
$labAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $LauncherPath, [ref]$labTokens, [ref]$labParseErrors)
if ($labParseErrors.Count -gt 0) { throw ($labParseErrors | Out-String) }
foreach ($definition in $labAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}

# Guard against reintroducing automatic process termination.
$termination = $labAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -match '^(Stop-Process|taskkill(\.exe)?|kill|tskill(\.exe)?)$'
}, $true)
if ($termination.Count -gt 0) { throw 'Launcher must not terminate processes.' }

function Assert-Throws {
    param([scriptblock]$Action, [string]$Pattern)
    try { & $Action }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        return
    }
    throw "Expected rejection: $Pattern"
}

$labTestContract = 'adaptive-hrc-lab-backend-v1'
$labTestHash = 'test-startup-hash'
$labTestListener = [pscustomobject]@{ OwningProcess = 123; LocalPort = 8765 }

function New-LabTestStatus {
    return [pscustomobject]@{
        service = [pscustomobject]@{
            contract = $labTestContract; source_sha256 = $labTestHash; pid = 123
        }
        recording = $false
        capture_mode = 'automatic_streams'
        controller_output_enabled = $true
        automation = [pscustomobject]@{
            active = $false; enabled = $true
            supported_collection_modes = @('participant_study', 'qualification')
        }
    }
}

# Clean stopped state may start; occupied but unreadable must never imply idle.
Assert-LabBackendState $null $null $labTestHash $labTestContract
Assert-Throws {
    Assert-LabBackendState $null $labTestListener $labTestHash $labTestContract
} 'active trial cannot be ruled out'

$labTestStatus = New-LabTestStatus
Assert-LabBackendState $labTestStatus $labTestListener $labTestHash $labTestContract
$labTestStatus.recording = $true
$labTestStatus.automation.active = $true
Assert-LabBackendState $labTestStatus $labTestListener $labTestHash $labTestContract
# Passing here permits reuse only; the launcher contains no termination command.

$labTestStatus.service.source_sha256 = 'old'
Assert-Throws {
    Assert-LabBackendState $labTestStatus $labTestListener $labTestHash $labTestContract
} 'older or unidentified'
$labTestStatus = New-LabTestStatus
$labTestStatus.recording = $null
Assert-Throws {
    Assert-LabBackendState $labTestStatus $labTestListener $labTestHash $labTestContract
} 'state is unknown'
$labTestStatus = New-LabTestStatus
$labTestStatus.automation.enabled = $false
Assert-Throws {
    Assert-LabBackendState $labTestStatus $labTestListener $labTestHash $labTestContract
} 'required launch settings'
$labTestStatus = New-LabTestStatus
$labTestStatus.service.pid = 999
Assert-Throws {
    Assert-LabBackendState $labTestStatus $labTestListener $labTestHash $labTestContract
} 'current port owner'
Assert-Throws {
    Assert-LabBackendState ([pscustomobject]@{}) $labTestListener $labTestHash $labTestContract
} 'older or unidentified'

function Get-NetTCPConnection {
    [CmdletBinding()]
    param([string]$State)
    if ($script:labPortFailure) { throw 'Access denied by test fixture' }
    return $script:labPortRows
}
$script:labPortFailure = $false
$script:labPortRows = @()
if ($null -ne (Get-LabListener 8765)) { throw 'Empty port enumeration must return null.' }
$script:labPortRows = @($labTestListener)
if ((Get-LabListener 8765).OwningProcess -ne 123) { throw 'Wrong port owner.' }
$script:labPortFailure = $true
Assert-Throws { Get-LabListener 8765 } 'cannot inspect TCP port'

function Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    throw 'Connection timed out'
}
if ($null -ne (Get-LabUrl 'http://127.0.0.1:8765/api/status')) {
    throw 'HTTP failure must not produce a fabricated idle status.'
}
Write-Output 'LAUNCHER CHECKS PASSED'
