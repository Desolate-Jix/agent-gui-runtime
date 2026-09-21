"""交付依赖预检不能漏掉新增的只读功能入口。"""
import json
from pathlib import Path
import subprocess
import sys


def test_isolated_preflight_covers_read_text_without_running_it(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / 'entrypoints.json'
    result = subprocess.run([sys.executable, '-I', str(root / 'scripts/check_instant_entrypoints.py'),
                             '--root', str(root), '--report', str(report)],
                            cwd=tmp_path, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    evidence = json.loads(report.read_text(encoding='utf-8'))
    read = next((row for row in evidence.get('observation_operations', [])
                 if row.get('operation') == 'read_text'), None)
    assert read is not None, 'new read_text entrypoint is missing from delivery preflight'
    assert read['handler_imported'] and read['request_validated']
    assert not read['handler_executed']
    assert 'app.operation.screen_reading.captured_text' in evidence['local_module_sources']
    assert 'app.core.ocr_service' in evidence['local_module_sources']
    assert not evidence['input_executed'] and not evidence['screenshots_taken']


def test_isolated_preflight_covers_click_variants_and_owned_window_close(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / 'entrypoints.json'
    result = subprocess.run([sys.executable, '-I', str(root / 'scripts/check_instant_entrypoints.py'),
                             '--root', str(root), '--report', str(report)],
                            cwd=tmp_path, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    evidence = json.loads(report.read_text(encoding='utf-8'))
    variants = evidence.get('recognition_click_variants', [])
    assert {row['click_kind'] for row in variants} == {'single', 'double', 'right'}
    assert all(row['request_validated'] and not row['handler_executed'] for row in variants)
    close = next((row for row in evidence.get('window_operations', [])
                  if row['operation'] == 'close_launched_window'), None)
    assert close and close['handler_imported'] and close['request_validated']
    assert not close['handler_executed']
    assert 'app.core.window_close' in evidence['local_module_sources']
    assert not evidence['input_executed'] and not evidence['screenshots_taken']
