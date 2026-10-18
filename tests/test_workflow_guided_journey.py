"""普通工作台从新学习草稿到实际参数对话框与原队列的离屏链路。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.workflow_control import workflow_control
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_input_dialog import WorkflowInputDialog
from tests.test_learning_synthesis import _input_workflow, _reply
from tests.test_workflow_run_journey import _next_control
from tests.test_workflow_steps_ui import qt_app, _wait
from tests.test_workflow_user_journey import _run_main


class _FreshSessionRoot:
    """复用合成学习夹具，同时给真实运行客户端提供合法的会话目录名。"""

    def __init__(self, session):
        self.session = session

    def __truediv__(self, name):
        assert name == "input-session"
        return self.session


def _drive_dialog(kind, click, inspect):
    errors, handled = [], []
    deadline = time.monotonic() + 3
    timer = QTimer()
    timer.setInterval(5)

    def inspect_visible():
        dialogs = [widget for widget in QApplication.topLevelWidgets()
                   if isinstance(widget, kind) and widget.isVisible()]
        if dialogs:
            timer.stop()
            dialog = dialogs[-1]
            try:
                inspect(dialog)
                handled.append(True)
            except BaseException as error:
                errors.append(error)
                dialog.reject()
        elif time.monotonic() >= deadline:
            timer.stop()
            errors.append(AssertionError(f"未显示真实 {kind.__name__} 对话框"))
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QDialog) and widget.isVisible():
                    widget.reject()

    timer.timeout.connect(inspect_visible)
    timer.start()
    try:
        click()
    finally:
        timer.stop()
    if errors:
        raise errors[0]
    assert handled == [True]


def _source_and_session(root):
    session = root / ("session-" + uuid4().hex)
    store, _started, stopped = _input_workflow(_FreshSessionRoot(session))
    request = stopped["synthesis"]["synthesis_request"]
    completed = store.control("learning_workflow", _reply(request,
        annotations={"query": {"verification": {"kind": "agent_judgment"}}}), "guided-reply")
    assert completed["status"] == "draft_ready"
    assert completed["draft"]["definition"]["steps"][0]["action"]["text"]["source"] == "constant"
    (session / "commands").mkdir()
    # 仅用当前测试进程身份核验隔离客户端；这里没有物理宿主。
    identity = {"pid": os.getpid(), "created": psutil.Process().create_time()}
    write_json_snapshot(root / "latest-session.json", {
        "name": session.name, "host_identity": identity,
        "recognition_source": "agent_current", "delegate_profile": None, "api_profile": None})
    write_json_snapshot(session / "report.json", {
        "phase": "ready", "runner_pid": identity["pid"], "target": None,
        "learning_recording": {"status": "disabled", "recording_enabled": False}})
    return session


def _capture(widget, filename):
    target = os.environ.get("WORKFLOW_GUIDED_CAPTURE_DIR")
    if not target:
        return
    directory = Path(target)
    directory.mkdir(parents=True, exist_ok=True)
    assert widget.grab().save(str(directory / filename))


def test_guided_main_learning_parameter_save_reopen_and_original_queue(monkeypatch, qt_app, tmp_path):
    session = _source_and_session(tmp_path)
    saved = {}

    def edit(window):
        pane = window.steps
        _wait(qt_app, lambda: pane.open_learning_button.isEnabled() and not pane.is_busy)
        pane.open_learning_button.click()
        assert pane.dirty and pane.action_kind.currentData() == "input_sequence"
        assert pane.text_source.currentData() == "constant"

        def name_parameter(dialog):
            assert dialog.textValue() == "value_1"
            dialog.accept()

        _drive_dialog(QInputDialog, pane.parameterize_button.click, name_parameter)
        assert pane.text_binding.currentData() == {"source": "input", "name": "value_1"}
        pane.field_goal.setText("本次编号字段")
        rules = pane.rules_editor
        rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("field_equals"))
        rules.target_type.setText("Edit")
        rules.target_name.setText("本次编号字段")
        rules.expected_source.setCurrentIndex(rules.expected_source.findData("input"))
        rules.expected_name.setCurrentText("value_1")
        pane.editor_tabs.setCurrentIndex(next(i for i in range(pane.editor_tabs.count())
            if pane.editor_tabs.tabText(i) == "动作与分支"))
        qt_app.processEvents()
        _capture(window, "guided-values-main.png")
        pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        assert pane.snapshot["program_id"] is not None
        assert pane.snapshot["definition"]["steps"][0]["action"]["text"] == {"source": "input", "name": "value_1"}
        saved["program_id"] = pane.snapshot["program_id"]
        assert not list((session / "commands").glob("*.json"))
        _wait(qt_app, lambda: not pane.is_busy)

    _run_main(monkeypatch, qt_app, tmp_path, edit, session=session)
    runtime = WorkflowRuntime(session, SimpleNamespace(_memory_library_root=tmp_path / "memory-library"))

    def run(window):
        pane = window.steps
        assert pane.snapshot["program_id"] == saved["program_id"]
        assert pane.text_binding.currentData() == {"source": "input", "name": "value_1"}
        assert pane.field_goal.text() == "本次编号字段"
        assert pane.rules_editor.target_name.text() == "本次编号字段"
        panel = pane.run_panel
        pane.open_run_button.click()
        assert pane.editor_tabs.currentWidget() is panel
        assert pane.editor_tabs.tabText(pane.editor_tabs.currentIndex()) == "运行"
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy and panel.single_button.isEnabled())
        assert pane.session_dir == session

        def cancel_inputs(dialog):
            assert set(dialog.editors) == {"value_1"}
            dialog.reject()

        _drive_dialog(WorkflowInputDialog, panel.single_button.click, cancel_inputs)
        assert not list((session / "commands").glob("*.json"))

        def invalid_inputs(dialog):
            dialog.editors["value_1"].setText(" ")
            dialog.accept()
            assert dialog.error_label.text()
            dialog.reject()

        _drive_dialog(WorkflowInputDialog, panel.single_button.click, invalid_inputs)
        assert not list((session / "commands").glob("*.json"))

        def current_inputs(dialog):
            dialog.editors["value_1"].setText("本轮新编号-42")
            _capture(dialog, "guided-inputs-dialog.png")
            dialog.accept()
            assert dialog.values() == {"value_1": "本轮新编号-42"}

        _drive_dialog(WorkflowInputDialog, panel.single_button.click, current_inputs)
        start_path, start_command = _next_control(qt_app, session, "start")
        assert start_command["request"]["inputs"] == {"value_1": "本轮新编号-42"}
        with MemoryWorkspace(tmp_path / "memory-library") as library:
            started = workflow_control(library, session, start_command["request"], start_path.stem)
        assert started["program_id"] == saved["program_id"]
        assert started["inputs"] == {"value_1": "本轮新编号-42"}
        # 合成宿主回执只推动队列控制状态；不声称有物理动作结果。
        write_json_snapshot(session / "responses" / start_path.name,
                            {"status": "returned", "command": start_command, "result": started})
        run_path, run_command = _next_control(qt_app, session, "run")
        snapshot = runtime.control(run_command["request"], run_path.stem)
        write_json_snapshot(session / "responses" / run_path.name,
                            {"status": "returned", "command": run_command, "result": snapshot})
        _wait(qt_app, lambda: any(json.loads(path.read_text(encoding="utf-8")).get("kind") == "input_sequence"
                            for path in (session / "commands").glob("*.json")))
        queued = [json.loads(path.read_text(encoding="utf-8")) for path in (session / "commands").glob("*.json")
                  if json.loads(path.read_text(encoding="utf-8")).get("kind") == "input_sequence"]
        assert len(queued) == 1
        assert queued[0]["request"]["text"] == "本轮新编号-42"
        assert queued[0]["request"]["field_goal"] == "本次编号字段"
        assert snapshot["run_id"] == started["run_id"]
        assert snapshot["runner_state"] in {"waiting", "single_complete", "completed"}
        _wait(qt_app, lambda: not pane.is_busy and panel._run is not None
              and panel._run.get("runner_state") == snapshot["runner_state"])
        assert panel.step_label.text().startswith("当前步骤：")
        assert panel.step_label.text() != "当前步骤："
        _capture(window, "guided-run-main.png")
        _wait(qt_app, lambda: not pane.is_busy)

    _run_main(monkeypatch, qt_app, tmp_path, run, session=session)
