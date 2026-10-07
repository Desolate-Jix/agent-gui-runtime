"""运行面板只通过受控客户端回读原票据。"""
from __future__ import annotations

from copy import deepcopy
import time
import pytest

from PySide6.QtWidgets import QApplication

from app.learning_memory.workflow_run_panel import WorkflowRunPanel


_APP = None
PROGRAM = {"workflow_id": "workflow-1", "program_id": "program-1", "definition": {"steps": []}}


def receipt(request_id, value, *, status="returned"):
    return {"request_id": request_id, "status": status, "result": deepcopy(value),
            "operation_succeeded": status == "returned"}


class FakeClient:
    def __init__(self, session, library):
        self.session = session
        self.calls = []
        self.results = {}
        self.report = None
        self.pending_ids = []
        self.recoverable_controls = []
        self.closed = False
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return {"host_alive": True, "phase": "running", "source": "fixture",
                "session_directory": str(self.session), "target": {"title": "合成窗口"},
                "pending_ids": deepcopy(self.pending_ids), "workflow_run": deepcopy(self.report), "workflow_runtime_error": None,
                "recoverable_controls": deepcopy(self.recoverable_controls)}

    def control(self, request, request_id):
        self.calls.append((deepcopy(request), request_id))
        return {"request_id": request_id, "status": "pending", "automatic_retry_allowed": False}

    def result(self, request_id):
        return deepcopy(self.results.get(request_id, {"request_id": request_id, "status": "pending"}))

    def close(self):
        self.closed = True


def panel(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    clients = []
    def factory(session, library):
        item = FakeClient(session, library)
        clients.append(item)
        return item
    widget = WorkflowRunPanel(tmp_path, tmp_path, client_factory=factory)
    widget.set_context(PROGRAM, "step-1")
    return _APP, widget, clients


def wait(app, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("后台读取未完成")


def connect(app, widget, clients):
    widget.connect_session()
    wait(app, lambda: bool(clients) and not widget.is_busy)
    return clients[-1]


@pytest.mark.parametrize("state,reason", [("waiting", "verification_required"),
    ("waiting", "input_required"), ("waiting", "takeover_ready"),
    ("completed", None), ("cancelled", None), ("failed", None)])
def test_static_original_run_does_not_disable_controls_for_automatic_poll(tmp_path, monkeypatch, state, reason):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    snapshot = {"run_id": "run-original", "runner_state": state, "status": state,
        "wait_reason": reason, "wait": {"wait_id": "original-wait"}}
    client.report = snapshot
    widget._show_run(snapshot)
    widget._sync()
    monkeypatch.setattr(widget, "isVisible", lambda: True)
    original_calls = client.connect_calls
    enabled = (widget.continue_button.isEnabled(), widget.cancel_button.isEnabled())
    for _ in range(3):
        widget._poll_visible()
        assert not widget.is_busy
        assert (widget.continue_button.isEnabled(), widget.cancel_button.isEnabled()) == enabled
    assert client.connect_calls == original_calls
    assert client.calls == []
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert client.connect_calls == original_calls + 1
    widget.close_client()


@pytest.mark.parametrize("state,reason,pending,host_pending", [
    ("running", None, False, False), ("dispatching", None, False, False),
    ("cancel_requested", None, False, False), ("waiting", "execution_pending", False, False),
    ("waiting", "queue_busy", False, False), ("waiting", "result_unknown", False, False),
    ("waiting", "verification_required", True, False),
    ("waiting", "verification_required", False, True)])
def test_unsettled_original_run_still_polls_without_new_control(tmp_path, monkeypatch, state, reason, pending, host_pending):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.report = {"run_id": "run-original", "runner_state": state, "status": state, "wait_reason": reason}
    widget._show_run(client.report)
    if pending:
        widget._pending = {"request_id": "control-original", "action": "run", "mode": "until_wait"}
        client.results["control-original"] = {"request_id": "control-original", "status": "pending"}
    if host_pending:
        widget._host_pending_ids = ["host-original"]
        client.pending_ids = ["host-original"]
    monkeypatch.setattr(widget, "isVisible", lambda: True)
    calls = client.connect_calls
    widget._poll_visible()
    assert widget.is_busy
    wait(app, lambda: not widget.is_busy)
    assert client.calls == []
    if pending:
        assert widget._pending["request_id"] == "control-original"
    else:
        assert client.connect_calls == calls + 1
    widget.close_client()


@pytest.mark.parametrize("terminal", ["failed", "waiting"])
def test_continue_ready_receipt_reads_original_next_tick_without_control(tmp_path, monkeypatch, terminal):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget._prepared_run = True
    widget._pending = {"request_id": "continue-original", "action": "continue", "mode": "until_wait"}
    ready = {"run_id": "original", "program_id": "program-1", "workflow_id": "workflow-1",
             "status": "ready", "runner_state": "ready", "history": [{"step_id": "step-1"}]}
    widget._accept_receipt("control", "continue-original", ("continue", "until_wait"),
                           receipt("continue-original", ready))
    assert widget._pending is None and not widget._prepared_run
    client.report = {**ready, "status": terminal, "runner_state": terminal,
                     "wait_reason": "verification_required" if terminal == "waiting" else None}
    monkeypatch.setattr(widget, "isVisible", lambda: True)
    calls = client.connect_calls
    widget._poll_visible()
    wait(app, lambda: not widget.is_busy)
    assert client.connect_calls == calls + 1
    assert widget._run["run_id"] == "original" and widget._run["runner_state"] == terminal
    widget._poll_visible()
    assert not widget.is_busy and client.connect_calls == calls + 1
    assert client.calls == []
    widget.close_client()


def test_recovered_prepared_ready_stays_idle_without_poll_or_autorun(tmp_path, monkeypatch):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget._accept_receipt("control", "start-original", ("start", None),
                           receipt("start-original", {"run_id": "prepared", "status": "ready"}))
    assert widget._prepared_run and widget._pending is None
    monkeypatch.setattr(widget, "isVisible", lambda: True)
    calls = client.connect_calls
    widget._poll_visible()
    assert not widget.is_busy and client.connect_calls == calls and client.calls == []
    widget.close_client()


def test_missing_output_names_pinned_source_step_and_does_not_suggest_guessing(tmp_path):
    app, widget, clients = panel(tmp_path)
    definition = {"steps": [{"step_id": "read-current", "title": "读取当前状态"},
                             {"step_id": "fill-current", "title": "填写当前状态"}]}
    widget.set_context({**PROGRAM, "definition": definition}, "fill-current")
    snapshot = {"run_id": "run-original", "program_id": "program-1", "workflow_id": "workflow-1",
        "current_step_id": "fill-current", "runner_state": "waiting", "status": "blocked",
        "wait_reason": "input_required", "reason": "workflow_trial_upstream_output_missing:read-current.status",
        "outputs": {}}
    widget._show_run(snapshot)
    assert widget.step_label.text() == "当前步骤：填写当前状态"
    assert "读取当前状态" in widget.wait_label.text()
    assert "status" in widget.wait_label.text() and "本次" in widget.wait_label.text()
    assert "来源步骤" in widget.wait_label.text()
    assert "Agent" not in widget.status_label.text(), "缺数据应指向来源修复，不能用模型猜值"
    widget.set_context({**PROGRAM, "program_id": "new-version", "definition": {
        "steps": [{"step_id": "read-current", "title": "新版本的无关标题"}]}}, "read-current", dirty=True)
    widget._show_run(snapshot)
    assert "读取当前状态" in widget.wait_label.text()
    assert "新版本的无关标题" not in widget.wait_label.text()
    assert not clients
    widget.close_client()


def test_run_uses_readable_generated_action_title(tmp_path):
    app, widget, _ = panel(tmp_path)
    widget.set_context({**PROGRAM, "definition": {"steps": [
        {"step_id": "step-1", "title": "input_sequence"}]}}, "step-1")
    widget._show_run({"run_id": "current", "workflow_id": "workflow-1", "program_id": "program-1",
                      "current_step_id": "step-1", "status": "pending"})
    assert widget.step_label.text() == "当前步骤：填写文本"
    widget.close_client()


def test_start_uses_original_pending_id_then_runs_once(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {"query": "A"}
    widget.start_single()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    start, start_id = client.calls[0]
    assert start == {"action": "start", "workflow_id": "workflow-1", "program_id": "program-1",
                     "start_step_id": "step-1", "inputs": {"query": "A"}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert len(client.calls) == 1
    client.results[start_id] = receipt(start_id, {"run_id": "run-1", "status": "ready"})
    widget.refresh()
    wait(app, lambda: len(client.calls) == 2 and not widget.is_busy)
    run, run_id = client.calls[1]
    assert run == {"action": "run", "run_id": "run-1", "mode": "single"}
    assert start_id != run_id
    widget.close_client()


def test_wait_continue_uses_exact_wait_id_and_no_automatic_resume(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.report = {"run_id": "run-old", "runner_state": "waiting", "status": "blocked",
                     "wait_reason": "verification_required", "wait": {"wait_id": "wait-7"},
                     "outputs": {"a": "value"}, "metrics": {"steps_completed": 2}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert not client.calls
    assert widget.continue_button.isEnabled()
    widget.continue_run()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    assert client.calls[0][0] == {"action": "continue", "run_id": "run-old", "wait_id": "wait-7"}
    widget.close_client()


def test_continuous_run_stops_at_wait_until_explicit_continue(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    widget.start_continuous()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    start_id = client.calls[0][1]
    client.results[start_id] = receipt(start_id, {"run_id": "run-2", "status": "ready"})
    widget.refresh()
    wait(app, lambda: len(client.calls) == 2 and not widget.is_busy)
    assert client.calls[1][0] == {"action": "run", "run_id": "run-2", "mode": "until_wait"}
    run_id = client.calls[1][1]
    client.results[run_id] = receipt(run_id, {"run_id": "run-2", "status": "blocked",
        "runner_state": "waiting", "wait_reason": "verification_required",
        "wait": {"wait_id": "wait-2"}, "outputs": {"answer": "A"},
        "metrics": {"steps_completed": 1}})
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert len(client.calls) == 2
    assert "answer" in widget.outputs.toPlainText()
    assert "{\"" not in widget.outputs.toPlainText()
    assert "需 Agent" in widget.wait_label.text()
    assert "run-2" not in widget.status_label.text()
    assert "已完成步骤 1" in widget.metrics_label.text()
    widget.continue_button.click()
    wait(app, lambda: len(client.calls) == 3 and not widget.is_busy)
    assert client.calls[2][0] == {"action": "continue", "run_id": "run-2", "wait_id": "wait-2"}
    widget.close_client()


def test_unknown_result_never_resubmits_and_reconnect_never_runs(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    widget.start_continuous()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    start_id = client.calls[0][1]
    client.results[start_id] = {"request_id": start_id, "status": "result_unknown"}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert len(client.calls) == 1
    assert "结果未知" in widget.status.text()
    widget.close_client()
    widget.connect_session()
    wait(app, lambda: len(clients) == 2 and not widget.is_busy)
    assert not clients[1].calls
    widget.close_client()


def test_reconnected_pending_command_blocks_new_start(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.pending_ids = ["workflow-ui-old"]
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert not widget.single_button.isEnabled()
    assert not widget.run_button.isEnabled()
    assert "不会猜测或重发" in widget.status_label.text()
    widget.close_client()


def test_same_session_reconnect_preserves_original_pending_id(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    widget.start_single()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    original_id = client.calls[0][1]
    widget.connect_session()
    wait(app, lambda: not widget.is_busy)
    assert len(clients) == 1
    assert widget._pending["request_id"] == original_id
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert len(client.calls) == 1
    widget.close_client()


def test_status_failure_disables_run_and_not_submitted_clears_pending(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    widget.start_single()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    request_id = client.calls[0][1]
    client.results[request_id] = {"request_id": request_id, "status": "not_submitted",
        "reason": "command_pending", "pending_ids": ["earlier-id"]}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget._pending is None
    assert not widget.single_button.isEnabled()
    assert "未入队" in widget.status_label.text()
    assert len(client.calls) == 1
    def failed_connect():
        raise ValueError("host vanished")
    client.connect = failed_connect
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert not widget._host_alive
    assert not widget.single_button.isEnabled()
    widget.close_client()


def test_dirty_context_preserves_old_run_and_close_waits_for_io(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.report = {"run_id": "run-old", "runner_state": "waiting", "status": "blocked",
                     "wait_reason": "input_required", "wait": {"wait_id": "wait-1"}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    widget.set_context({"workflow_id": "workflow-2", "program_id": None}, "other", dirty=True)
    assert not widget.single_button.isEnabled()
    assert widget.cancel_button.isEnabled()
    widget.cancel_run()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    assert client.calls[0][0] == {"action": "cancel", "run_id": "run-old"}
    cancel_id = client.calls[0][1]
    client.results[cancel_id] = receipt(cancel_id, {"run_id": "run-old", "runner_state": "cancelled", "status": "cancelled"})
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    from threading import Event
    entered, release = Event(), Event()
    original = client.connect
    def slow_connect():
        entered.set()
        release.wait(2)
        return original()
    client.connect = slow_connect
    widget.refresh()
    assert entered.wait(1)
    widget.close_client()
    assert not client.closed
    release.set()
    wait(app, lambda: client.closed and not widget.is_busy)
    assert widget._client is None


def test_cancel_loading_during_dispatch_keeps_original_id(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    from threading import Event
    entered, release = Event(), Event()
    original = client.control
    def slow_control(request, request_id):
        entered.set()
        release.wait(2)
        return original(request, request_id)
    client.control = slow_control
    widget.start_single()
    assert entered.wait(1)
    original_id = widget._pending["request_id"]
    widget.cancel_loading()
    release.set()
    wait(app, lambda: not widget.is_busy)
    assert widget._pending["request_id"] == original_id
    client.results[original_id] = receipt(original_id, {"run_id": "run-3", "status": "ready"})
    widget.refresh()
    wait(app, lambda: len(client.calls) == 2 and not widget.is_busy)
    assert client.calls[0][1] == original_id
    assert client.calls[1][0]["action"] == "run"
    widget.close_client()


@pytest.mark.parametrize("source,expected", [
    ("agent_current", {"image_transport": "supported", "current_vision": "supported"}),
    ("agent_delegate", {"image_transport": "supported", "delegation": "supported",
                        "model_selection": "supported", "delegate_vision": "supported"}),
    ("local", None), ("external_api", None)])
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("declared", [False, True])
def test_explicit_session_vision_reaches_both_run_entries(tmp_path, source, expected, prepared, declared):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget._accept_status({**client.connect(), "recognition_source": source})
    widget._sync()
    assert not widget.vision_checkbox.isChecked()
    widget.vision_checkbox.setChecked(declared)
    widget.inputs_provider = lambda: {}
    if prepared:
        widget._run = {"run_id": "prepared", "status": "ready", "workflow_id": "workflow-1",
                       "program_id": "program-1", "start_step_id": "step-1"}
        widget._prepared_run = True
    widget.start_single()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    if not prepared:
        start_id = client.calls[0][1]
        assert "vision_capabilities" not in client.calls[0][0]
        assert not widget.vision_checkbox.isEnabled()
        widget.vision_checkbox.setChecked(not declared)
        client.results[start_id] = receipt(start_id, {"run_id": "created", "status": "ready"})
        widget.refresh()
        wait(app, lambda: len(client.calls) == 2 and not widget.is_busy)
    request = client.calls[-1][0]
    assert request["action"] == "run"
    if expected is None or not declared:
        assert "vision_capabilities" not in request
    else:
        assert request["vision_capabilities"] == expected
    widget.close_client()


def test_declaration_default_reset_and_active_run_lock(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    status = {**client.connect(), "recognition_source": "agent_current"}
    widget._accept_status(status)
    widget._sync()
    assert widget.vision_checkbox.isEnabled()
    assert widget._run_request("run", "single").get("vision_capabilities") is None
    widget.vision_checkbox.setChecked(True)
    widget._accept_status(status)
    assert widget.vision_checkbox.isChecked()
    widget._show_run({"run_id": "original", "status": "blocked", "runner_state": "waiting",
                      "wait_reason": "verification_required", "wait": {"wait_id": "wait"}})
    widget._sync()
    assert not widget.vision_checkbox.isEnabled()
    widget.continue_run()
    wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
    assert client.calls[0][0] == {"action": "continue", "run_id": "original", "wait_id": "wait"}
    widget._pending = None
    widget._accept_status({**status, "recognition_source": "agent_delegate"})
    assert not widget.vision_checkbox.isChecked()
    widget.vision_checkbox.setChecked(True)
    other = tmp_path / "other"
    other.mkdir()
    widget.session_path.setText(str(other))
    assert not widget.vision_checkbox.isChecked()
    widget.connect_session()
    wait(app, lambda: len(clients) == 2 and not widget.is_busy)
    assert not widget.vision_checkbox.isChecked()
    widget.close_client()
    assert not widget.vision_checkbox.isChecked()


def test_recovered_start_does_not_redeclare_or_auto_run(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget._accept_status({**client.connect(), "recognition_source": "agent_current"})
    widget.vision_checkbox.setChecked(True)
    widget._recover_controls([{"request_id": "old-start", "action": "start",
        "request": {"action": "start"}, "receipt": receipt("old-start", {
            "run_id": "original", "status": "ready"})}])
    assert widget._prepared_run and not client.calls
    widget.close_client()


def test_explicit_execution_installation_reaches_client_without_dispatch(tmp_path):
    app, widget, clients = panel(tmp_path)
    installation = tmp_path / "execution-installation"
    installation.mkdir()
    received = []
    def factory(session, library, *, execution_root=None):
        received.append((session, library, execution_root))
        client = FakeClient(session, library)
        clients.append(client)
        return client
    widget._client_factory = factory
    widget.execution_path.setText(str(installation))
    client = connect(app, widget, clients)
    assert received == [(tmp_path.resolve(), tmp_path, installation.resolve())]
    assert not client.calls
    assert widget._connection_matches()
    widget.close_client()


def test_frozen_workbench_requires_execution_root_and_remains_offline(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    app, widget, clients = panel(tmp_path)
    widget.connect_session()
    app.processEvents()
    assert not clients and not widget.is_busy
    assert "执行模式安装目录" in widget.status_label.text()
    assert not widget.single_button.isEnabled()
    assert widget._context == PROGRAM
    widget.close_client()


def test_changing_execution_root_invalidates_old_connection(tmp_path):
    app, widget, clients = panel(tmp_path)
    first = connect(app, widget, clients)
    installation = tmp_path / "separate-executor"
    installation.mkdir()
    widget.execution_path.setText(str(installation))
    assert not widget._connection_matches()
    assert not widget.single_button.isEnabled()
    assert not first.calls
    def factory(session, library, *, execution_root=None):
        assert execution_root == installation.resolve()
        client = FakeClient(session, library)
        clients.append(client)
        return client
    widget._client_factory = factory
    widget.connect_session()
    wait(app, lambda: len(clients) == 2 and not widget.is_busy)
    assert first.closed and not clients[-1].calls
    assert widget._connection_matches()
    widget.close_client()


def test_pending_request_cannot_be_lost_by_switching_connection(tmp_path):
    app, widget, clients = panel(tmp_path)
    original = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    widget.start_single()
    wait(app, lambda: len(original.calls) == 1 and not widget.is_busy)
    request_id = widget._pending["request_id"]
    assert not widget.execution_path.isEnabled()
    assert not widget.execution_browse_button.isEnabled()
    assert not widget.session_path.isEnabled()
    other = tmp_path / "other-session"
    other.mkdir()
    widget.session_path.setText(str(other))
    widget.connect_session()
    app.processEvents()
    assert len(clients) == 1 and not original.closed
    assert widget._pending["request_id"] == request_id
    assert len(original.calls) == 1
    widget.session_path.setText(str(tmp_path))
    widget.connect_session()
    wait(app, lambda: not widget.is_busy)
    assert widget._pending["request_id"] == request_id
    widget.close_client()


def test_client_creation_error_keeps_previous_connection_and_context(tmp_path):
    app, widget, clients = panel(tmp_path)
    original = connect(app, widget, clients)
    other = tmp_path / "other-session"
    other.mkdir()
    widget.session_path.setText(str(other))
    def factory(session, library):
        raise ValueError("execution_installation_invalid")
    widget._client_factory = factory
    widget.connect_session()
    assert widget._client is original and not original.closed
    assert widget._context == PROGRAM
    assert "execution_installation_invalid" in widget.status_label.toolTip()
    assert not widget.single_button.isEnabled()
    widget.close_client()


def test_raw_error_detail_is_not_translated_when_matching_application_text(tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n
    app, widget, _ = panel(tmp_path)
    manager = initialize_i18n(app, preferences_path=tmp_path / "language.json", system_locale="zh-CN")
    previous = manager.language
    raw = "\u4efb\u52a1\u6b65\u9aa4\noriginal traceback"
    try:
        manager.set_language("en-US", persist=False)
        widget._show_error("\u8bfb\u53d6\u5931\u8d25\uff1a", raw)
        assert widget.status_label.text().endswith(raw.splitlines()[0])
        assert widget.status_label.toolTip() == raw
        manager.set_language("zh-CN", persist=False)
        manager.set_language("en-US", persist=False)
        assert widget.status_label.text().endswith(raw.splitlines()[0])
        assert widget.status_label.toolTip() == raw
    finally:
        manager.set_language(previous, persist=False)
        widget.close_client()
