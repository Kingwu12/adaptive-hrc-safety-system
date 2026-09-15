# Compatibility entry point. Normal startup uses Start-Lab.cmd directly.
# scripts/lab_launcher.py owns startup; this wrapper changes no policy.
param([switch]$CheckOnly, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $PSScriptRoot '.venv/bin/python'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment missing. Use Setup-Lab.cmd during maintenance.'
}
$labArgs = @((Join-Path $PSScriptRoot 'scripts/lab_launcher.py'))
$labArgs += $(if ($CheckOnly) { 'check' } else { 'start' })
if ($NoBrowser) { $labArgs += '--no-browser' }
& $python @labArgs
exit $LASTEXITCODE
