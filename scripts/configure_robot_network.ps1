[CmdletBinding()]
param(
    [string]$AdapterName = "Ethernet 6",
    [string]$ExpectedMac = "00-E0-4C-36-C7-44",
    [string]$PcAddress = "192.168.2.102",
    [string]$RobotAddress = "192.168.2.101",
    [int]$PrefixLength = 24,
    [switch]$CheckOnly,
    [switch]$Pause
)

$ErrorActionPreference = "Stop"

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 1000) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $attempt = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $attempt.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($attempt)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

try {
    $adapter = Get-NetAdapter -Name $AdapterName
    if ($adapter.MacAddress -ne $ExpectedMac) {
        throw "Refusing to configure ${AdapterName}: expected MAC $ExpectedMac, found $($adapter.MacAddress)."
    }

    Write-Host "Robot adapter: $AdapterName ($($adapter.InterfaceDescription))"
    Write-Host "Link: $($adapter.Status) at $($adapter.LinkSpeed)"

    if (-not $CheckOnly) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        $admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $admin) {
            throw "Administrator rights are required. Re-run this script from an Administrator PowerShell."
        }
        if ($adapter.Status -ne "Up") {
            throw "$AdapterName has no physical link. Check the robot Ethernet cable first."
        }

        Set-NetIPInterface -InterfaceAlias $AdapterName -AddressFamily IPv4 -Dhcp Disabled
        $existing = Get-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -eq $PcAddress }
        if (-not $existing) {
            New-NetIPAddress -InterfaceAlias $AdapterName -IPAddress $PcAddress `
                -PrefixLength $PrefixLength | Out-Null
        }
    }

    $addresses = Get-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue | Select-Object IPAddress, PrefixLength, AddressState
    $addresses | Format-Table -AutoSize
    $pcReady = $PcAddress -in @($addresses.IPAddress)

    $ping = $null -ne (ping.exe -n 1 -w 1000 $RobotAddress | Select-String "TTL=")
    $dashboard = Test-TcpPort $RobotAddress 29999
    $rtde = Test-TcpPort $RobotAddress 30004
    Write-Host "Robot ${RobotAddress}: ping=$ping dashboard29999=$dashboard rtde30004=$rtde"

    if (-not ($dashboard -and $rtde)) {
        if ($pcReady) {
            Write-Warning "PC adapter is prepared, but the robot is not responding yet. On the pendant set static IP $RobotAddress, mask 255.255.255.0, no gateway, then keep Remote Control enabled."
        }
        else {
            Write-Warning "$AdapterName still needs $PcAddress/$PrefixLength. Run this script as Administrator without -CheckOnly."
        }
        exit 2
    }
    Write-Host "ROBOT NETWORK READY" -ForegroundColor Green
}
finally {
    if ($Pause) { Read-Host "Press Enter to close" | Out-Null }
}
