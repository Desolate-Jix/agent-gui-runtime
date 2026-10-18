"""原 InstantSession 明确恢复只创建一个新宿主，不放宽旧 gate。"""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from mcp.server import MCPServer
import asyncio

from app.core.json_snapshot import write_json_snapshot
from app.execution.session_resources import SessionResourceJournal
from app.instant_mcp import InstantSession, InstantStartError, build_server
from tests.test_workflow_trial import services
from tests.test_workflow_runtime import runtime_scene


@pytest.fixture
def epoch_scene(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "新会话准入"
    old = data / ("session-" + "a" * 32)
    old.mkdir(parents=True)
    (old / "commands").mkdir()
    (old / "responses").mkdir()
    host = {"pid": 900001, "created": 100.125}
    SessionResourceJournal(old, recognition_source="agent_current", host_identity=host,
        runner_identity={"pid":900002,"create_time_ns":100250000000}).mark_ready()
    write_json_snapshot(old / "report.json", {"phase":"ready","runner_pid":900002,"target":None})
    write_json_snapshot(data / "latest-session.json", {"name":old.name,"host_identity":host,
        "recognition_source":"agent_current","delegate_profile":None,"api_profile":None})
    active = {}
    launches = []
    class Process:
        def __init__(self, pid):
            if pid not in active:
                raise psutil.NoSuchProcess(pid)
            self.pid = pid
        def create_time(self): return active[self.pid]["created"]
        def is_running(self): return True
        def status(self): return psutil.STATUS_RUNNING
        def ppid(self): return os.getpid()
        def cmdline(self): return list(active[self.pid]["command"])
    class Popen:
        def __init__(self, command, **kwargs):
            self.pid = 900100 + len(launches)
            self.command = command
            launches.append(self)
            active[self.pid] = {"created":200.125 + len(launches), "command":command}
            new = Path(command[command.index("--output") + 1])
            new.mkdir()
            (new / "commands").mkdir()
            (new / "responses").mkdir()
            SessionResourceJournal(new, recognition_source="agent_current",
                host_identity={"pid":self.pid,"created":active[self.pid]["created"]},
                runner_identity={"pid":self.pid,"create_time_ns":round(active[self.pid]["created"]*1000000000)}).mark_ready()
            write_json_snapshot(new / "report.json", {"phase":"ready","runner_pid":self.pid,"target":None})
        def poll(self): return None if self.pid in active else 0
    monkeypatch.setattr(psutil, "Process", Process)
    monkeypatch.setattr("app.instant_mcp.subprocess.Popen", Popen)
    manager = InstantSession(root, data, allow_local_input=True, recognition_source="agent_current")
    try:
        yield SimpleNamespace(manager=manager,old=old,launches=launches,active=active)
    finally:
        if manager.log_file:
            manager.log_file.close()
        if manager.lock_file:
            manager.lock_file.close()


def old_bytes(scene):
    return {str(path.relative_to(scene.old)):path.read_bytes()
            for path in scene.old.rglob("*") if path.is_file()}


def test_preview_is_readonly_and_ordinary_new_session_remains_blocked(epoch_scene):
    scene = epoch_scene
    raw = old_bytes(scene)
    preview = scene.manager.preview_recovery()
    assert preview["resource_proof"]["resources_cleanup_verified"] is True
    assert preview["input_proof"]["input_terminal_settlement_verified"] is True
    assert len(preview["preview_sha256"]) == 64
    assert not scene.launches and old_bytes(scene) == raw
    with pytest.raises(InstantStartError, match="previous session"):
        scene.manager.start(new_session=True)
    assert not scene.launches


def test_explicit_recovery_uses_original_launcher_once_and_empty_new_queue(epoch_scene):
    scene = epoch_scene
    raw = old_bytes(scene)
    preview = scene.manager.preview_recovery()
    result = scene.manager.recover_session("recover-once", preview["preview_sha256"])
    assert result["recovery_admission"]["new_epoch_ready"] is True
    assert result["recovery_admission"]["workflow_takeover_completed"] is False
    assert scene.manager.session != scene.old and scene.manager.session.parent == scene.old.parent
    assert len(scene.launches) == 1
    assert not list((scene.manager.session / "commands").glob("*.json"))
    again = scene.manager.recover_session("recover-once", preview["preview_sha256"])
    assert again["session_directory"] == result["session_directory"]
    assert len(scene.launches) == 1 and old_bytes(scene) == raw


def test_wrong_preview_and_operator_disabled_never_launch(epoch_scene):
    scene = epoch_scene
    preview = scene.manager.preview_recovery()
    with pytest.raises(ValueError):
        scene.manager.recover_session("wrong-preview", "f" * 64)
    scene.manager.allow_local_input = False
    with pytest.raises(ValueError):
        scene.manager.recover_session("disabled", preview["preview_sha256"])
    assert not scene.launches


def test_unresolved_original_command_blocks_preview_and_launch(epoch_scene):
    scene = epoch_scene
    write_json_snapshot(scene.old / "commands" / "unresolved-input.json",
        {"kind":"input_sequence","request":{"field_goal":"current field","text":"新值"}})
    raw = old_bytes(scene)
    with pytest.raises(ValueError):
        scene.manager.preview_recovery()
    assert not scene.launches and old_bytes(scene) == raw


def test_intent_write_failure_cannot_spawn(epoch_scene, monkeypatch):
    from app.execution import session_epoch_admission as admission
    scene = epoch_scene
    preview = scene.manager.preview_recovery()
    original = admission.write_json_snapshot
    def fail(path, value):
        if Path(path).parent.name == "recovery-admissions":
            raise OSError("controlled intent write failure")
        return original(path, value)
    monkeypatch.setattr(admission, "write_json_snapshot", fail)
    with pytest.raises(OSError):
        scene.manager.recover_session("write-failed", preview["preview_sha256"])
    assert not scene.launches


def test_pointer_publication_retry_does_not_create_another_host(epoch_scene, monkeypatch):
    from app import instant_mcp
    scene = epoch_scene
    preview = scene.manager.preview_recovery()
    original = instant_mcp.write_json
    def fail(path, value):
        if Path(path).name == "latest-session.json":
            raise OSError("controlled pointer publication failure")
        return original(path, value)
    monkeypatch.setattr(instant_mcp, "write_json", fail)
    with pytest.raises(OSError):
        scene.manager.recover_session("pointer-failed", preview["preview_sha256"])
    assert len(scene.launches) == 1
    monkeypatch.setattr(instant_mcp, "write_json", original)
    recovered = scene.manager.recover_session("pointer-failed", preview["preview_sha256"])
    assert recovered["recovery_admission"]["new_epoch_ready"] is True
    assert len(scene.launches) == 1


def test_reconnected_transaction_reads_the_same_new_host(epoch_scene):
    scene = epoch_scene
    preview = scene.manager.preview_recovery()
    first = scene.manager.recover_session("reconnect", preview["preview_sha256"])
    scene.manager.lock_file.close()
    scene.manager.lock_file = None
    reconnected = InstantSession(scene.manager.root,scene.manager.data_root,
        allow_local_input=True,recognition_source="agent_current")
    try:
        again = reconnected.recover_session("reconnect",preview["preview_sha256"])
        assert again["session_directory"] == first["session_directory"]
        assert len(scene.launches) == 1
    finally:
        if reconnected.lock_file:
            reconnected.lock_file.close()


def test_public_discovery_exposes_separate_preview_and_explicit_recovery(epoch_scene):
    server = build_server(epoch_scene.manager)
    tools = server._tool_manager._tools
    assert "instant_recovery_preview" in tools and "instant_recover_session" in tools


def test_public_recovery_roundtrip_reads_same_transaction_without_replay(epoch_scene):
    scene = epoch_scene
    server = build_server(scene.manager)
    preview = asyncio.run(server.call_tool("instant_recovery_preview", {}))
    assert not preview.is_error
    arguments = {"request_id":"public-once", "preview_sha256":preview.structured_content["preview_sha256"]}
    first = asyncio.run(server.call_tool("instant_recover_session", arguments))
    second = asyncio.run(server.call_tool("instant_recover_session", arguments))
    assert not first.is_error and not second.is_error
    assert first.structured_content == second.structured_content
    assert second.structured_content["recovery_admission"]["workflow_takeover_completed"] is False
    assert len(scene.launches) == 1


def test_public_post_launch_exception_does_not_claim_no_launch(epoch_scene, monkeypatch):
    from app import instant_mcp
    scene = epoch_scene
    server = build_server(scene.manager)
    preview = scene.manager.preview_recovery()
    original = instant_mcp.write_json
    def fail(path, value):
        if Path(path).name == "latest-session.json":
            raise OSError("controlled publication failure")
        return original(path, value)
    monkeypatch.setattr(instant_mcp, "write_json", fail)
    failed = asyncio.run(server.call_tool("instant_recover_session", {
        "request_id":"public-failed", "preview_sha256":preview["preview_sha256"]}))
    assert failed.is_error and len(scene.launches) == 1
    assert failed.structured_content["host_launch_attempted"] is None
    assert failed.structured_content["automatic_retry_allowed"] is False
    record = json.loads((scene.old.parent / "recovery-admissions/public-failed.json").read_text(encoding="utf-8"))
    assert record["phase"] == "host_created" and record["new_host_identity"]["pid"] == scene.launches[0].pid


def test_original_settled_workflow_survives_pointer_publication_and_same_id_read(epoch_scene, runtime_scene):
    from app.learning_memory.workflow_trial import TrialService
    from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
    from tests.test_workflow_terminal_recovery import terminal
    scene = epoch_scene
    runtime, original_trials, run, source, _ = runtime_scene
    runtime.control({"action":"run", "run_id":run["run_id"], "mode":"until_wait"}, "original-run")
    for name in ("commands", "responses", "workflow-trials", "workflow-runners"):
        shutil.copytree(source / name, scene.old / name, dirs_exist_ok=True)
    trials = TrialService(original_trials.programs.library, scene.old)
    ticket = trials.status(run["run_id"])["pending"]
    pointer = json.loads((scene.old.parent / "latest-session.json").read_text(encoding="utf-8"))
    worker = terminal((runtime,trials,run,scene.old,ticket,pointer["host_identity"],900002))
    worker.update(dispatch_in_progress=False, dispatch_attempts=[])
    write_json_snapshot(scene.old / "agent-commands" / (ticket["execution_request_id"] + ".json"), worker)
    service = WorkflowTerminalRecovery(trials,host_identity=pointer["host_identity"],runner_pid=900002)
    service.settle(service.preview(run["run_id"]), "original-settlement")
    library = scene.old.parent / "memory-library" / "desktop-review"
    shutil.copytree(original_trials.programs.library._workspace_root,library)
    from app.learning_memory.workspace import MemoryWorkspace
    with MemoryWorkspace(library.parent):
        pass
    assert (library / ".owner.lock").read_bytes()
    before = old_bytes(scene)
    preview = scene.manager.preview_recovery()
    assert run["run_id"] in preview["input_proof"]["workflow_settlements"]
    first = scene.manager.recover_session("workflow-admission",preview["preview_sha256"])
    second = scene.manager.recover_session("workflow-admission",preview["preview_sha256"])
    assert first["recovery_admission"]["new_epoch_ready"] is True
    assert second["session_directory"] == first["session_directory"]
    assert not second["recovery_admission"]["workflow_takeover_completed"]
    assert len(scene.launches) == 1 and old_bytes(scene) == before
    with pytest.raises(ValueError,match="host_binding_changed"):
        service.status(run["run_id"])
