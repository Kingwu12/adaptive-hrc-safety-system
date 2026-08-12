# xsens_reset_listener.ps1 - one-click MVN resets from the HRC dashboard
# Runs ON the Windows laptop that runs MVN. Listens on HTTP :9764 and,
# when poked, focuses the MVN window and presses the documented shortcut:
#   grid     -> Ctrl+Alt+G  (heading + position, the usual one)
#   heading  -> Ctrl+Alt+A  (axis reset only)
#   position -> Ctrl+0      (move character to origin)
#
# RUN AS ADMINISTRATOR (needed to bind the port + add the firewall rule):
#   powershell -ExecutionPolicy Bypass -File .\xsens_reset_listener.ps1
#
# Person must be standing still, facing the agreed +X direction, when
# the button is pressed. Never reset mid-recording.

Add-Type -AssemblyName System.Windows.Forms
$wsh = New-Object -ComObject WScript.Shell

# Firewall rule (idempotent)
if (-not (Get-NetFirewallRule -DisplayName "HRC Xsens Reset" -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName "HRC Xsens Reset" -Direction Inbound `
    -Protocol TCP -LocalPort 9764 -Action Allow | Out-Null
  Write-Host "Firewall rule added (TCP 9764 inbound)."
}

$keys = @{ "grid" = "^%g"; "heading" = "^%a"; "position" = "^0" }

function Focus-MVN {
  $p = Get-Process | Where-Object { $_.MainWindowTitle -like "*MVN*" } | Select-Object -First 1
  if (-not $p) { return $false }
  return $wsh.AppActivate($p.Id)
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://+:9764/")
$listener.Start()
Write-Host "Listening on :9764  (endpoints: /reset?type=grid|heading|position, /ping)"

while ($listener.IsListening) {
  $ctx = $listener.GetContext()
  $req = $ctx.Request
  $res = $ctx.Response
  $out = ""
  if ($req.Url.AbsolutePath -eq "/ping") {
    $out = '{"ok":true,"service":"xsens_reset_listener"}'
  } elseif ($req.Url.AbsolutePath -eq "/reset") {
    $type = $req.QueryString["type"]
    if (-not $type) { $type = "grid" }
    if ($keys.ContainsKey($type)) {
      if (Focus-MVN) {
        Start-Sleep -Milliseconds 400
        [System.Windows.Forms.SendKeys]::SendWait($keys[$type])
        $out = '{"ok":true,"reset":"' + $type + '"}'
        Write-Host "$(Get-Date -Format T)  reset: $type"
      } else {
        $res.StatusCode = 503
        $out = '{"ok":false,"error":"MVN window not found"}'
      }
    } else {
      $res.StatusCode = 400
      $out = '{"ok":false,"error":"unknown type"}'
    }
  } else {
    $res.StatusCode = 404
    $out = '{"ok":false,"error":"not found"}'
  }
  $bytes = [Text.Encoding]::UTF8.GetBytes($out)
  $res.ContentType = "application/json"
  $res.ContentLength64 = $bytes.Length
  $res.OutputStream.Write($bytes, 0, $bytes.Length)
  $res.OutputStream.Close()
}
