"""离线功能检查必须使用真实图像、依赖和程序消费路径。"""
from pathlib import Path
import json
import subprocess
import sys


def test_real_image_command_and_recovery_probe():
    from scripts.check_image_feature_closure import check
    result = check()
    assert result['passed'] and result['png_match']['matched']
    assert result['command_kinds'] == ['click', 'input_sequence', 'scroll']
    assert all(row['verified'] for row in result['recovery_consumption'])
    assert result['input_executed'] is False


def test_lightweight_dependency_versions_match_desktop_constraints():
    root = Path(__file__).resolve().parents[1]
    lightweight = (root / 'requirements/agent-runtime-win311.txt').read_text(encoding='utf-8')
    constraints = (root / 'requirements/desktop-runtime-constraints.txt').read_text(encoding='utf-8')
    for line in ('numpy==2.4.4', 'opencv-python==4.13.0.92'):
        assert line in lightweight.splitlines()
        assert line in constraints.splitlines()


def test_learning_entrypoint_image_feature_check(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / 'image-check.json'
    result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
        str(root / 'scripts/start_learning_workbench.py'), '--check-image-feature', str(report)],
        cwd=tmp_path, capture_output=True, timeout=45)
    assert result.returncode == 0, (report.read_text(encoding='utf-8') if report.exists() else result.stderr.decode('utf-8'))
    evidence = json.loads(report.read_text(encoding='utf-8'))
    assert evidence['passed'] and evidence['save_reopen'] and evidence['disable_persisted']
    assert evidence['png_match']['matched']


def test_normal_learning_entrypoint_is_unchanged(monkeypatch):
    from scripts import start_learning_workbench
    calls = []
    monkeypatch.setattr(start_learning_workbench, 'main', lambda args: calls.append(args) or 7)
    assert start_learning_workbench.entrypoint(['--data-dir', 'ordinary']) == 7
    assert calls == [['--data-dir', 'ordinary']]


def test_isolated_learning_payload_runs_real_image_editor(tmp_path):
    from scripts.build_learning_workbench import build_learning_source, verify_learning_source
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / 'source'
    manifest = build_learning_source(root, source)
    paths = {row['path'] for row in manifest['files']}
    assert {'scripts/check_learning_image_feature.py', 'scripts/check_image_feature_closure.py'} <= paths
    working = tmp_path / 'working'
    working.mkdir()
    rows = verify_learning_source(source, Path(sys.executable), working)
    assert rows[-1]['passed'] and rows[-1]['save_reopen'] and rows[-1]['png_match']['matched']
    assert Path(rows[-1]['runtime_root']) == source


def test_frozen_probe_reports_runtime_identity_without_normal_launch(tmp_path, monkeypatch):
    from scripts import start_learning_workbench, check_learning_image_feature
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'runtime'), raising=False)
    monkeypatch.setattr(start_learning_workbench, 'main', lambda args: (_ for _ in ()).throw(AssertionError('normal launch invoked')))
    monkeypatch.setattr(check_learning_image_feature, 'check', lambda: {'passed': True})
    report = tmp_path / 'identity.json'
    assert start_learning_workbench.entrypoint(['--check-image-feature', str(report)]) == 0
    evidence = json.loads(report.read_text(encoding='utf-8'))
    assert evidence['frozen'] is True and Path(evidence['runtime_root']) == tmp_path / 'runtime'
