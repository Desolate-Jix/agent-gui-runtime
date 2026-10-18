"""死宿主终态结算不得重放输入、推进分支或伪造业务成功。"""
from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


@pytest.fixture
def recovery_scene(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    proc = subprocess.Popen([sys.executable, "-u", "-c",
        "import os,sys; print(os.getpid(), flush=True); sys.stdin.read()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    actual_pid = int(proc.stdout.readline())
    host = {"pid": proc.pid, "created": psutil.Process(proc.pid).create_time()}
    psutil.Process(actual_pid).kill()
    proc.wait(timeout=10)
    proc.stdin.close()
    proc.stdout.close()
    write_json_snapshot(session.parent / "latest-session.json", {
        "name": session.name, "host_identity": host})
    write_json_snapshot(session / "report.json", {"runner_pid": actual_pid})
    return runtime, trials, run, session, ticket, host, actual_pid


def terminal(scene, status="completed", action=True):
    _, _, _, session, ticket, _, _ = scene
    eid = ticket["execution_request_id"]
    initial = {"contract_version": "agent_command.v1", "command_id": eid, "status": "running",
               "action_executed": False}
    write_json_snapshot(session / "responses" / (eid + ".json"),
        {"command": ticket["suggested_command"], "status": "returned", "result": initial})
    worker = {**initial, "status": status, "action_executed": action,
              "result": {"contract_version": "input_sequence_v1", "status": status,
                         "action_executed": action}}
    (session / "agent-commands").mkdir(exist_ok=True)
    write_json_snapshot(session / "agent-commands" / (eid + ".json"), worker)
    return worker


def service(scene):
    from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
    _, trials, _, _, _, host, runner_pid = scene
    return WorkflowTerminalRecovery(trials, host_identity=host, runner_pid=runner_pid)


def originals(session):
    return {str(path.relative_to(session)): path.read_bytes()
            for folder in ("commands", "responses", "agent-commands", "workflow-runners")
            for path in (session / folder).glob("*.json")}


@pytest.mark.parametrize("status,action", [("completed", True), ("failed", True),
                                          ("cancelled", False), ("failed", None)])
def test_original_terminal_settles_once_without_branch_or_business_verdict(recovery_scene, status, action):
    scene = recovery_scene
    runtime, trials, run, session, ticket, _, _ = scene
    terminal(scene, status, action)
    recovery = service(scene)
    before = trials.status(run["run_id"])
    raw = originals(session)
    preview = recovery.preview(run["run_id"])
    assert trials.status(run["run_id"]) == before
    assert preview["terminal_status"] == status and preview["action_executed"] is action
    assert preview["worker_terminal_sha256"] == hashlib.sha256(
        (session / "agent-commands" / (ticket["execution_request_id"] + ".json")).read_bytes()).hexdigest()
    settled = recovery.settle(preview, "recover-original")
    evidence = settled.pop("recovery_settlement")
    assert settled == before
    assert evidence["action_executed"] is action
    assert evidence["task_effect_verified"] is None
    assert evidence["automatic_retry_allowed"] is False
    assert evidence["status"] == "recovery_paused"
    saved = trials._path(run["run_id"]).read_bytes()
    assert recovery.settle(preview, "recover-original") == trials.status(run["run_id"])
    assert trials._path(run["run_id"]).read_bytes() == saved
    assert originals(session) == raw
    snapshot = runtime.runner.advance(run["run_id"])
    assert snapshot["wait_reason"] == "recovery_paused"
    assert snapshot["pending"] == ticket
    assert originals(session) == raw
    with pytest.raises(ValueError, match="recovery_paused"):
        trials.review(run["run_id"], "unsafe-review", ticket["execution_request_id"],
                      "success", {"results_visible": True}, {"result_title": "next"})


@pytest.mark.parametrize("status", ["running", "awaiting_grounding", "result_unknown"])
def test_nonterminal_never_becomes_failed_or_settled(recovery_scene, status):
    scene = recovery_scene
    _, trials, run, session, _, _, _ = scene
    terminal(scene, status, None)
    before = trials._path(run["run_id"]).read_bytes()
    with pytest.raises(ValueError, match="not_terminal"):
        service(scene).preview(run["run_id"])
    assert trials._path(run["run_id"]).read_bytes() == before
    assert len(list((session / "commands").glob("*.json"))) == 1


@pytest.mark.parametrize("folder", ["commands", "responses", "agent-commands"])
def test_changed_original_bytes_reject_settlement_without_writing_ledger(recovery_scene, folder):
    scene = recovery_scene
    _, trials, run, session, ticket, _, _ = scene
    terminal(scene)
    recovery = service(scene)
    preview = recovery.preview(run["run_id"])
    path = session / folder / (ticket["execution_request_id"] + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    before = trials._path(run["run_id"]).read_bytes()
    with pytest.raises(ValueError, match="preview_changed"):
        recovery.settle(preview, "changed-evidence")
    assert trials._path(run["run_id"]).read_bytes() == before


@pytest.mark.parametrize("drift", ["eid", "command", "ticket", "program", "host", "runner"])
def test_identity_conflict_or_still_live_process_never_settles(recovery_scene, drift):
    scene = recovery_scene
    runtime, trials, run, session, ticket, host, runner_pid = scene
    worker = terminal(scene)
    if drift == "eid":
        worker["command_id"] = "another-execution"
        write_json_snapshot(session / "agent-commands" / (ticket["execution_request_id"] + ".json"), worker)
    elif drift == "command":
        write_json_snapshot(session / "commands" / (ticket["execution_request_id"] + ".json"), {"kind": "capture"})
    elif drift in {"ticket", "program"}:
        state = runtime.runner._load(run["run_id"])
        state["ticket"]["step_id" if drift == "ticket" else "suggested_command"] = (
            "another-step" if drift == "ticket" else {"kind": "capture"})
        runtime.runner._save(state)
    else:
        if drift == "host":
            host = {"pid": os.getpid(), "created": psutil.Process().create_time()}
        else:
            runner_pid = os.getpid()
    from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
    recovery = WorkflowTerminalRecovery(trials, host_identity=host, runner_pid=runner_pid)
    before = trials._path(run["run_id"]).read_bytes()
    with pytest.raises(ValueError):
        recovery.preview(run["run_id"])
    assert trials._path(run["run_id"]).read_bytes() == before


@pytest.mark.parametrize("after_write", [False, True])
def test_atomic_commit_failure_retries_original_request_without_double_count(recovery_scene, monkeypatch, after_write):
    scene = recovery_scene
    _, trials, run, session, _, _, _ = scene
    terminal(scene)
    recovery = service(scene)
    preview = recovery.preview(run["run_id"])
    import app.learning_memory.workflow_terminal_recovery as module
    original_write = module._write
    before = trials._path(run["run_id"]).read_bytes()
    raw = originals(session)
    def broken(path, value):
        if after_write:
            original_write(path, value)
        raise OSError("injected commit interruption")
    monkeypatch.setattr(module, "_write", broken)
    with pytest.raises(OSError):
        recovery.settle(preview, "recover-interrupted")
    if not after_write:
        assert trials._path(run["run_id"]).read_bytes() == before
    monkeypatch.setattr(module, "_write", original_write)
    settled = recovery.settle(preview, "recover-interrupted")
    assert settled["recovery_settlement"]["request_id"] == "recover-interrupted"
    assert settled["history"] == [] and settled["outputs"] == {}
    assert originals(session) == raw
    with pytest.raises(ValueError, match="conflict"):
        recovery.settle(preview, "another-request")


@pytest.mark.parametrize("status", ["started", "unknown"])
def test_terminal_label_cannot_resolve_unknown_dispatch(recovery_scene, status):
    scene = recovery_scene
    _, trials, run, session, ticket, _, _ = scene
    worker = terminal(scene, "failed", None)
    worker["dispatch_attempts"] = [{"index": 1, "operation": "input_sequence",
                                    "status": status, "action_executed": None}]
    write_json_snapshot(session / "agent-commands" / (ticket["execution_request_id"] + ".json"), worker)
    before = trials._path(run["run_id"]).read_bytes()
    with pytest.raises(ValueError, match="dispatch_not_terminal"):
        service(scene).preview(run["run_id"])
    assert trials._path(run["run_id"]).read_bytes() == before


def test_changed_durable_host_binding_rejects_even_if_supplied_pid_is_dead(recovery_scene):
    scene = recovery_scene
    _, trials, run, session, _, _, _ = scene
    terminal(scene)
    recovery = service(scene)
    preview = recovery.preview(run["run_id"])
    write_json_snapshot(session / "report.json", {"runner_pid": os.getpid()})
    before = trials._path(run["run_id"]).read_bytes()
    with pytest.raises(ValueError, match="host_binding"):
        recovery.settle(preview, "host-changed")
    assert trials._path(run["run_id"]).read_bytes() == before


@pytest.mark.parametrize("source", ["attempt", "result"])
def test_cumulative_true_never_downgrades_to_false(recovery_scene, source):
    scene = recovery_scene
    _, _, run, session, ticket, _, _ = scene
    worker = terminal(scene, "completed", False)
    if source == "attempt":
        worker["dispatch_attempts"] = [{"index": 1, "operation": "press_key", "status": "returned",
            "previous_action_executed": False, "action_executed": True}]
        worker["last_execution"] = {"attempt_index": 1, "operation": "press_key",
            "receipt": {"response": {"data": {"pressed": True}}}}
    else:
        worker["result"]["action_executed"] = True
    write_json_snapshot(session / "agent-commands" / (ticket["execution_request_id"] + ".json"), worker)
    assert service(scene).preview(run["run_id"])["action_executed"] is True


def test_concurrent_trial_change_is_preserved_or_rejected(recovery_scene, monkeypatch):
    scene = recovery_scene
    _, trials, run, _, _, _, _ = scene
    terminal(scene)
    recovery = service(scene)
    preview = recovery.preview(run["run_id"])
    inspect = recovery._inspect
    count = 0
    def racing(run_id):
        nonlocal count
        count += 1
        if count == 2:
            trials.cancel(run_id, "concurrent-cancel")
        return inspect(run_id)
    monkeypatch.setattr(recovery, "_inspect", racing)
    with pytest.raises(ValueError, match="preview_changed"):
        recovery.settle(preview, "racing-settlement")
    assert trials.status(run["run_id"])["status"] == "cancel_requested"
    assert "recovery_settlement" not in trials.status(run["run_id"])


@pytest.mark.parametrize("drift", ["last_receipt", "last_index", "index_bool", "action_int"])
def test_terminal_dispatch_evidence_must_match_original_boundary(recovery_scene, drift):
    scene = recovery_scene
    _, trials, run, session, ticket, _, _ = scene
    worker = terminal(scene)
    worker["dispatch_attempts"] = [{"index": 1, "operation": "press_key", "status": "returned",
        "previous_action_executed": False, "action_executed": True}]
    worker["last_execution"] = {"attempt_index": 1, "operation": "press_key",
        "receipt": {"response": {"data": {"pressed": True}}}}
    if drift == "last_receipt":
        worker["last_execution"]["receipt"]["response"]["data"]["pressed"] = False
    elif drift == "last_index":
        worker["last_execution"]["attempt_index"] = True
    elif drift == "index_bool":
        worker["dispatch_attempts"][0]["index"] = True
    else:
        worker["dispatch_attempts"][0]["action_executed"] = 1
    write_json_snapshot(session / "agent-commands" / (ticket["execution_request_id"] + ".json"), worker)
    before = trials._path(run["run_id"]).read_bytes()
    with pytest.raises(ValueError, match="dispatch_evidence_invalid"):
        service(scene).preview(run["run_id"])
    assert trials._path(run["run_id"]).read_bytes() == before
