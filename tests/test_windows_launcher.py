from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from scripts import lab_launcher as lab
from scripts.dashboard_server import SERVICE_CONTRACT, service_identity

ROOT = Path(__file__).resolve().parents[1]


def test_backend_identity_binds_process_to_loaded_source():
    identity = service_identity()
    assert identity['contract'] == SERVICE_CONTRACT
    assert identity['pid'] > 0
    assert identity['source_sha256'] == hashlib.sha256((ROOT / 'scripts/dashboard_server.py').read_bytes()).hexdigest()


def test_windows_venv_interpreter_child_is_verified():
    lab.assert_started_process(789, 123, {789: 456, 456: 123, 123: 1})
    lab.assert_started_process(123, 123, {})


@pytest.mark.parametrize('parents', [{789: 999, 999: 1}, {}, {789: 456, 456: 789}])
def test_unrelated_or_unknown_backend_never_passes_as_our_child(parents):
    with pytest.raises(lab.Blocked, match='not the launched process'):
        lab.assert_started_process(789, 123, parents)


@pytest.fixture
def backend(tmp_path):
    (tmp_path / 'source.py').write_text('loaded source')
    return {'service': {'contract': lab.CONTRACT, 'pid': 123, 'source_sha256': 'current'},
            'runtime_files': {'source.py': hashlib.sha256(b'loaded source').hexdigest()},
            'recording': False, 'capture_mode': 'automatic_streams', 'controller_output_enabled': True,
            'automation': {'active': False, 'enabled': True,
                           'version': 'automatic-panel-v7-helmet-body-task',
                           'supported_collection_modes': ['participant_study', 'qualification']}}


def test_windows_ports_include_ipv6_and_translated_states():
    result = lab.windows_listeners('''Active Connections
  TCP  0.0.0.0:8765  0.0.0.0:0  LISTENING  123
  TCP  [::]:8765  [::]:0  ABHÖREN  123
  TCP  127.0.0.1:3000  0.0.0.0:0  正在侦听  456
  TCP  127.0.0.1:8765  127.0.0.1:52221  ESTABLISHED  123
  TCP  [::1]:3000  [::1]:55212  TIME_WAIT  0''')
    assert result == {8765: {123}, 3000: {456}}


@pytest.mark.parametrize('row', ['TCP 127.0.0.1:8765 0.0.0.0:0 LISTENING',
                                      'TCP [::]:3000 [::]:0 LISTENING nope',
                                      'TCP [::]:3000 [::]:0 LISTENING 0', 'TCP bad'])
def test_ambiguous_port_owners_never_mean_free(row):
    with pytest.raises(lab.Blocked):
        lab.windows_listeners(row)


def test_access_denied_to_bind_is_blocked(monkeypatch):
    class Denied:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): pass
        def bind(self, *args): raise PermissionError('denied by policy')
    monkeypatch.setattr(lab.socket, 'socket', lambda *args: Denied())
    with pytest.raises(lab.Blocked, match='denied by policy'):
        lab.require_free(8765)


@pytest.mark.parametrize('reason', [TimeoutError('timed out'), PermissionError('blocked by policy')])
def test_http_unknown_state_never_means_stopped(monkeypatch, reason):
    def fail(*args, **kwargs): raise URLError(reason)
    monkeypatch.setattr(lab, 'build_opener', lambda *args: SimpleNamespace(open=fail))
    with pytest.raises(lab.Blocked, match='unknown'):
        lab.status(8765)


def test_only_refused_http_can_mean_absent(monkeypatch):
    def fail(*args, **kwargs): raise URLError(ConnectionRefusedError())
    monkeypatch.setattr(lab, 'build_opener', lambda *args: SimpleNamespace(open=fail))
    assert lab.status(8765) is None


@pytest.mark.parametrize('mutation', ['hash', 'pid', 'recording', 'active', 'disabled', 'capture', 'output', 'modes', 'version', 'files'])
def test_rejects_stale_or_unknown_backend(backend, tmp_path, mutation):
    if mutation == 'hash': backend['service']['source_sha256'] = 'old'
    if mutation == 'pid': backend['service']['pid'] = 456
    if mutation == 'recording': del backend['recording']
    if mutation == 'active': del backend['automation']['active']
    if mutation == 'disabled': backend['automation']['enabled'] = False
    if mutation == 'capture': backend['capture_mode'] = 'manual'
    if mutation == 'output': backend['controller_output_enabled'] = False
    if mutation == 'modes': backend['automation']['supported_collection_modes'] = ['qualification']
    if mutation == 'version': backend['automation']['version'] = 'old'
    if mutation == 'files': del backend['runtime_files']
    with pytest.raises(lab.Blocked):
        lab.assert_backend(backend, {123}, 'current', tmp_path)


def test_source_change_detected_before_trial(backend, tmp_path):
    (tmp_path / 'source.py').write_text('changed under running service')
    with pytest.raises(lab.Blocked, match='changed since'):
        lab.assert_backend(backend, {123}, 'current', tmp_path)


def test_active_compatible_service_is_reused_without_launch_or_stop(backend, tmp_path, monkeypatch, capsys):
    backend['recording'] = backend['automation']['active'] = True
    monkeypatch.setattr(lab, 'listeners', lambda: {8765: {123}, 3000: {456}})
    monkeypatch.setattr(lab, 'status', lambda *args: copy.deepcopy(backend))
    def forbidden(*args, **kwargs): pytest.fail('must not launch/restart a compatible active service')
    monkeypatch.setattr(lab, 'launch_process', forbidden)
    lab.start({'errors': [], 'checks': {'backend_source_sha256': 'current'}}, no_browser=True, root=tmp_path)
    assert 'SERVICES READY' in capsys.readouterr().out
    assert backend['recording'] is True


def test_browser_failure_does_not_fail_verified_services(backend, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lab, 'listeners', lambda: {8765: {123}, 3000: {456}})
    monkeypatch.setattr(lab, 'status', lambda *args: backend)
    def browser(*args): raise OSError('browser blocked by policy')
    monkeypatch.setattr(lab.webbrowser, 'open', browser)
    lab.start({'errors': [], 'checks': {'backend_source_sha256': 'current'}}, root=tmp_path)
    output = capsys.readouterr().out
    assert 'SERVICES READY' in output and 'browser blocked by policy' in output


def test_unknown_occupied_service_never_launches(monkeypatch):
    monkeypatch.setattr(lab, 'listeners', lambda: {8765: {123}, 3000: set()})
    monkeypatch.setattr(lab, 'status', lambda *args: None)
    monkeypatch.setattr(lab, 'launch_process', lambda *a: pytest.fail('unexpected launch'))
    with pytest.raises(lab.Blocked, match='active trial cannot be ruled out'):
        lab.start({'errors': [], 'checks': {'backend_source_sha256': 'current'}})


def test_dashboard_must_proxy_same_backend(backend):
    other = copy.deepcopy(backend)
    other['service']['pid'] = 999
    with pytest.raises(lab.Blocked, match='different'):
        lab.assert_dashboard(other, {456}, backend, 'current')


def test_preflight_collects_all_errors_and_does_not_erase_failed_status(tmp_path, monkeypatch):
    monkeypatch.setattr(lab.shutil, 'which', lambda *a: None)
    monkeypatch.setattr(lab, 'listeners', lambda: {8765: set(), 3000: set()})
    def fail(*a): raise lab.Blocked('request denied')
    monkeypatch.setattr(lab, 'status', fail)
    report = lab.preflight(tmp_path)
    assert len(report['errors']) >= 6
    assert 'direct_status' not in report['checks']
    assert 'backend_state' not in report['checks']
    assert 'dashboard_state' not in report['checks']
    assert json.loads(lab.save_report(report, tmp_path).read_text()) == report


def test_reports_exclude_control_keys_and_participant_identity(backend):
    backend.update(control_key='secret', participant_id='P99', token='private')
    text = json.dumps(lab.safe_status(backend))
    assert not any(x in text for x in ('secret', 'P99', 'private'))
    assert 'secret' not in lab.redact('http://localhost/control?k=secret&x=1')


def test_failed_preflight_never_starts_process(monkeypatch):
    monkeypatch.setattr(lab, 'listeners', lambda: pytest.fail('must not reach mutation boundary'))
    with pytest.raises(lab.Blocked, match='Preflight failed'):
        lab.start({'errors': ['missing runtime'], 'checks': {}})


def test_native_command_failure_retains_original_error(monkeypatch):
    monkeypatch.setattr(lab.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 126, '', 'blocked by policy'))
    with pytest.raises(lab.Blocked, match='exited 126: blocked by policy'):
        lab.command(['python.exe'])
