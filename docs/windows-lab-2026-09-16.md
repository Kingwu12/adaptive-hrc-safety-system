# Central Windows lab handoff — 16 September 2026

## Before the experiment

Use the existing `Kingwu12/adaptive-hrc-safety-system` checkout on `main`.
Preserve local recordings, calibration, models and taught poses. Establish an
idle rig and a maintenance window before updating code or dependencies. Do not
pull or edit underneath a running experiment. An HTTP timeout does not prove idle.

The original “blocked by policy” message remains unidentified. Capture the exact
command, complete error and exit code if it recurs. A command-tool rejection,
Windows script/program policy, service failure and trial-preflight rejection
need different fixes. Do not guess that they are all PowerShell.

Claude reviewed source `b482297` in session
`ee6ca642-9434-493f-9031-a23747275205`; Codex independently reproduced the UI's
silent manual fallback and implemented the repairs. Updated startup preserves
successful service checks even if Windows cannot open the browser. Structured
trials now refuse disabled/unknown automation instead of posting a manual start.
No hardware interlock or calibration requirement was relaxed.

Mac validation: 119 focused Python/PowerShell checks and 8 UI request-behavior
checks passed; dashboard lint/build passed. Before the UI fix, all four cases
with disabled/missing automation posted a manual request and failed the new
regression check. Hardware calls were stubbed; no real trial was started.

## 1. Capture the machine state (read-only)

Run these in the existing checkout's PowerShell window. Retain exact errors:

```powershell
Get-Location
git status --short
git rev-parse HEAD
git remote -v
$PSVersionTable.PSVersion
whoami
Get-ExecutionPolicy -List
Get-Command python,py,node,npm,npm.cmd -All -ErrorAction SilentlyContinue |
    Select-Object Name,Source
Get-NetTCPConnection -State Listen -ErrorAction Stop |
    Where-Object { $_.LocalPort -in @(8765,3000) } |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

Probe each endpoint separately; connection refused before startup can be expected:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/status -TimeoutSec 5 |
    Select-Object service,recording,automation,capture_mode,controller_output_enabled
Invoke-RestMethod http://127.0.0.1:3000/api/status -TimeoutSec 5 |
    Select-Object service,recording,automation,capture_mode,controller_output_enabled
```

If even `Get-Location` is rejected by the AI command tool, retain that tool error
and compare the harmless command in a normal terminal. Do not change robot or
Windows settings to diagnose an agent-tool restriction.

## 2. Update during the confirmed maintenance window

After preserving local changes and deliberately resolving any old services:

```powershell
git fetch origin main
git log --oneline HEAD..origin/main
git diff --stat HEAD..origin/main
git pull --ff-only origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
Test-Path .\data\models\pilot_hmm.json
Test-Path .\data\taught_poses.json
```

Stop on a Git conflict; preserve local files. Both model and pose checks must
return True. The model is tracked in Git; taught poses must belong to this actual
rig. Neither file's existence proves its physical calibration is correct.

## 3. Check and start the software

1. Run `Check-Lab.cmd`. Keep its full output, including any first blocker.
2. Run `Setup-Lab.cmd` only if dependencies are missing/outdated, with services
   deliberately shut down. Re-run the check afterward.
3. Run `Start-Lab.cmd`. Require `SERVICES READY`, matching backend source SHA-256
   and PID through both endpoints, `capture_mode=automatic_streams`,
   `controller_output_enabled=true`, and `automation.enabled=true`.
4. Require `automation.version=automatic-panel-v7-helmet-body-task` and support
   for the chosen `participant_study` or `qualification` mode.
5. If automatic browser launch fails, preserve that exact error and open
   `http://localhost:3000` manually. It no longer makes successful service startup
   report failure. Confirm the page loads, is styled and polls the same backend.

Start/Check use a per-process PowerShell setting; Setup is a CMD dependency script.
If managed policy rejects execution, identify the enforced rule and use the
institution's approved remedy. The scripts do not override managed policy.
See [the full diagnostic guide](windows-startup-repair.md).

## 4. Qualify the actual rig before collecting participant data

Follow the team's established physical safeguards and qualification procedure.
Verify current taught low/top poses, payload/support, robot and gripper health,
fresh OptiTrack/Xsens streams, body/hand tracking and the intended task settings.
Mark Xsens calibration complete only after actual calibration; start within the
existing five-minute window. Do not merely re-mark an expired calibration.

Use a Q-code for a supervised qualification rehearsal. Confirm the actual guarded
cycle and required stop/fault checks on the rig before participant release.
The automatic tracked-gesture configuration uses four corner dwells; follow the
server's current instruction and keep its task fingerprint with the data.

If Start trial refuses, preserve its full message. Common checks include a changed
code/config fingerprint since startup, expired calibration, stale/missing tracking
or robot telemetry, missing model/poses, wrong P/Q mode, wrong assigned study slot,
or low-pose/gripper/clearance checks. Fix the demonstrated cause; do not lower
thresholds, fabricate status, switch to manual to get past it, or force-kill services.

Software checks completed on Mac are not proof of Windows policy compatibility
or physical experiment readiness. That proof remains the task for the lab PC.
