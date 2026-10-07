"""接管声明与新会话原命令入队必须共享原子边界。"""
from types import SimpleNamespace

import pytest

from app.core.instant_command_queue import CommandQueueBusy, enqueue_command
from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.workflow_runtime import WorkflowRuntime
from tests.test_workflow_recovery_import import import_scene, prepare, commit
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


SELECT = {"kind": "select", "request": {"window_handle": 71}}


def assert_not_imported(scene):
    assert not list((scene.new.parent / "workflow-takeovers").glob("*.json"))
    assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
    assert old_bytes(scene.epoch) == scene.old_before


@pytest.mark.parametrize("returned", [False, True])
def test_new_select_after_prepare_blocks_first_claim(import_scene, returned):
    scene = import_scene
    prepared = prepare(scene)
    enqueue_command(scene.new, "competing-select", SELECT)
    if returned:
        write_json_snapshot(scene.new / "responses/competing-select.json",
                            {"command": SELECT, "status": "returned", "result": {"selected": True}})
    with pytest.raises(ValueError):
        commit(scene, prepared)
    assert_not_imported(scene)


def test_existing_unresolved_command_blocks_prepare(import_scene):
    scene = import_scene
    enqueue_command(scene.new, "pending-select", SELECT)
    with pytest.raises(ValueError):
        prepare(scene)
    assert_not_imported(scene)


def test_first_claim_writer_cannot_enqueue_or_admit_competing_input(import_scene, monkeypatch):
    import app.learning_memory.workflow_recovery_import as module
    scene = import_scene
    prepared = prepare(scene)
    original = module._write
    attempted = []

    def write(path, value):
        if value.get("contract_version") == "workflow_takeover_claim.v1" and value.get("phase") == "prepared":
            with pytest.raises(CommandQueueBusy):
                enqueue_command(scene.new, "inside-select", SELECT)
            runtime = WorkflowRuntime(scene.new, SimpleNamespace(_memory_library_root=scene.library_root))
            with pytest.raises(ValueError):
                runtime.admit("inside-input", {"kind": "input_sequence", "request": {
                    "field_goal": "field", "text": "blocked", "clear_existing": True, "submit_search": False}})
            attempted.append(True)
        return original(path, value)

    monkeypatch.setattr(module, "_write", write)
    _, snapshot = commit(scene, prepared)
    assert attempted and snapshot["wait_reason"] == "takeover_ready"
    assert not list((scene.new / "commands").glob("*.json"))
    assert old_bytes(scene.epoch) == scene.old_before


def test_ready_same_id_retry_allows_new_terminal_command(import_scene):
    scene = import_scene
    prepared = prepare(scene)
    _, first = commit(scene, prepared)
    enqueue_command(scene.new, "later-select", SELECT)
    write_json_snapshot(scene.new / "responses/later-select.json",
                        {"command": SELECT, "status": "returned", "result": {"selected": True}})
    _, second = commit(scene, prepared)
    assert first == second
    assert old_bytes(scene.epoch) == scene.old_before
