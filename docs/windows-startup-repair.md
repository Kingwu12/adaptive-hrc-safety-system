# Windows startup: diagnose the actual blocker

Use this on the central Windows FYP computer. Repository:
https://github.com/Kingwu12/adaptive-hrc-safety-system (main).

The Mac chat has not recovered the original policy error. PowerShell execution
policy is a possibility, not the established cause. Full access in the AI app
does not establish the Windows user's elevation or the policy that rejected a
command. Read the failing command and its actual error before choosing a fix.

## 1. Capture evidence before changing the environment

Find the existing checkout and inspect `git status --short`, `git remote -v`, and
`git rev-parse HEAD`. Preserve local lab edits, calibration, models and recordings.
Do not reinstall dependencies, pull code underneath running experiments, or stop
services until the operator and service state establish that this is a maintenance
window. An HTTP timeout does not prove that recording or motion has stopped.

Use read-only commands in the existing PowerShell terminal:

```powershell
Get-Location
$PSVersionTable.PSVersion
whoami
Get-ExecutionPolicy -List
Get-Command python,py,node,npm,npm.cmd -All -ErrorAction SilentlyContinue |
    Select-Object Name,Source
Get-NetTCPConnection -State Listen -ErrorAction Stop |
    Where-Object { $_.LocalPort -in @(8765,3000) } |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

Probe each address separately and keep the exact error if it fails:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/status -TimeoutSec 5 |
    Select-Object service,recording,automation,capture_mode,controller_output_enabled
Invoke-RestMethod http://127.0.0.1:3000/api/status -TimeoutSec 5 |
    Select-Object service,recording,automation,capture_mode,controller_output_enabled
```

Capture the original failed command, exit code and stderr. If the AI's command
tool rejects even `Get-Location` before PowerShell executes, preserve that tool
error. It is not evidence that the FYP backend or PowerShell script policy failed.
Inspect the active app permissions and its relevant sandbox log. An operator can
compare the same harmless command in a normal terminal if the agent cannot execute
it. Redact tokens, control keys and participant identities from diagnostic output.

## 2. Fix the layer identified by the evidence

- A `PSSecurityException` mentioning `.ps1` or disabled script execution points to
  PowerShell script policy. Inspect the scopes above. For an ordinary local rule,
  use the supplied `Start-Lab.cmd` after completing the maintenance checks. It
  launches one PowerShell process with `-ExecutionPolicy Bypass`. Use `npm.cmd`
  when the failing command selected `npm.ps1`; use the venv Python executable
  directly instead of activating the environment with `Activate.ps1`.
- A configured `MachinePolicy` or `UserPolicy` can override the process setting.
  Identify the exact enforced rule and approved remedy. Do not repeatedly retry
  Bypass or disable institution-wide controls. If administrator action is needed,
  report the particular action and Windows error requiring it.
- Connection refused, address already in use, missing imports, stale service
  identity and HTTP errors are different failures. Inspect the matching listener
  and `data/service-logs` entries; repair only the demonstrated cause. A backend
  already answering HTTP has started, so investigate the failing operation itself.
- A browser policy error requires its exact browser-console message and request.
  Compare direct backend HTTP with the dashboard proxy before changing any browser,
  firewall or backend access rule.

Microsoft's policy precedence reference:
https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies

OpenAI's Windows execution and sandbox troubleshooting:
https://learn.chatgpt.com/docs/windows/windows-sandbox

## 3. Update and verify during maintenance

After establishing a safe maintenance window, preserve local edits, fetch main,
and update without destructive reset. Read the latest launcher. The earlier
`d96950f` launcher could force-stop a service following a failed status query;
use the subsequent version that contains `Assert-LabBackendState` and no
`Stop-Process`. Current launchers never terminate existing services automatically.

Run setup only for demonstrated missing/outdated dependencies and with the lab
services deliberately shut down. Use `Setup-Lab.cmd` interactively, or the commands
inside it with explicit exit-code checks in the agent. The CMD files pause for a
human and are not intended as unattended diagnostic tools.

Use `powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\Start-Lab.ps1 -CheckOnly`
for the software check. Once any existing service is deliberately resolved, remove
`-CheckOnly` to launch. If a running service is stale, establish its recording and
rig state before arranging a graceful shutdown; do not force-kill the robot backend.

Re-run the originally failing command and inspect both HTTP status endpoints.
They must report the current backend source SHA-256, matching process identity,
and required capabilities. Open the dashboard and verify that styling and normal
read-only status polling work. Do not start a trial, change robot/gripper state,
weaken interlocks, or alter the experiment protocol to prove software startup.

Report the exact failure, its owner, the change made, and the confirming output.
`SERVICES READY` proves only software startup. Actual Windows policy enforcement,
native port inspection and physical operation require evidence on Windows.
