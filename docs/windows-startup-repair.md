# Windows startup: identify the actual blocker

Start with the [one-hour lab handoff](windows-lab-2026-09-16.md).
The original reported “blocked by policy” error is still unidentified. Do not
assume a PowerShell cause from that phrase alone.

## Current entry points

- **Check-Lab.cmd** runs the read-only Python preflight and saves one JSON report.
- **Start-Lab.cmd** runs that preflight, verifies existing service identities, and
  starts only missing services. It never terminates a process.
- **Diagnose-Lab.cmd** also records executable lookup, Windows version and read-only
  PowerShell policy scopes. It captures Python execution failures outside Python.
- **Setup-Lab.cmd** installs the pinned Python 3.12 environment and dashboard.
  It refuses installation while either lab port has a service or unknown state.
  An operator must still establish an idle rig and maintenance window.

Normal Check/Start/Setup paths use CMD and executable paths directly. They do not
run `.ps1`, change execution policy or require venv activation. The old
Start-Lab.ps1 is a thin compatibility wrapper; use the CMD entry points instead.
`HRC_NONINTERACTIVE=1` suppresses pauses for bounded automated diagnostics.

## Match the error to the layer

**AI command-tool rejection:** retain the tool's full rejection, command and time.
If it rejected the request before execution, that is not evidence the backend
failed. Compare the harmless Check-Lab.cmd in ordinary Command Prompt. Inspect the
app's actual permissions/sandbox evidence; do not change robot settings.

**PowerShell script policy / npm.ps1 / Activate.ps1:** use Check-Lab.cmd,
Start-Lab.cmd and Setup-Lab.cmd. They select `.venv\Scripts\python.exe`, `node.exe`
and `npm.cmd` directly. No policy bypass is needed for this launch path.

**Windows denies CMD, Python, Node or another native executable:** keep the exact
executable path, exit code and complete error. A managed application-control rule
requires the institution's approved remedy. Do not repeatedly retry Bypass or
change machine-wide controls. The Mac and hosted Windows runner cannot prove the
campus machine's rule configuration.

**Missing imports/files/runtime:** retain the preflight report. During maintenance,
use Setup with the prepared `.lab-offline` wheels/npm cache. Setup requires Python
3.12, Node 22.13+ and npm already installed. It preserves a venv with an incompatible
Python version and reports that choice rather than deleting it.

**Port in use / stale source / unknown HTTP status:** establish the actual rig and
recording state before deliberately shutting down the identified old service.
A timeout, denied port inspection or unknown PID is never proof of idle. The new
launcher verifies source fingerprints, native listener ownership and proxy identity.
Current Check/Start never force-stop a backend, including an unidentified one.

**Browser cannot open:** retain the exact browser error; manually open
http://localhost:3000. Successful service startup stays successful. If the page
fails, compare direct http://127.0.0.1:8765/api/status with the dashboard proxy
http://127.0.0.1:3000/api/status and preserve the failing request/response.

**Start trial is refused:** preserve the complete rejection. Software startup,
automation availability, live sensor health and the guarded trial preflight are
separate stages. Structured P/Q trials now reject disabled/unknown automation
instead of silently posting a manual start. Follow the existing qualification
procedure; do not weaken interlocks or select a different mode to bypass a check.

## Evidence to keep

Keep the source commit, exact failed command, timestamp, exit code/stderr and
`data/service-logs/preflight-*.json` plus `bootstrap-*.txt`. These diagnostics omit
participant fields and control keys from status responses. Raw backend logs may
contain control keys: redact before sharing externally.

`SERVICES READY` establishes software startup only. Campus policy compatibility
and physical operation require their own on-device evidence.

Microsoft's explanation of PowerShell policy scopes:
https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies
