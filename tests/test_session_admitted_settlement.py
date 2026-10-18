import json
import shutil
from hashlib import sha256

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.execution.session_resources import SessionResourceJournal
from app.execution.session_input_terminal import inspect_session_input_terminal
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
from tests.test_workflow_trial import services
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_terminal_recovery import terminal


@pytest.fixture
def admitted(runtime_scene, monkeypatch):
    runtime, trials, run, source, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "admitted-run")
    old = source.parent / ("session-" + "a" * 32)
    shutil.copytree(source, old)
    trials = TrialService(trials.programs.library, old)
    host = {"pid": 900001, "created": 123.0}
    original_pointer = {"name": old.name, "host_identity": host, "recognition_source": "agent_current", "delegate_profile": None, "api_profile": None}
    write_json_snapshot(old.parent / "latest-session.json", original_pointer)
    write_json_snapshot(old / "report.json", {"runner_pid": host["pid"]})
    journal = SessionResourceJournal(old, recognition_source="agent_current", host_identity=host, runner_identity={"pid": host["pid"], "create_time_ns": 123000000000})
    journal.mark_ready()
    ticket = trials.status(run["run_id"])["pending"]
    worker = terminal((runtime, trials, run, old, ticket, host, host["pid"]))
    worker.update(dispatch_in_progress=False, dispatch_attempts=[])
    write_json_snapshot(old / "agent-commands" / (ticket["execution_request_id"] + ".json"), worker)
    def process(pid):
        if pid != 900002: raise psutil.NoSuchProcess(pid)
        return type("Process", (), {"create_time": lambda self: 124.0, "is_running": lambda self: True, "status": lambda self: psutil.STATUS_RUNNING})()
    monkeypatch.setattr(psutil, "Process", process)
    recovery = WorkflowTerminalRecovery(trials, host_identity=host, runner_pid=host["pid"])
    recovery.settle(recovery.preview(run["run_id"]), "admitted-settle")
    library = old.parent / "memory-library"
    shutil.copytree(trials.programs.library._workspace_root, library / "desktop-review")
    (library / "desktop-review" / ".owner.lock").write_bytes(b"0")
    pointer_raw = (old.parent / "latest-session.json").read_bytes()
    resource = {"contract_version": "session_resource_cleanup.v1", "resources_cleanup_verified": True, "session_name": old.name, "host_identity": host, "runner_identity": journal._state["runner_identity"], "recognition_source": "agent_current", "original_snapshots": {"pointer": sha256(pointer_raw).hexdigest(), "report": sha256((old / "report.json").read_bytes()).hexdigest(), "resources": sha256(journal.path.read_bytes()).hexdigest()}}
    preview = {"contract_version": "session_epoch_admission_preview.v1", "source_session": str(old), "original_pointer_raw_utf8": pointer_raw.decode(), "resource_proof": resource, "input_proof": inspect_session_input_terminal(old, library)}
    digest = sha256(canonical_json_bytes(preview)).hexdigest()
    preview["preview_sha256"] = digest
    new_pointer = {**original_pointer, "name": "session-" + "b" * 32, "host_identity": {"pid": 900002, "created": 124.0}}
    record = {"contract_version": "session_epoch_admission.v1", "request_id": "admitted-one", "preview_sha256": digest, "preview": preview, "new_session_name": new_pointer["name"], "phase": "pointer_published", "new_host_identity": new_pointer["host_identity"]}
    path = old.parent / "recovery-admissions" / "admitted-one.json"
    path.parent.mkdir()
    write_json_snapshot(path, record)
    write_json_snapshot(old.parent / "latest-session.json", new_pointer)
    return old, library, recovery, run["run_id"], path, record


def test_admitted_status_and_inspector_preserve_original_bytes(admitted):
    old, library, recovery, run, path, _ = admitted
    before = {p: p.read_bytes() for p in old.parent.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="host_binding_changed"): recovery.status(run)
    with pytest.raises(ValueError, match="host_binding_changed"): recovery.preview(run)
    original = dict(recovery.trials.status(run)["recovery_settlement"])
    original.update(contract_version="workflow_terminal_recovery_preview.v1")
    original.pop("request_id")
    original.pop("status")
    with pytest.raises(ValueError, match="host_binding_changed"): recovery.settle(original, "admitted-settle")
    state = recovery.status_admitted(run, path)
    assert state["recovery_settlement"]["action_executed"] is True
    assert inspect_session_input_terminal(old, library, admission_record_path=path)["input_terminal_settlement_verified"]
    assert before == {p: p.read_bytes() for p in old.parent.rglob("*") if p.is_file()}


@pytest.mark.parametrize("corruption", ["foreign_pointer", "hash", "command", "owner_alive", "launch_started"])
def test_admitted_rejects_invalid_authority(admitted, monkeypatch, corruption):
    old, _, recovery, run, path, record = admitted
    if corruption == "foreign_pointer": write_json_snapshot(old.parent / "latest-session.json", {"name": "foreign"})
    if corruption == "hash": record["preview_sha256"] = "f" * 64; write_json_snapshot(path, record)
    if corruption == "launch_started": record["phase"] = "launch_started"; write_json_snapshot(path, record)
    if corruption == "command":
        command = next((old / "commands").glob("*.json")); command.write_bytes(command.read_bytes() + b" ")
    if corruption == "owner_alive":
        monkeypatch.setattr(psutil, "Process", lambda pid: type("Process", (), {"create_time": lambda self: 123.0 if pid == 900001 else 124.0, "is_running": lambda self: True, "status": lambda self: psutil.STATUS_RUNNING})())
    with pytest.raises(ValueError): recovery.status_admitted(run, path)
