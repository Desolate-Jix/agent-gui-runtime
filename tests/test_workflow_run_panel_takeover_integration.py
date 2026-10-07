"""普通 Qt 经真实客户端与公开运行时联调；隔离队列不派发桌面输入。"""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.learning_memory.workflow_run_client import WorkflowRunClient
from app.learning_memory.workflow_run_panel import WorkflowRunPanel
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workspace import MemoryWorkspace

from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services, WORKFLOW
from tests.test_workflow_unexecuted_takeover import build_unexecuted, public_scene
from tests.test_workflow_run_panel import wait


_APP = None


def new_panel(scene):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    with MemoryWorkspace(scene.library_root) as library:
        saved = TrialService(library, scene.epoch.old).programs.load(WORKFLOW)
    widget = WorkflowRunPanel(scene.library_root, scene.new)
    widget.set_context(saved, "search")
    widget.connect_session()
    wait(_APP, lambda: not widget.is_busy)
    assert type(widget._client) is WorkflowRunClient
    assert widget._host_alive, widget.status_label.text()
    assert len(widget.takeover.rows) == 1, widget.status_label.text()
    return widget


def commands(scene):
    return {path.stem: read_json_snapshot(path)
            for path in (scene.new / "commands").glob("*.json")}


def request_after_click(widget, button):
    button.click()
    wait(_APP, lambda: not widget.is_busy)
    assert widget._pending is not None, widget.status_label.text()
    return widget._pending["request_id"]


def deliver(public, request_id, *, publish=False):
    command = read_json_snapshot(public.scene.new / "commands" / (request_id + ".json"))
    assert command["kind"] == "learning_workflow"
    result = public.runtime.control(command["request"], request_id)
    write_json_snapshot(public.scene.new / "responses" / (request_id + ".json"),
                        {"command": command, "status": "returned", "result": result})
    if publish:
        path = public.scene.new / "report.json"
        report = read_json_snapshot(path)
        report["workflow_run"] = deepcopy(result)
        write_json_snapshot(path, report)
    return result


def refresh(widget):
    widget.refresh()
    wait(_APP, lambda: not widget.is_busy)


def choose_preview(scene, public, widget):
    assert not commands(scene)
    assert not widget.takeover_commit_button.isEnabled()
    assert not widget.continue_button.isEnabled()
    widget.takeover_source.setCurrentIndex(1)
    widget.takeover_resolution.setCurrentIndex(
        widget.takeover_resolution.findData("resume_unexecuted"))
    request_id = request_after_click(widget, widget.takeover_preview_button)
    request = commands(scene)[request_id]["request"]
    assert request == {"action": "takeover_preview", "admission_request_id": "fresh-epoch-admission",
                       "source_run_id": scene.source_run_id, "resolution": "resume_unexecuted"}
    result = deliver(public, request_id)
    refresh(widget)
    assert widget.takeover.preview["preview_request_id"] == request_id
    assert widget.takeover_commit_button.isEnabled(), widget.status_label.text()
    assert not widget.continue_button.isEnabled()
    assert len(commands(scene)) == 1
    assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
    return request_id, result


@pytest.mark.parametrize("prefix_count", [0, 1])
def test_ordinary_preview_reopen_commit_reopen_and_explicit_continue(
        build_unexecuted, monkeypatch, prefix_count):
    scene = build_unexecuted(prefix_count)
    public = public_scene(scene, monkeypatch)
    widget = new_panel(scene)
    try:
        preview_id, preview = choose_preview(scene, public, widget)
        original_commands = commands(scene)
        widget.close_client()
        widget = new_panel(scene)
        assert commands(scene) == original_commands
        assert widget.takeover.preview_id == preview_id
        assert widget.takeover.preview["preview_sha256"] == preview["preview_sha256"]
        assert widget.takeover_commit_button.isEnabled(), widget.status_label.text()

        commit_id = request_after_click(widget, widget.takeover_commit_button)
        request = commands(scene)[commit_id]["request"]
        assert request == {"action": "takeover_commit", "preview_request_id": preview_id,
                           "preview_sha256": preview["preview_sha256"], "mode": "single"}
        snapshot = deliver(public, commit_id, publish=True)
        refresh(widget)
        assert snapshot["wait_reason"] == "takeover_ready"
        assert snapshot["current_step_id"] == "search"
        assert len(snapshot["history"]) == prefix_count
        assert public.runtime._enabled_run is None
        assert len(commands(scene)) == 2
        assert widget.continue_button.isEnabled(), widget.status_label.text()
        assert not widget.takeover_commit_button.isEnabled()
        assert len(public.calls) == 2

        original_commands = commands(scene)
        widget.close_client()
        widget = new_panel(scene)
        assert commands(scene) == original_commands
        assert widget._run["run_id"] == snapshot["run_id"]
        assert widget._run["wait"]["wait_id"] == snapshot["wait"]["wait_id"]
        assert widget.continue_button.isEnabled(), widget.status_label.text()
        assert public.runtime._enabled_run is None

        continue_id = request_after_click(widget, widget.continue_button)
        assert commands(scene)[continue_id]["request"] == {
            "action": "continue", "run_id": snapshot["run_id"],
            "wait_id": snapshot["wait"]["wait_id"]}
        deliver(public, continue_id)
        public.runtime.tick(force=True)
        inputs = {key: value for key, value in commands(scene).items()
                  if value["kind"] != "learning_workflow"}
        assert len(inputs) == 1
        assert scene.old_eid not in inputs
        assert old_bytes(scene.epoch) == scene.old_before
        public.runtime.tick(force=True)
        assert {key: value for key, value in commands(scene).items()
                if value["kind"] != "learning_workflow"} == inputs
    finally:
        widget.close_client()


def test_reopened_unknown_commit_reads_original_request_without_automatic_input(
        build_unexecuted, monkeypatch):
    scene = build_unexecuted()
    public = public_scene(scene, monkeypatch)
    widget = new_panel(scene)
    try:
        preview_id, preview = choose_preview(scene, public, widget)
        commit_id = request_after_click(widget, widget.takeover_commit_button)
        before = commands(scene)
        widget.close_client()
        widget = new_panel(scene)
        assert widget._pending["request_id"] == commit_id
        assert widget.takeover.preview_id == preview_id
        assert widget.takeover.preview["preview_sha256"] == preview["preview_sha256"]
        for _ in range(2):
            refresh(widget)
            widget.takeover_preview_button.click()
            widget.takeover_commit_button.click()
            widget.continue_button.click()
        assert commands(scene) == before
        assert widget._pending["request_id"] == commit_id
        assert not widget.continue_button.isEnabled()
        assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
        assert old_bytes(scene.epoch) == scene.old_before
    finally:
        widget.close_client()
