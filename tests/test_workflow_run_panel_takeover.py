"""普通 Qt 恢复选择只经原客户端，提交接管与继续明确分开。"""
from copy import deepcopy

import pytest

from test_workflow_run_panel import panel, connect, wait, FakeClient, receipt

SOURCE = {
    "admission_request_id": "admission-original", "source_run_id": "trial-" + "a" * 64,
    "source_session": "original-session", "workflow_id": "workflow-1", "program_id": "program-1",
    "program_sha256": "b" * 64, "step_id": "step-original", "step_title": "填写当前文本",
    "terminal_status": "cancelled", "action_executed": False,
    "resume_unexecuted_available": True, "resume_unexecuted_reason": None,
    "current_effect_verified": False,
}


def takeover_scene(tmp_path, monkeypatch):
    original = FakeClient.connect
    monkeypatch.setattr(FakeClient, "connect", lambda self: {
        **original(self), "takeover_sources": [deepcopy(SOURCE)]})
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    return app, widget, client


def preview_value(request_id, resolution="resume_unexecuted"):
    return {"status": "preview_ready", "preview_request_id": request_id,
        "preview_sha256": "c" * 64, "source_run_id": SOURCE["source_run_id"],
        "admission_request_id": SOURCE["admission_request_id"],
        "new_run_id": "trial-" + "d" * 64, "next_step_id": SOURCE["step_id"],
        "inputs": {"query": "当前值"}, "outputs": {}, "effect": {"verification": {
            "verdict": "failure", "reason": "observed_value_conflict"}},
        "resolution": resolution, "automatic_retry_allowed": False, "input_dispatched": False}


def prepare_preview(app, widget, client):
    widget.takeover_source.setCurrentIndex(1)
    widget.takeover_resolution.setCurrentIndex(widget.takeover_resolution.findData("resume_unexecuted"))
    widget.takeover_preview_button.click()
    wait(app, lambda: not widget.is_busy)
    request, rid = client.calls[-1]
    assert request == {"action": "takeover_preview",
        "admission_request_id": SOURCE["admission_request_id"],
        "source_run_id": SOURCE["source_run_id"], "resolution": "resume_unexecuted"}
    client.results[rid] = receipt(rid, preview_value(rid))
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    return rid


def test_ordinary_selection_preview_commit_then_explicit_continue(tmp_path, monkeypatch):
    app, widget, client = takeover_scene(tmp_path, monkeypatch)
    try:
        assert not client.calls
        assert not widget.takeover_preview_button.isEnabled()
        assert not widget.takeover_commit_button.isEnabled()
        assert not widget.run_button.isEnabled()
        rid = prepare_preview(app, widget, client)
        assert len(client.calls) == 1
        assert widget.takeover_commit_button.isEnabled()
        assert not widget.continue_button.isEnabled()
        assert "未完成" in widget.takeover_label.text()
        widget.takeover_commit_button.click()
        wait(app, lambda: not widget.is_busy)
        request, cid = client.calls[-1]
        assert request == {"action": "takeover_commit", "preview_request_id": rid,
            "preview_sha256": "c" * 64, "mode": "single"}
        result = {"run_id": "trial-" + "d" * 64, "runner_state": "waiting", "status": "ready",
            "current_step_id": SOURCE["step_id"], "workflow_id": "workflow-1", "program_id": "program-1",
            "wait_reason": "takeover_ready", "wait": {"wait_id": "wait-recovered", "reason": "takeover_ready"},
            "history": [], "outputs": {}}
        client.results[cid] = receipt(cid, result)
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        assert len(client.calls) == 2 and widget.continue_button.isEnabled()
        widget.continue_button.click()
        wait(app, lambda: not widget.is_busy)
        assert client.calls[-1][0] == {"action": "continue", "run_id": result["run_id"],
            "wait_id": "wait-recovered"}
        assert len(client.calls) == 3
    finally:
        widget.close_client()


def test_unknown_preview_keeps_original_id_and_freezes_choices(tmp_path, monkeypatch):
    app, widget, client = takeover_scene(tmp_path, monkeypatch)
    try:
        widget.takeover_source.setCurrentIndex(1)
        widget.takeover_resolution.setCurrentIndex(widget.takeover_resolution.findData("resume_unexecuted"))
        widget.takeover_preview_button.click()
        wait(app, lambda: not widget.is_busy)
        rid = client.calls[-1][1]
        client.results[rid] = {"request_id": rid, "status": "result_unknown"}
        for _ in range(2):
            widget.refresh()
            wait(app, lambda: not widget.is_busy)
            widget.takeover_preview_button.click()
            widget.takeover_commit_button.click()
        assert len(client.calls) == 1
        assert widget._pending["request_id"] == rid
        assert not widget.takeover_source.isEnabled()
        assert not widget.takeover_resolution.isEnabled()
        assert not widget.takeover_commit_button.isEnabled()
    finally:
        widget.close_client()


@pytest.mark.parametrize("key,value", [
    ("preview_request_id", "other"), ("source_run_id", "trial-" + "e" * 64),
    ("admission_request_id", "other"), ("resolution", "adopt_success"),
    ("preview_sha256", "bad"), ("input_dispatched", True), ("automatic_retry_allowed", True),
])
def test_preview_binding_drift_never_enables_commit(tmp_path, monkeypatch, key, value):
    app, widget, client = takeover_scene(tmp_path, monkeypatch)
    try:
        widget.takeover_source.setCurrentIndex(1)
        widget.takeover_resolution.setCurrentIndex(widget.takeover_resolution.findData("resume_unexecuted"))
        widget.takeover_preview_button.click()
        wait(app, lambda: not widget.is_busy)
        rid = client.calls[-1][1]
        result = preview_value(rid)
        result[key] = value
        client.results[rid] = receipt(rid, result)
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        widget.takeover_commit_button.click()
        assert len(client.calls) == 1 and not widget.takeover_commit_button.isEnabled()
        assert widget._pending["request_id"] == rid
    finally:
        widget.close_client()


def test_nonzero_original_has_no_resume_choice(tmp_path, monkeypatch):
    original = FakeClient.connect
    monkeypatch.setattr(FakeClient, "connect", lambda self: {
        **original(self), "takeover_sources": [{**SOURCE, "action_executed": None,
            "resume_unexecuted_available": False, "resume_unexecuted_reason": "unknown_original_input"}]})
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    try:
        widget.takeover_source.setCurrentIndex(1)
        assert widget.takeover_resolution.findData("resume_unexecuted") == -1
        assert widget.takeover_resolution.findData("adopt_success") > 0
        assert not client.calls
    finally:
        widget.close_client()


def test_reopen_original_ready_preview_never_recreates_it(tmp_path, monkeypatch):
    app, widget, client = takeover_scene(tmp_path, monkeypatch)
    try:
        rid = "preview-before-reopen"
        request = {"action": "takeover_preview", "admission_request_id": SOURCE["admission_request_id"],
            "source_run_id": SOURCE["source_run_id"], "resolution": "resume_unexecuted"}
        widget._accept_status({**client.connect(), "recoverable_controls": [{"request_id": rid,
            "action": "takeover_preview", "request": request,
            "receipt": receipt(rid, preview_value(rid))}]})
        widget._sync()
        assert widget.takeover_commit_button.isEnabled()
        assert not client.calls
        widget.takeover_commit_button.click()
        wait(app, lambda: not widget.is_busy)
        assert len(client.calls) == 1 and client.calls[0][0]["preview_request_id"] == rid
    finally:
        widget.close_client()

@pytest.mark.parametrize("action,state", [
    ("takeover_preview", "failed"), ("takeover_preview", "not_submitted"),
    ("takeover_commit", "failed"), ("takeover_commit", "not_submitted"),
])
def test_unsuccessful_takeover_retains_original_id_without_resubmission(tmp_path, monkeypatch, action, state):
    app, widget, client = takeover_scene(tmp_path, monkeypatch)
    try:
        if action == "takeover_commit":
            prepare_preview(app, widget, client)
            widget.takeover_commit_button.click()
        else:
            widget.takeover_source.setCurrentIndex(1)
            widget.takeover_resolution.setCurrentIndex(widget.takeover_resolution.findData("resume_unexecuted"))
            widget.takeover_preview_button.click()
        wait(app, lambda: not widget.is_busy)
        rid = client.calls[-1][1]
        client.results[rid] = {"request_id": rid, "status": state, "reason": "original_control_failed"}
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        before = deepcopy(client.calls)
        widget.takeover_preview_button.click()
        widget.takeover_commit_button.click()
        assert client.calls == before and widget._pending["request_id"] == rid
        assert not widget.continue_button.isEnabled()
    finally:
        widget.close_client()


@pytest.mark.parametrize("change", ["run", "wait", "outputs", "operation"])
def test_bad_commit_cannot_enable_continue(tmp_path, monkeypatch, change):
    app, widget, client = takeover_scene(tmp_path, monkeypatch)
    try:
        prepare_preview(app, widget, client)
        widget.takeover_commit_button.click()
        wait(app, lambda: not widget.is_busy)
        rid = client.calls[-1][1]
        value = {"run_id": "trial-" + "d" * 64, "runner_state": "waiting", "status": "ready",
            "current_step_id": SOURCE["step_id"], "workflow_id": "workflow-1", "program_id": "program-1",
            "wait_reason": "takeover_ready", "wait": {"wait_id": "wait-original", "reason": "takeover_ready"},
            "outputs": {}}
        result = receipt(rid, value)
        if change == "run":
            result["result"]["run_id"] = "trial-" + "f" * 64
        elif change == "wait":
            result["result"]["wait"]["reason"] = "other"
        elif change == "outputs":
            result["result"]["outputs"] = {"unexpected": "value"}
        else:
            result["operation_succeeded"] = False
        client.results[rid] = result
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        assert widget._pending["request_id"] == rid
        assert not widget.continue_button.isEnabled() and len(client.calls) == 2
    finally:
        widget.close_client()


def test_latest_session_button_attaches_new_client_without_stopping_original(tmp_path):
    import json
    from app.learning_memory.workflow_run_panel import WorkflowRunPanel
    app, unused, _ = panel(tmp_path)
    unused.close_client()
    library = tmp_path / "memory-library"
    library.mkdir()
    old, new = tmp_path / ("session-" + "a" * 32), tmp_path / ("session-" + "b" * 32)
    old.mkdir()
    new.mkdir()
    clients = []
    def factory(path, root):
        value = FakeClient(path, root)
        clients.append(value)
        return value
    widget = WorkflowRunPanel(library, old, client_factory=factory)
    try:
        widget.connect_button.click()
        wait(app, lambda: not widget.is_busy)
        first = clients[-1]
        (tmp_path / "latest-session.json").write_text(json.dumps({"name": new.name}), encoding="utf-8")
        widget.latest_button.click()
        wait(app, lambda: not widget.is_busy)
        assert len(clients) == 2 and first.closed
        assert widget._connected_path == new.resolve() and widget._client is clients[-1]
        assert all(not value.calls for value in clients)
        assert not (old / "closing.json").exists()
    finally:
        widget.close_client()
