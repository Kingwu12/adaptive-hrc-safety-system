# Central Windows lab — 16 September 2026

## The short path for the one-hour booking

1. **Update during maintenance**, with the rig confirmed idle and old services
   deliberately resolved. Preserve local recordings, calibration and taught poses.
2. Double-click **Check-Lab.cmd**. If it passes, skip dependency installation.
3. Double-click **Start-Lab.cmd**. Require **SERVICES READY**, then open
   **http://localhost:3000**. Browser auto-open failure does not invalidate startup.
4. Qualify the actual rig with the established supervised **Q-code** procedure
   before collecting participant data.

Start/Check now use CMD and the existing venv Python **directly**. They do not
execute PowerShell scripts, activate a venv, invoke npm.ps1, or change execution
policy. Start-Lab.ps1 is only a compatibility wrapper. Native executable policy,
firewall restrictions and AI command-tool restrictions still need their actual
error and approved remedy; the original reported policy block was never recovered.

## Before leaving the Mac

Bring the prepared **FYP-Windows-kit.zip**, extracted if transfer time matters.
It contains the Git update bundle, Windows Python wheels and the Windows npm cache.
Keep its SHA-256 and Windows test receipt with it. The kit is for **Windows x64,
Python 3.12 and Node 22.13+**. It does not install Python, Node or Git themselves.
These must already be present or available through the institution's approved
installation process. A working older lab venv can be checked without replacing it;
Setup intentionally refuses to overwrite a venv using a different Python version.

Software tests do not qualify the campus computer or physical rig. The hosted
Windows test runs no trial and issues no control API requests.

## Update without losing the lab's local state

Use **Command Prompt**, opened in the existing repository. Confirm an idle rig and
maintenance window first; an HTTP timeout does not prove stopped recording/motion.

```bat
git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin main
git merge --ff-only origin/main
```

Use the existing main checkout. Stop on a conflict or unexpected local edit;
retain those files. Do not reset, clean or overwrite the checkout. Both the model
and example taught poses are tracked; preserve the **actual rig's** calibrated
poses and extrinsics. File existence is not physical calibration proof.

If internet is unavailable, fetch the bundle instead (replace the kit path):

```bat
git fetch "C:\path\FYP-Windows-kit\source-update.bundle" main
git merge --ff-only FETCH_HEAD
robocopy "C:\path\FYP-Windows-kit\.lab-offline" ".lab-offline" /E /R:1 /W:1
```

Robocopy exit codes 0–7 are success/nonfatal differences; 8+ indicates a copy
failure. Do not use /MIR. Then run Check-Lab.cmd. Only run **Setup-Lab.cmd** if the
check identifies missing dependencies, while services are deliberately shut down.
Setup uses the supplied wheels/cache offline when `.lab-offline` is present.
Run Check again after Setup. Avoid doing a fresh installation during the booking
if the existing environment already passes.

## What Check / Start establish

The preflight checks Python and Node versions, actual RTDE/scientific imports,
loading the fitted model, required files and valid low/top joint-pose structure.
It checks listener PIDs and both direct/proxied status responses. Empty ports must
also permit binding. Unknown or stale services block startup and remain intact.
A backend loaded before a source/config change is rejected before trial start.

Start requires the current backend source SHA-256 and matching PID through both
endpoints, automatic stream capture, research output enabled, and automatic trial
support for both P and Q modes. The automation version is
`automatic-panel-v10-supervised-head-clearance`. Starting services alone does not start a trial.
An already compatible service is reused, including an active one; no process is
terminated or recording restarted by these launchers.

## If anything fails: capture once, identify the owner

Run **Diagnose-Lab.cmd**. It starts no service. It retains executable lookup,
read-only PowerShell policy scopes, exact errors and the consolidated preflight.
Keep `data/service-logs/bootstrap-*.txt` and `preflight-*.json`. If Python itself
is denied, the outer CMD diagnostic still records that executable error.
Raw service logs can contain a control URL/key; do not post them publicly.

If the AI tool says “blocked by policy” before running a command, retain its
full rejection and compare **Check-Lab.cmd in ordinary Command Prompt**. A tool
rejection and a Windows executable restriction are different diagnoses. If CMD or
Python is denied by a managed rule, retain the exact command/error and involve
lab support; no Mac-side change can verify or remove that institution rule.
See [the diagnostic guide](windows-startup-repair.md).

## Use the hour for qualification and collection

Aim to finish update/check/start in the first **5 minutes**. If blocked, capture
Diagnose immediately and use the offline kit only for a demonstrated dependency
failure. Set a **10-minute software troubleshooting limit** with the team; if a
managed restriction remains, use the captured evidence to seek lab support or
additional time. Do not consume the whole booking repeating the same launch.

Once software starts, follow the existing physical safeguards and qualification
procedure. Check the actual taught low/top poses, payload/support, robot/gripper
health, fresh OptiTrack/Xsens streams and body/hand tracking. Mark Xsens calibration
complete only after actual calibration and start within its five-minute window.
Run the supervised Q-code rehearsal and required stop/fault checks before P-code
release. The tracked-gesture task uses four corner dwells; follow its current
instruction and preserve the task fingerprint with the data.

A trial rejection must retain its full message. Common causes include expired
calibration, stale/incomplete tracking, robot telemetry, model/poses, changed source,
wrong P/Q collection mode or assigned slot, and low-pose/gripper/clearance checks.
Fix the demonstrated cause. Supervised manual is the default trial mode after
automatic qualification faults, but it still requires the same live tracking,
grip, robot and controller preflight. Do not fabricate calibration/status,
change thresholds or force-kill services to get past it. Advance each manual
phase only after the operator verifies the physical event. The dashboard saves
streams and controller decisions through supported low release; check the trial
manifest and survey completion before proceeding to the next assigned slot.
