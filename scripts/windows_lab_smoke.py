"""Exercise actual Windows CMD entry points on a disposable GitHub runner only.

No trial or control API is called. The CI host is discarded after this job;
this script never stops services or runs on an operator's lab computer.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import lab_launcher as lab


def run(name, *args, expected=0):
    result = subprocess.run(['cmd.exe', '/d', '/c', name, *args], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    print(lab.redact(result.stdout + result.stderr))
    assert result.returncode == expected, (name, result.returncode)
    return result.stdout


def get(path):
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:3000' + path, timeout=90) as response:
        assert response.status == 200
        return response.read().decode('utf-8')


def main():
    assert sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true', 'Disposable Windows CI only'
    assert os.environ.get('PSExecutionPolicyPreference') == 'Restricted'
    assert not any(lab.listeners().values()), 'CI needs clean lab ports; never stops existing owners'
    run('Check-Lab.cmd')
    first = run('Start-Lab.cmd', '--no-browser')
    assert 'SERVICES READY' in first
    direct, proxy = lab.status(8765), lab.status(3000)
    assert direct['service'] == proxy['service']
    assert direct['recording'] is False and direct['automation']['active'] is False
    assert direct['automation']['version'] == 'automatic-panel-v7-helmet-body-task'
    assert direct['service']['source_sha256'] == hashlib.sha256((ROOT / 'scripts/dashboard_server.py').read_bytes()).hexdigest()
    page = get('/')
    css = re.findall(r'<link[^>]+href="([^"]+\.css(?:\?[^\"]*)?)"', page)
    assert css, 'Dashboard HTML did not include stylesheets'
    for path in css:
        assert len(get(path)) > 100, 'Missing/empty stylesheet'
    second = run('Start-Lab.cmd', '--no-browser')
    assert 'Reusing verified backend' in second
    assert lab.status(8765)['service']['pid'] == direct['service']['pid']
    run('Check-Lab.cmd')
    run('Diagnose-Lab.cmd')
    run('Setup-Lab.cmd', expected=1)
    assert lab.status(8765)['service']['pid'] == direct['service']['pid'], 'Maintenance refusal must leave service intact'
    receipt = {'platform': sys.platform, 'powershell_process_policy': 'Restricted',
               'actual_cmd_start_and_reuse': True, 'offline_setup': True,
               'page_and_stylesheets': True, 'active_service_setup_refused': True,
               'service': direct['service'], 'hardware_qualified': False, 'trial_started': False}
    (ROOT / '.lab-offline/windows-smoke.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print('WINDOWS LAB SMOKE PASSED')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # This is a disposable CI host, never the lab. Keep diagnostic evidence
        # before the runner disappears, with control keys redacted.
        print('WINDOWS FAILURE DIAGNOSTICS', flush=True)
        try:
            print('Native listeners:', lab.listeners(), flush=True)
            for port in lab.PORTS:
                try:
                    print(port, json.dumps(lab.safe_status(lab.status(port))), flush=True)
                except Exception as exc:
                    print(port, lab.redact(exc), flush=True)
        except Exception as exc:
            print(lab.redact(exc), flush=True)
        for path in sorted((ROOT / 'data/service-logs').glob('*.log')):
            print(path.name, lab.redact(path.read_text(errors='replace')[-12000:]), flush=True)
        raise
