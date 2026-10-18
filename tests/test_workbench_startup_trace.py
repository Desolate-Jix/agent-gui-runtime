"""离屏真实 Qt 事件日志不得改变关闭行为或泄漏用户标题。"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def _run(tmp_path, script, *arguments):
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", LOCALAPPDATA=str(tmp_path))
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script,
        str(tmp_path), *arguments], env=environment, cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("mode", ["normal", "ignored_close", "write_failure"])
def test_real_qt_events_detach_and_failure_do_not_change_exit_policy(tmp_path, mode):
    script = r'''
import gc, json, sys, weakref
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from app.learning_memory.workbench_startup_trace import StartupTrace, TraceWriteError
application = QApplication([])
root, mode = Path(sys.argv[1]), sys.argv[2]
path = root / 'trace.jsonl'
class Window(QWidget):
    def closeEvent(self, event):
        if mode == 'ignored_close':
            event.ignore()
        else:
            super().closeEvent(event)
window = Window()
window.setObjectName('\u5b66\u4e60\u7a97\u53e3')
window.setWindowTitle('PRIVATE_TITLE_NOT_FOR_TRACE')
child = QWidget(window)
child.setObjectName('private-child')
trace = StartupTrace(application, path)
with trace:
    trace.record('before_workbench')
    window.show()
    child.show()
    if mode == 'write_failure':
        trace._stream.close()
        QTimer.singleShot(10, window.hide)
        QTimer.singleShot(30, lambda: application.exit(7))
    else:
        QTimer.singleShot(10, window.close)
        if mode == 'ignored_close':
            QTimer.singleShot(30, lambda: application.exit(7))
    code = application.exec()
    visible = window.isVisible()
    if mode == 'write_failure':
        try:
            trace.record('workbench_return', exit_code=code)
        except TraceWriteError:
            pass
    else:
        trace.exit_code = code
        trace.record('workbench_return', exit_code=code)
size = path.stat().st_size
window.hide()
application.processEvents()
assert path.stat().st_size == size
rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
assert 'PRIVATE_TITLE_NOT_FOR_TRACE' not in path.read_text(encoding='utf-8')
assert not any(row.get('object_name') == 'private-child' for row in rows)
reference = weakref.ref(trace)
del trace
gc.collect()
assert reference() is None, 'application retained detached trace callbacks'
print(json.dumps({'code': code, 'visible': visible, 'events': rows}))
'''
    if mode == "write_failure":
        # 真正的关闭流故障必须在 context 退出时失败，不能被 Qt 回调吞成成功。
        script = script.replace("with trace:\n", "try:\n    with trace:\n")
        start = script.index("    trace.record('before_workbench')")
        end = script.index("size = path.stat()")
        script = script[:start] + "".join("    " + line if line.strip() else line
            for line in script[start:end].splitlines(True)) + script[end:]
        script = script.replace("size = path.stat()", "except TraceWriteError:\n    pass\nelse:\n    raise AssertionError('lost log failure')\nsize = path.stat()")
    result = _run(tmp_path, script, mode)
    assert result["code"] == (0 if mode == "normal" else 7)
    if mode == "ignored_close":
        assert result["visible"] is True
    elif mode == "normal":
        assert result["visible"] is False
        events = [row["event"] for row in result["events"]]
        assert "last_window_closed" in events and "about_to_quit" in events
        assert "qt_quit" in events
        assert any(row.get("object_name") == "学习窗口" for row in result["events"])


def test_trace_requires_absolute_new_file_and_preserves_existing_bytes(tmp_path):
    script = '''
import json, sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app.learning_memory.workbench_startup_trace import StartupTrace, TraceWriteError
application = QApplication([])
root = Path(sys.argv[1])
path = root / 'existing.jsonl'
path.write_bytes(b'original evidence')
for candidate in (Path('relative.jsonl'), path):
    try:
        StartupTrace(application, candidate)
    except TraceWriteError:
        pass
    else:
        raise AssertionError('accepted invalid trace path')
assert path.read_bytes() == b'original evidence'
print(json.dumps({'preserved': True}))
'''
    assert _run(tmp_path, script)["preserved"]


def test_log_failure_keeps_business_exception_relationship_and_closes_on_entry_failure(tmp_path):
    script = '''
import json, os, sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app.learning_memory.workbench_startup_trace import StartupTrace, TraceWriteError
application = QApplication([])
root = Path(sys.argv[1])
business = ValueError('business failure')
trace = StartupTrace(application, root / 'both.jsonl')
try:
    with trace:
        trace._stream.close()
        raise business
except TraceWriteError as failure:
    assert failure.__cause__ is business
else:
    raise AssertionError('both errors lost')
entered = StartupTrace(application, root / 'entry.jsonl')
os.close(entered._stream.fileno())
try:
    with entered:
        raise AssertionError('entry should fail')
except TraceWriteError:
    pass
assert entered._stream.closed
print(json.dumps({'preserved': True}))
'''
    assert _run(tmp_path, script)["preserved"]


def test_check_startup_does_not_enable_normal_trace(tmp_path, monkeypatch):
    from app.learning_memory import workbench_launch
    monkeypatch.setattr(workbench_launch, "_check_startup", lambda *arguments: 0)
    destination = tmp_path / "unused.jsonl"
    assert workbench_launch.main(["--data-dir", str(tmp_path), "--check-startup",
        str(tmp_path / "report.json"), "--startup-trace", str(destination)]) == 0
    assert not destination.exists()


@pytest.mark.parametrize("mode", ["normal", "cancel", "error"])
def test_normal_launcher_trace_records_boundaries_and_exit(tmp_path, mode):
    script = '''
import json, sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from app.learning_memory import workbench_launch as launch
application = QApplication([])
root, mode = Path(sys.argv[1]), sys.argv[2]
data = root / 'data'
data.mkdir()
def choose(*arguments):
    dialog = QDialog()
    QTimer.singleShot(10, dialog.reject if mode == 'cancel' else dialog.accept)
    dialog.exec()
    if mode == 'error':
        raise RuntimeError('private input must not be logged')
    return '' if mode == 'cancel' else str(data)
QFileDialog.getExistingDirectory = choose
QMessageBox.critical = lambda *arguments: None
def inspect():
    windows = [window for window in application.topLevelWidgets() if hasattr(window, 'steps')]
    if not windows:
        QTimer.singleShot(30, inspect)
        return
    window = windows[0]
    if window.steps.is_busy or window.projects.is_busy or window.interfaces.pane.is_busy:
        QTimer.singleShot(30, inspect)
        return
    window.close()
QTimer.singleShot(100, inspect)
path = root / 'trace.jsonl'
result = launch.main(['--startup-trace', str(path)])
rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
assert 'private input must not be logged' not in path.read_text(encoding='utf-8')
print(json.dumps({'result': result, 'rows': rows}))
'''
    result = _run(tmp_path, script, mode)
    assert result["result"] == (2 if mode == "error" else 0)
    events = [row["event"] for row in result["rows"]]
    assert "directory_picker_before" in events
    assert result["rows"][-1]["event"] == "launcher_exit"
    assert result["rows"][-1]["exit_code"] == result["result"]
    if mode == "normal":
        assert "workbench_enter" in events and "workbench_return" in events
    elif mode == "cancel":
        assert "directory_picker_after" in events and "workbench_enter" not in events
    else:
        assert any(row["event"] == "startup_error" and row["error_type"] == "RuntimeError"
                   for row in result["rows"])
