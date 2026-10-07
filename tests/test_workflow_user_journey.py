"""直接运行工作台 main，验证完整窗口入口和规则编辑保存重开。"""
import os
import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from tests.test_workflow_steps_ui import generated, qt_app, _wait


def _run_main(monkeypatch, qt_app, root, inspect_window, *, session=None):
    from scripts import run_learning_memory_workbench
    calls = []
    def event_loop():
        windows = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow)
                   and w.windowTitle().startswith("Agent Review")]
        assert len(windows) == 1
        window = windows[0]
        _wait(qt_app, lambda: not window.steps.is_busy and not window.projects.is_busy and not window.interfaces.pane.is_busy)
        assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["任务步骤", "流程项目", "独立界面库"]
        try:
            inspect_window(window)
            calls.append(True)
        finally:
            if window.steps.dirty:
                window.steps.discard()
            window.interfaces.pane.cancel_loading()
            window.projects.cancel_loading()
            _wait(qt_app, lambda: not window.steps.is_busy and not window.projects.is_busy and not window.interfaces.pane.is_busy)
            window.close()
            window.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return 0
    monkeypatch.setattr(qt_app, "exec", event_loop)
    arguments = ["run_learning_memory_workbench.py", "--data-dir", str(root)]
    if session is not None:
        arguments.extend(["--session-dir", str(session)])
    monkeypatch.setattr(sys, "argv", arguments)
    assert run_learning_memory_workbench.main() == 0
    assert calls == [True]


def test_actual_entrypoint_empty_state_has_all_existing_sections(monkeypatch, qt_app, tmp_path):
    def inspect(window):
        assert window.steps.steps.count() == 0
        assert window.steps.snapshot is None and not window.steps.dirty
        assert not window.steps.rules_editor.isEnabled()
        assert not list(tmp_path.glob("session-*"))
    _run_main(monkeypatch, qt_app, tmp_path, inspect)


def test_actual_entrypoint_replaces_instance_event_loop_left_by_other_test(monkeypatch, qt_app, tmp_path):
    monkeypatch.setattr(qt_app, "exec", lambda: 37)
    try:
        _run_main(monkeypatch, qt_app, tmp_path, lambda window: None)
    finally:
        # 失败路径也清理本测试创建的离屏窗口，避免影响同进程后续检查。
        for window in QApplication.topLevelWidgets():
            if isinstance(window, QMainWindow) and hasattr(window, "steps"):
                _wait(qt_app, lambda: not window.steps.is_busy and not window.projects.is_busy and not window.interfaces.pane.is_busy)
                window.close()
                window.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_actual_entrypoint_rule_edit_save_and_reopen(monkeypatch, qt_app, generated):
    session, root, _workflow_id = generated
    saved = []
    def edit(window):
        pane = window.steps
        assert pane.snapshot is not None
        rules = pane.rules_editor
        rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("field_equals"))
        rules.target_type.setText("Edit")
        rules.target_name.setText("搜索字段")
        rules.expected_source.setCurrentIndex(rules.expected_source.findData("input"))
        rules.expected_name.setCurrentText("place")
        assert pane.dirty
        pane.save_button.click()
        assert not pane.dirty and pane.snapshot["program_id"] is not None
        saved.append(pane.snapshot["program_id"])
        assert pane.snapshot["definition"]["steps"][0]["verification"]["expected"] == {"source": "input", "name": "place"}
        if os.environ.get("WORKFLOW_FULL_ENTRY_CAPTURE"):
            pane.editor_tabs.setCurrentIndex(next(i for i in range(pane.editor_tabs.count())
                if pane.editor_tabs.tabText(i) == "结果与读取"))
            qt_app.processEvents()
            assert window.grab().save(os.environ["WORKFLOW_FULL_ENTRY_CAPTURE"])
    _run_main(monkeypatch, qt_app, root.parent, edit)
    def reopened(window):
        pane = window.steps
        assert pane.snapshot["program_id"] == saved[0]
        assert pane.rules_editor.target_name.text() == "搜索字段"
        assert pane.rules_editor.expected_name.currentText() == "place"
        assert not pane.dirty
        assert not list((session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, reopened)


def test_actual_entrypoint_title_edit_keeps_review_after_save_and_reopen(monkeypatch, qt_app, generated):
    session, root, workflow_id = generated
    versions = []
    def edit(window):
        pane = window.steps
        pane.save_button.click()
        pane.review.setCurrentIndex(pane.review.findData("reviewed"))
        pane.save_button.click()
        assert pane.snapshot["definition"]["steps"][0]["review_status"] == "reviewed"
        versions.append(pane.snapshot["program_id"])
        pane.step_title.setText("查询最新地点")
        pane.save_button.click()
        assert not pane.dirty
        assert pane.review.currentData() == "reviewed"
        assert "已人工审核" in pane.step_summary.text()
        versions.append(pane.snapshot["program_id"])
        assert versions[0] != versions[1]
    _run_main(monkeypatch, qt_app, root.parent, edit)
    def reopened(window):
        pane = window.steps
        assert pane.snapshot["program_id"] == versions[1]
        assert pane.step_title.text() == "查询最新地点"
        assert pane.review.currentData() == "reviewed"
        old = pane.facade.load_workflow_program(workflow_id, versions[0])
        assert old["definition"]["steps"][0]["title"] != "查询最新地点"
        assert old["definition"]["steps"][0]["review_status"] == "reviewed"
        assert not list((session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, reopened)
