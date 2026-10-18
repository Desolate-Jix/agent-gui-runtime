import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.learning_memory.workbench_launch import select_data_dir
from app.learning_memory import workbench_launch


def test_writable_probe_permission_denied_attempts_once(tmp_path, monkeypatch):
    attempts = []
    access_checks = []
    denied = PermissionError(13, 'creation denied')

    def deny(path, flags, mode=0o777):
        attempts.append(Path(path))
        raise denied

    monkeypatch.setattr(os, 'open', deny)
    monkeypatch.setattr(os, 'access', lambda *args: access_checks.append(args) or True)
    monkeypatch.setattr(workbench_launch.tempfile, 'TMP_MAX', 5)
    with pytest.raises(PermissionError) as error:
        workbench_launch._check_writable(tmp_path)
    assert error.value is denied
    assert len(attempts) == 1
    assert access_checks == []
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_collision_preserves_external_file(tmp_path, monkeypatch):
    original_open = os.open
    attempts = []
    external = b'external original bytes'

    def collide_once(path, flags, mode=0o777):
        path = Path(path)
        attempts.append(path)
        if len(attempts) == 1:
            path.write_bytes(external)
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, 'open', collide_once)
    workbench_launch._check_writable(tmp_path)
    assert len(attempts) == 2
    assert attempts[0] != attempts[1]
    assert attempts[0].read_bytes() == external
    assert not attempts[1].exists()
    assert list(tmp_path.iterdir()) == [attempts[0]]


def test_writable_probe_collision_exhaustion_is_bounded(tmp_path, monkeypatch):
    attempts = []

    def collide(path, flags, mode=0o777):
        attempts.append(Path(path))
        raise FileExistsError(17, 'already exists', str(path))

    monkeypatch.setattr(os, 'open', collide)
    monkeypatch.setattr(workbench_launch.tempfile, 'TMP_MAX', 8)
    with pytest.raises(FileExistsError):
        workbench_launch._check_writable(tmp_path)
    assert 1 < len(attempts) <= 3
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_success_closes_and_cleans_own_file(tmp_path, monkeypatch):
    original_open = os.open
    opened = []

    def observe(path, flags, mode=0o777):
        fd = original_open(path, flags, mode)
        opened.append((Path(path), flags, fd))
        return fd

    monkeypatch.setattr(os, 'open', observe)
    workbench_launch._check_writable(tmp_path)
    assert len(opened) == 1
    path, flags, fd = opened[0]
    assert flags & os.O_CREAT and flags & os.O_EXCL
    assert path.parent == tmp_path
    assert not path.exists()
    with pytest.raises(OSError):
        os.fstat(fd)
    assert list(tmp_path.iterdir()) == []


def test_first_selection_and_remembered_directory(tmp_path):
    data = tmp_path / '中文 data'
    data.mkdir()
    settings = tmp_path / 'settings.json'
    assert select_data_dir(None, settings, lambda: str(data)) == data
    assert json.loads(settings.read_text(encoding='utf-8')) == {'data_dir': str(data)}
    assert select_data_dir(None, settings, lambda: pytest.fail('unexpected picker')) == data


def test_explicit_directory_does_not_read_or_write_settings(tmp_path):
    settings = tmp_path / 'settings.json'
    settings.write_text('broken', encoding='utf-8')
    assert select_data_dir(tmp_path, settings, lambda: pytest.fail('picker')) == tmp_path
    assert settings.read_text(encoding='utf-8') == 'broken'


def test_cancel_creates_nothing(tmp_path):
    settings = tmp_path / 'new' / 'settings.json'
    assert select_data_dir(None, settings, lambda: '') is None
    assert not settings.parent.exists()


def test_corrupt_settings_do_not_fallback(tmp_path):
    settings = tmp_path / 'settings.json'
    settings.write_text('{bad', encoding='utf-8')
    with pytest.raises(ValueError, match='settings'):
        select_data_dir(None, settings, lambda: pytest.fail('picker'))


def test_unwritable_directory_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr('app.learning_memory.workbench_launch._check_writable', lambda path: (_ for _ in ()).throw(OSError('not writable')))
    with pytest.raises(OSError, match='not writable'):
        select_data_dir(tmp_path, tmp_path / 'settings.json', lambda: '')


def test_settings_write_error_is_not_ignored(tmp_path):
    parent = tmp_path / 'blocked-parent'
    parent.write_text('file', encoding='utf-8')
    settings = parent / 'settings.json'
    with pytest.raises(OSError):
        select_data_dir(None, settings, lambda: str(tmp_path))


def test_saved_missing_directory_does_not_fallback(tmp_path):
    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps({'data_dir': str(tmp_path / 'missing')}), encoding='utf-8')
    with pytest.raises(ValueError, match='existing directory'):
        select_data_dir(None, settings, lambda: pytest.fail('picker'))


def test_original_entry_receives_session_and_restores_arguments(tmp_path, monkeypatch):
    import sys
    original = sys.argv
    calls = []
    monkeypatch.setattr(workbench_launch.run_learning_memory_workbench, 'main', lambda: calls.append(list(sys.argv)) or 0)
    assert workbench_launch._run_workbench(tmp_path, tmp_path / 'session') == 0
    assert calls == [[original[0], '--data-dir', str(tmp_path), '--session-dir', str(tmp_path / 'session')]]
    assert sys.argv is original


@pytest.mark.parametrize('args', [['--check-startup', 'report.json'],
    ['--check-startup', 'report.json', '--data-dir', '.', '--session-dir', 'session']])
def test_check_mode_requires_explicit_data_and_forbids_attachment(args):
    with pytest.raises(SystemExit) as error:
        workbench_launch.main(args)
    assert error.value.code == 2


def test_check_mode_never_reads_personal_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench_launch, 'select_data_dir', lambda *args: pytest.fail('personal settings access'))
    monkeypatch.setattr(workbench_launch, '_check_startup', lambda data, report: 0)
    assert workbench_launch.main(['--data-dir', str(tmp_path), '--check-startup', str(tmp_path / 'report.json')]) == 0


def test_check_mode_error_writes_failure_report(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError('明确失败')
    monkeypatch.setattr(workbench_launch, '_check_startup', fail)
    report = tmp_path / 'report.json'
    assert workbench_launch.main(['--data-dir', str(tmp_path), '--check-startup', str(report)]) == 2
    assert json.loads(report.read_text(encoding='utf-8')) == {'passed': False, 'error': 'RuntimeError: 明确失败'}


@pytest.mark.parametrize('mode', ['first', 'first_nested', 'remembered', 'cancel'])
def test_real_qt_selection_to_workbench_lifecycle(tmp_path, mode):
    worker = r'''
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from app.learning_memory import workbench_launch as launch
application = QApplication([sys.argv[0]])
root, mode = Path(sys.argv[1]), sys.argv[2]
data = root / 'data'
data.mkdir()
settings = root / 'AgentGUIRuntime' / 'learning-workbench.json'
if mode == 'remembered':
    settings.parent.mkdir()
    settings.write_text(json.dumps({'data_dir': str(data)}), encoding='utf-8')
record = {'mode': mode, 'observed': False, 'picker': False, 'normal_close': False}
def choose(*args):
    assert mode != 'remembered'
    record['picker'] = True
    dialog = QDialog()
    if mode == 'first_nested':
        loop = QEventLoop()
        def finish():
            dialog.close()
            loop.quit()
        dialog.show()
        QTimer.singleShot(30, finish)
        loop.exec()
    else:
        QTimer.singleShot(30, dialog.reject if mode == 'cancel' else dialog.accept)
        dialog.exec()
    return '' if mode == 'cancel' else str(data)
QFileDialog.getExistingDirectory = choose
def inspect():
    app = QApplication.instance()
    windows = [w for w in app.topLevelWidgets() if hasattr(w, 'steps')]
    if not windows:
        return
    window = windows[0]
    record['observed'] = window.isVisible()
    if window.steps.is_busy or window.projects.is_busy or window.interfaces.pane.is_busy:
        QTimer.singleShot(50, inspect)
        return
    window.close()
    record['normal_close'] = not window.isVisible()
QTimer.singleShot(500, inspect)
record['result'] = launch.main([])
record['settings_exists'] = settings.exists()
record['library_exists'] = (data / 'memory-library').exists()
record['visible_windows'] = sum(w.isVisible() for w in QApplication.instance().topLevelWidgets())
print(json.dumps(record))
'''
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', LOCALAPPDATA=str(tmp_path), PYTHONUTF8='1')
    process = subprocess.run([sys.executable, '-c', worker, str(tmp_path), mode], cwd=Path(__file__).resolve().parents[1],
        env=environment, capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert process.returncode == 0, process.stderr
    record = json.loads(process.stdout.splitlines()[-1])
    assert record['result'] == 0 and record['visible_windows'] == 0, record
    if mode == 'cancel':
        assert record['picker'] and not record['observed'] and not record['settings_exists'] and not record['library_exists'], record
    else:
        assert record['observed'] and record['normal_close'] and record['settings_exists'] and record['library_exists'], record
