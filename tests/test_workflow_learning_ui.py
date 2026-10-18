"""普通主窗口读取当前学习草稿，修改保存和重开均不派发输入。"""
import os

from test_learning_synthesis import _reply, _stop, repeated_state, observation_scene
from test_workflow_steps_ui import qt_app, _wait
from test_workflow_user_journey import _run_main


def test_main_opens_generated_draft_saves_recipes_and_reopens(monkeypatch, qt_app, repeated_state):
    store, root, _, _, _ = repeated_state
    saved = []
    def inspect(window):
        pane = window.steps
        assert "等待" in pane.learning_status.text()
        assert not pane.open_learning_button.isEnabled()
        request = _stop(store)["synthesis_request"]
        store.control("learning_workflow", _reply(request), "current-agent-reply")
        pane.learning_refresh_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert "可审核" in pane.learning_status.text()
        assert pane.open_learning_button.isEnabled()
        pane.open_learning_button.click()
        assert pane.dirty
        assert [step["title"] for step in pane.definition["steps"]] == ["查询", "刷新"]
        assert "2" in pane.learning_details.toPlainText()
        if os.environ.get("WORKFLOW_SYNTHESIS_CAPTURE"):
            qt_app.processEvents()
            assert window.grab().save(os.environ["WORKFLOW_SYNTHESIS_CAPTURE"])
        pane.program_title.setText("人工修订标题")
        pane.save_button.click()
        assert not pane.dirty and pane.snapshot["program_id"] is not None
        assert all("target_memory" in step["action"] for step in pane.snapshot["definition"]["steps"])
        saved.append(pane.snapshot["program_id"])
        assert not pane.open_learning_button.isEnabled()
        assert not list((store.session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)
    def reopen(window):
        pane = window.steps
        assert pane.snapshot["program_id"] == saved[0]
        assert pane.program_title.text() == "人工修订标题"
        assert "已保存" in pane.learning_status.text()
        assert not pane.dirty
        assert len(list((root / "desktop-review/target-recipes").glob("*.json"))) == 2
        assert not list((store.session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, reopen, session=store.session)


def test_learning_refresh_never_overwrites_unsaved_edit(monkeypatch, qt_app, repeated_state):
    store, root, _, _, _ = repeated_state
    store.control("learning_workflow", _reply(_stop(store)["synthesis_request"]), "reply")
    def inspect(window):
        pane = window.steps
        pane.learning_refresh_button.click()
        pane.program_title.setText("保留当前修改")
        _wait(qt_app, lambda: not pane.is_busy)
        assert pane.dirty and pane.program_title.text() == "保留当前修改"
        assert "保存或放弃" in pane.learning_status.text()
        assert not pane.open_learning_button.isEnabled()
        pane.open_learning_draft()
        assert pane.program_title.text() == "保留当前修改"
        assert not list((store.session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)


def test_main_wrong_library_session_is_visible_and_does_not_create_host(monkeypatch, qt_app, repeated_state, tmp_path):
    store, _, _, _, _ = repeated_state
    other = tmp_path / "other-library"
    def inspect(window):
        pane = window.steps
        assert "失败" in pane.learning_status.text()
        assert "同一数据目录" in pane.learning_status.text()
        assert "workflow_learning_library_mismatch" in pane.learning_status.toolTip()
        assert not pane.open_learning_button.isEnabled()
        assert not list(other.glob("session-*"))
        assert not list((store.session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, other, inspect, session=store.session)


def test_correction_reopens_with_event_reason_and_clears_after_reply(monkeypatch, qt_app, repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    bad = _reply(request, annotations={"click-1": {"verification": {
        "kind": "target_present", "target": {"name": "Refresh"}}}})
    store.control("learning_workflow", bad, "bad-reply")
    def inspect(window):
        pane = window.steps
        assert "需要补充" in pane.learning_status.text()
        details = pane.learning_details.toPlainText()
        assert "Refresh" in details and "成功条件" in details
        assert "原 Agent 对话" in details and "JSON" not in details
        assert not pane.open_learning_button.isEnabled()
        assert not list((store.session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)
    store.control("learning_workflow", _reply(request), "corrected-reply")
    def corrected(window):
        assert "可审核" in window.steps.learning_status.text()
        assert "需要补充" not in window.steps.learning_details.toPlainText()
        assert window.steps.open_learning_button.isEnabled()
    _run_main(monkeypatch, qt_app, root.parent, corrected, session=store.session)


def test_synthesis_correction_reopens_in_workbench(monkeypatch, qt_app, repeated_state):
    from test_learning_synthesis_conversation import _fail_twice, _resume
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    def waiting(window):
        pane = window.steps
        assert "等待你补充" in pane.learning_status.text()
        assert "自动纠错已用完" in pane.learning_details.toPlainText()
        assert "原 Agent 对话" in pane.learning_details.toPlainText()
        assert not pane.open_learning_button.isEnabled()
        pane.learning_refresh_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert "等待你补充" in pane.learning_status.text()
        assert not list((store.session / "commands").glob("*.json"))
    _run_main(monkeypatch, qt_app, root.parent, waiting, session=store.session)
    _run_main(monkeypatch, qt_app, root.parent, waiting, session=store.session)
    store.control("learning_workflow", _resume(request), "user-resume")
    store.control("learning_workflow", _reply(request, resume_request_id="user-resume"), "final-correction")
    saved = []
    def review(window):
        pane = window.steps
        assert "可审核" in pane.learning_status.text()
        pane.open_learning_button.click()
        pane.program_title.setText("人工确认后的流程")
        pane.save_button.click()
        assert not pane.dirty
        saved.append(pane.snapshot["program_id"])
    _run_main(monkeypatch, qt_app, root.parent, review, session=store.session)
    def reopened(window):
        assert window.steps.snapshot["program_id"] == saved[0]
        assert window.steps.program_title.text() == "人工确认后的流程"
    _run_main(monkeypatch, qt_app, root.parent, reopened, session=store.session)
