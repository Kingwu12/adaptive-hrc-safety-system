"""Lab startup and evidence collection. Standard library only; never stops services.

CMD and legacy PowerShell entry points delegate here. All HTTP is loopback-only,
all subprocess waits are bounded, and unknown service state blocks startup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "adaptive-hrc-lab-backend-v1"
PORTS = (8765, 3000)


class Blocked(RuntimeError):
    pass


def redact(text):
    return re.sub(r"(?i)([?&]k=|X-Control-Key[=: ]+|token[=: ]+)[^\s&\"']+",
                  r"\1[redacted]", str(text))


def command(args, *, cwd=ROOT, timeout=15):
    try:
        result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True,
                                text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(f"Cannot execute {args[0]}: {exc}") from exc
    if result.returncode:
        raise Blocked(f"{args[0]} exited {result.returncode}: "
                      f"{redact(result.stderr or result.stdout).strip()[-2500:]}")
    return result.stdout.strip()


def windows_listeners(text):
    """Parse numeric netstat -ano -p TCP. The remote :0 denotes a listener.

    Do not rely on translated column headings or the LISTENING spelling.
    Malformed target-port rows are an error, never an empty-port witness.
    """
    found = {port: set() for port in PORTS}
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].upper() != "TCP":
            continue
        try:
            port = int(parts[1].rsplit(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise Blocked(f"Unrecognised TCP row from netstat: {line}") from exc
        if port not in PORTS:
            continue
        try:
            if len(parts) != 5:
                raise ValueError("expected TCP/local/remote/state/PID")
            remote_port = int(parts[2].rsplit(":", 1)[1])
            pid = int(parts[4])
            if remote_port == 0:
                if pid <= 0:
                    raise ValueError("listener PID must be positive")
                found[port].add(pid)
        except (IndexError, ValueError) as exc:
            raise Blocked(f"Cannot identify port {port} owner: {line}") from exc
    return found


def listeners():
    if os.name == "nt":
        return windows_listeners(command(["netstat.exe", "-ano", "-p", "TCP"]))
    # lsof exit 1 with no output means no matching listeners. Other failures block.
    exe = shutil.which("lsof")
    if not exe:
        raise Blocked("lsof is required to identify local port owners")
    try:
        result = subprocess.run([exe, "-nP", "-iTCP:8765", "-iTCP:3000",
                                 "-sTCP:LISTEN", "-FpPn"], capture_output=True,
                                text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(f"Cannot inspect TCP listeners: {exc}") from exc
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise Blocked(f"Cannot inspect TCP listeners: {result.stderr}")
    found = {port: set() for port in PORTS}
    pid = None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            port = int(line.rsplit(":", 1)[1].split()[0])
            if port in found:
                found[port].add(pid)
    return found


def require_free(port):
    """A successful bind supplements enumeration; access denied is not 'free'."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
    except OSError as exc:
        raise Blocked(f"Port {port} is occupied or bind is denied: {exc}") from exc


def status(port, timeout=5):
    # Windows can take over two seconds to report WSAECONNREFUSED even on
    # loopback. A shorter deadline misclassifies a closed port as unknown.
    url = f"http://127.0.0.1:{port}/api/status"
    try:
        # Corporate HTTP_PROXY settings must never route local rig status elsewhere.
        with build_opener(ProxyHandler({})).open(url, timeout=timeout) as response:
            payload = json.loads(response.read(2_000_000))
        if not isinstance(payload, dict):
            raise ValueError("status is not a JSON object")
        return payload
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError) or getattr(reason, "errno", None) in (61, 111, 10061):
            return None
        raise Blocked(f"{url}: {exc}; service state is unknown") from exc
    except (OSError, ValueError) as exc:
        raise Blocked(f"{url}: {exc}; service state is unknown") from exc


def assert_backend(value, owners, expected_hash, root=ROOT):
    if value is None:
        if owners:
            raise Blocked(f"Port 8765 is occupied by {sorted(owners)} but status is unavailable; an active trial cannot be ruled out")
        require_free(8765)
        return
    service = value.get("service") or {}
    if service.get("contract") != CONTRACT or service.get("source_sha256") != expected_hash:
        raise Blocked("Older or unidentified backend is running. Establish rig/recording state before deliberate shutdown")
    if owners != {service.get("pid")} or type(service.get("pid")) is not int:
        raise Blocked("Backend identity does not match the port owner")
    runtime_files = value.get("runtime_files")
    if not isinstance(runtime_files, dict) or not runtime_files:
        raise Blocked("Backend did not report its startup source fingerprints")
    for name, digest in runtime_files.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise Blocked("Invalid runtime source path in backend identity")
        if name.endswith((".py", ".tsx")) or name == "configs/mocap_extrinsics.yaml":
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise Blocked(f"Study code/config changed since service startup: {name}; resolve rig state before restart")
    automation = value.get("automation") or {}
    if type(value.get("recording")) is not bool or type(automation.get("active")) is not bool:
        raise Blocked("Backend recording/automation state is unknown")
    if (value.get("capture_mode") != "automatic_streams"
            or automation.get("enabled") is not True
            or automation.get("version") != "automatic-panel-v7-helmet-body-task"
            or value.get("controller_output_enabled") is not True
            or not {"participant_study", "qualification"}.issubset(automation.get("supported_collection_modes") or [])):
        raise Blocked("Backend lacks required automatic trial/capture settings; resolve rig state before restarting")


def assert_dashboard(value, owners, backend, expected_hash):
    if value is None:
        if owners:
            raise Blocked(f"Port 3000 is occupied by {sorted(owners)} but its API is unavailable")
        require_free(3000)
        return
    service = value.get("service") or {}
    if (not owners or backend is None or service.get("contract") != CONTRACT
            or service.get("source_sha256") != expected_hash
            or service.get("pid") != (backend.get("service") or {}).get("pid")):
        raise Blocked("Dashboard is connected to a different or unidentified backend")


def safe_status(value):
    if value is None:
        return None
    # Explicit allowlist: no participant IDs, form tokens or local control keys.
    result = {k: value.get(k) for k in ("recording", "capture_mode", "controller_output_enabled",
                                       "connected", "stale", "optitrack_connected")}
    result["service"] = {k: (value.get("service") or {}).get(k)
                         for k in ("contract", "pid", "source_sha256", "started_at")}
    result["automation"] = {k: (value.get("automation") or {}).get(k)
                            for k in ("enabled", "active", "version", "phase", "fault", "supported_collection_modes")}
    result["runtime_files"] = value.get("runtime_files")
    return result


def preflight(root=ROOT):
    report = {"schema": 1, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "platform": sys.platform, "root": str(root), "checks": {}, "errors": []}
    def check(name, fn):
        try:
            value = fn()
            report["checks"][name] = value
            return value
        except Exception as exc:
            report["errors"].append(f"{name}: {redact(exc)}")
            return None

    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    def runtime():
        if not python.is_file():
            raise Blocked(".venv Python is missing. Run Setup-Lab.cmd during maintenance")
        version = command([python, "-c", "import sys; print('.'.join(map(str,sys.version_info[:3])))"], cwd=root)
        if tuple(map(int, version.split("."))) < (3, 10):
            raise Blocked(f"Python {version} is unsupported; use Python 3.12")
        return {"path": str(python), "version": version}
    check("python", runtime)
    node = shutil.which("node.exe" if os.name == "nt" else "node")
    def node_runtime():
        if not node:
            raise Blocked("Node is missing from PATH; Node 22.13 or newer is required")
        version = command([node, "-p", "process.versions.node"], cwd=root)
        if tuple(map(int, version.split("."))) < (22, 13, 0):
            raise Blocked(f"Node {version} is too old; Node 22.13 or newer is required")
        return {"path": node, "version": version}
    check("node", node_runtime)
    def dependencies():
        return command([python, "-c", "import numpy, scipy, yaml, rtde_control, rtde_receive, rtde_io; from scripts import dashboard_server; dashboard_server.load_upper_hmm('data/models/pilot_hmm.json'); print('imports and fitted model OK')"], cwd=root, timeout=25)
    if report["checks"].get("python"):
        check("python_dependencies", dependencies)
    def files():
        required = ("data/models/pilot_hmm.json", "data/taught_poses.json",
                    "configs/default.yaml", "configs/mocap_extrinsics.yaml",
                    "dashboard/node_modules/vinext/dist/cli.js")
        missing = [p for p in required if not (root / p).is_file()]
        if missing:
            raise Blocked("Missing required files: " + ", ".join(missing))
        for name in required[:2]:
            json.loads((root / name).read_text(encoding="utf-8"))
        poses = json.loads((root / "data/taught_poses.json").read_text(encoding="utf-8"))
        for name in ("pose1_low", "pose2_top"):
            q = poses.get(name, {}).get("q", [])
            if len(q) != 6 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in q):
                raise Blocked(f"Missing/invalid taught {name} joint pose; preserve and restore this rig's poses")
        return list(required)
    check("required_files", files)
    expected_hash = check("backend_source_sha256", lambda: hashlib.sha256((root / "scripts/dashboard_server.py").read_bytes()).hexdigest())
    owners = check("port_owners", lambda: {str(p): sorted(v) for p, v in listeners().items()})
    direct = check("direct_status", lambda: safe_status(status(8765)))
    proxy = check("proxy_status", lambda: safe_status(status(3000)))
    if owners is not None and expected_hash:
        # Failed HTTP checks never become a fabricated stopped-service state.
        if "direct_status" in report["checks"]:
            check("backend_state", lambda: assert_backend(direct, set(owners["8765"]), expected_hash, root) or "OK")
        if "proxy_status" in report["checks"]:
            check("dashboard_state", lambda: assert_dashboard(proxy, set(owners["3000"]), direct, expected_hash) or "OK")
    return report


def save_report(report, root=ROOT):
    folder = root / "data/service-logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"preflight-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return path
    except OSError as exc:
        raise Blocked(f"Cannot write diagnostic/service logs to {folder}: {exc}") from exc


def launch_process(args, cwd, log_name, root=ROOT):
    folder = root / "data/service-logs"
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{log_name}"
    try:
        with base.with_suffix(".log").open("ab") as out, base.with_suffix(".err.log").open("ab") as err:
            child = subprocess.Popen([str(a) for a in args], cwd=cwd, stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as exc:
        raise Blocked(f"Cannot start {log_name}: {exc}") from exc
    print(f"Started {log_name} PID {child.pid}; logs: {base}.*")
    return child


def wait_status(port, child, expected_hash, backend=None, timeout=60, root=ROOT):
    deadline = time.monotonic() + timeout
    last_error = "not yet responding"
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise Blocked(f"Service on port {port} exited {child.returncode}; read its .err.log")
        try:
            value = status(port, timeout=1)
        except Blocked as exc:
            last_error = str(exc)
            value = None
        if value is not None:
            owners = listeners()
            if port == 8765:
                assert_backend(value, owners[port], expected_hash, root)
                if value["service"]["pid"] != child.pid:
                    raise Blocked("Port 8765 was taken by a different process during startup")
            else:
                assert_dashboard(value, owners[port], backend, expected_hash)
            return value
        time.sleep(0.3)
    raise Blocked(f"Port {port} did not become ready within {timeout}s: {last_error}. Started processes were left intact for inspection")


def start(report, *, no_browser=False, root=ROOT):
    if report["errors"]:
        raise Blocked("Preflight failed; no services started")
    checks = report["checks"]
    expected_hash = checks["backend_source_sha256"]
    # Re-probe at the mutation boundary; never act on a prior cached check.
    owners = listeners()
    direct, proxy = status(8765), status(3000)
    assert_backend(direct, owners[8765], expected_hash, root)
    assert_dashboard(proxy, owners[3000], direct, expected_hash)
    if direct is None:
        child = launch_process([checks["python"]["path"], "-u", "scripts/dashboard_server.py",
                                "--enable-research-speed-output", "--enable-automatic-trials"], root, "backend", root)
        direct = wait_status(8765, child, expected_hash, root=root)
    else:
        print(f"Reusing verified backend PID {direct['service']['pid']}; no service restarted")
    if proxy is None:
        # Re-check after waiting for backend; another dashboard may have appeared.
        proxy = status(3000)
        assert_dashboard(proxy, listeners()[3000], direct, expected_hash)
        if proxy is None:
            child = launch_process([checks["node"]["path"], "scripts/run-vinext.mjs", "dev",
                                    "--host", "127.0.0.1", "--port", "3000", "--strictPort"], root / "dashboard", "dashboard", root)
            proxy = wait_status(3000, child, expected_hash, backend=direct, timeout=90)
    print("SERVICES READY (hardware and trial preflight still required)")
    print(f"Backend PID {direct['service']['pid']}; source {expected_hash}")
    print("Open http://localhost:3000 . Starting services alone does not start a trial.")
    if not no_browser:
        try:
            if not webbrowser.open("http://localhost:3000"):
                print("Browser did not open; use the URL above manually")
        except Exception as exc:
            print(f"Browser launch failed: {exc}. Use the URL above manually")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("start", "check", "diagnose", "maintenance-check"), nargs="?", default="start")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "maintenance-check":
        try:
            owners = listeners()
            for port in PORTS:
                if owners[port] or status(port) is not None:
                    raise Blocked(f"Port {port} has a service. Establish rig state and deliberately shut services down before setup")
                require_free(port)
            print("No lab services found. Setup still requires an operator-confirmed idle rig.")
            return 0
        except Exception as exc:
            print(f"SETUP BLOCKED: {redact(exc)}", file=sys.stderr)
            return 1
    report = preflight()
    print(json.dumps(report, indent=2))
    try:
        path = save_report(report)
        print(f"Diagnostic report: {path}")
        if report["errors"]:
            print("BLOCKED: " + "\nBLOCKED: ".join(report["errors"]))
            return 1
        if args.mode == "start":
            start(report, no_browser=args.no_browser)
        else:
            print("PREFLIGHT COMPLETE (no services or policy changed; hardware not qualified)")
        return 0
    except Exception as exc:
        print(f"BLOCKED: {redact(exc)}", file=sys.stderr)
        print("No existing service was stopped. Keep this error and data/service-logs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
