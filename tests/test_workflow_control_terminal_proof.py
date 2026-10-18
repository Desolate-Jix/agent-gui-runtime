"""缺外层响应的控制请求只能凭原接受来源和固定终态结算闭合。"""
from copy import deepcopy
import hashlib
import json
import shutil

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from tests.test_session_input_terminal import inspect, save
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_terminal_recovery import terminal, service
from tests.test_workflow_trial import services


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def runner_state(root, run):
    path = root / "workflow-runners" / (run["run_id"] + ".json")
    return path, json.loads(path.read_text(encoding="utf-8"))


def arrange(runtime_scene, monkeypatch, action="run", *, legacy=False, returned=False):
    runtime, trials, run, root, _ = runtime_scene
    request = {"action": "run", "run_id": run["run_id"], "mode": "until_wait",
               "vision_capabilities": {"current_vision": "supported", "image_transport": "supported"}}
    command = {"kind": "learning_workflow", "request": request}
    eid = "run-original"
    save(root, "commands", eid, command)
    started = runtime.control(request, eid)
    if action == "continue":
        save(root, "responses", eid, {"command": command, "status": "returned", "result": started})
        request = {"action": "continue", "run_id": run["run_id"], "wait_id": started["wait"]["wait_id"]}
        command = {"kind": "learning_workflow", "request": request}
        eid = "continue-original"
        save(root, "commands", eid, command)
        started = runtime.control(request, eid)
    if returned:
        save(root, "responses", eid, {"command": command, "status": "returned", "result": started})
    if legacy:
        path, value = runner_state(root, run)
        value.pop("control_requests", None)
        write_json_snapshot(path, value)
    ticket = trials.status(run["run_id"])["pending"]
    host = {"pid": 900001, "created": 123.0}
    save(root.parent, "", "latest-session", {"name": root.name, "host_identity": host})
    save(root, "", "report", {"runner_pid": host["pid"]})
    scene = runtime, trials, run, root, ticket, host, host["pid"]
    worker = terminal(scene)
    worker.update(dispatch_in_progress=False, dispatch_attempts=[])
    save(root, "agent-commands", ticket["execution_request_id"], worker)
    monkeypatch.setattr(psutil, "Process", lambda pid: (_ for _ in ()).throw(psutil.NoSuchProcess(pid)))
    recovery = service(scene)
    settled = recovery.settle(recovery.preview(run["run_id"]), "settle-original")
    library = root.parent / "memory-library" / "desktop-review"
    shutil.copytree(trials.programs.library._workspace_root, library)
    (library / ".owner.lock").write_bytes(b"0")
    return scene, eid, command, settled


@pytest.mark.parametrize("capabilities", [None, {"current_vision": "supported", "image_transport": "supported"}])
def test_run_origin_is_durable_before_original_input_enqueue(runtime_scene, capabilities):
    runtime, _, run, root, _ = runtime_scene
    request = {"action": "run", "run_id": run["run_id"], "mode": "until_wait"}
    if capabilities is not None:
        request["vision_capabilities"] = capabilities
    expected = digest({"kind": "learning_workflow", "request": request})
    original = runtime.runner.submit_command
    observed = []
    def submit(eid, command):
        _, value = runner_state(root, run)
        assert value["control_requests"]["run-source"] == {
            "schema": "workflow_runner_control.v1", "command_sha256": expected}
        observed.append(eid)
        return original(eid, command)
    runtime.runner.submit_command = submit
    runtime.control(request, "run-source")
    assert len(observed) == 1


def test_continue_origin_is_durable_before_original_result_read(runtime_scene):
    runtime, _, run, root, _ = runtime_scene
    started = runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "start")
    request = {"action": "continue", "run_id": run["run_id"], "wait_id": started["wait"]["wait_id"]}
    original = runtime.runner.read_result
    observed = []
    def read(eid):
        _, value = runner_state(root, run)
        assert value["control_requests"]["continue-source"] == {
            "schema": "workflow_runner_control.v1", "command_sha256": digest({"kind": "learning_workflow", "request": request})}
        assert value["resume_requests"]["continue-source"] == request["wait_id"]
        observed.append(eid)
        return original(eid)
    runtime.runner.read_result = read
    runtime.control(request, "continue-source")
    assert len(observed) == 1


@pytest.mark.parametrize("action", ["run", "continue"])
def test_exact_original_control_closes_only_after_real_terminal_settlement(runtime_scene, monkeypatch, action):
    scene, eid, command, settled = arrange(runtime_scene, monkeypatch, action)
    _, _, run, root, ticket, _, _ = scene
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}
    result = inspect(root)
    proof = result["commands"][eid]
    assert proof["terminal_status"] == "recovery_settled_control"
    assert proof["action_executed"] is None and proof["response_returned"] is False
    assert proof["run_id"] == run["run_id"] and proof["execution_request_id"] == ticket["execution_request_id"]
    assert proof["control_command_sha256"] == digest(command)
    assert proof["settlement_sha256"] == result["workflow_settlements"][run["run_id"]]
    path, _ = runner_state(root, run)
    assert proof["runner_state_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert settled["recovery_settlement"]["runner_state_sha256"] == proof["runner_state_sha256"]
    assert settled["recovery_settlement"]["task_effect_verified"] is None
    assert not (root / "responses" / (eid + ".json")).exists()
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}


@pytest.mark.parametrize("returned", [False, True])
def test_legacy_control_origin_is_not_backfilled(runtime_scene, monkeypatch, returned):
    scene, eid, _, settled = arrange(runtime_scene, monkeypatch, legacy=True, returned=returned)
    _, _, _, root, _, _, _ = scene
    assert "runner_state_sha256" not in settled["recovery_settlement"]
    if returned:
        assert inspect(root)["commands"][eid]["terminal_status"] == "returned"
    else:
        with pytest.raises(ValueError, match="session_input_"):
            inspect(root)


@pytest.mark.parametrize("change", ["run", "mode", "caps", "command", "metadata", "removed", "ticket",
    "unsettled", "unknown_worker", "wrong_worker", "missing_input_response", "nonworkflow", "live_process", "unaccepted_continue"])
def test_control_closure_does_not_hide_unknown_or_changed_evidence(runtime_scene, monkeypatch, change):
    scene, eid, command, _ = arrange(runtime_scene, monkeypatch)
    _, _, run, root, ticket, _, _ = scene
    path, value = runner_state(root, run)
    if change in {"run", "mode", "caps", "command"}:
        changed = deepcopy(command)
        if change == "run": changed["request"]["run_id"] = "trial-" + "a" * 64
        if change == "mode": changed["request"]["mode"] = "single"
        if change == "caps": changed["request"]["vision_capabilities"]["current_vision"] = "unknown"
        if change == "command": changed["extra"] = "unbound"
        save(root, "commands", eid, changed)
    if change == "metadata":
        value["control_requests"][eid]["command_sha256"] = "0" * 64
        write_json_snapshot(path, value)
    if change == "removed":
        value.pop("control_requests", None)
        write_json_snapshot(path, value)
    if change == "ticket":
        value["ticket"]["execution_request_id"] = "other"
        write_json_snapshot(path, value)
    if change == "unsettled":
        trial_path = root / "workflow-trials" / (run["run_id"] + ".json")
        state = json.loads(trial_path.read_text(encoding="utf-8"))
        state.pop("recovery_settlement")
        write_json_snapshot(trial_path, state)
    if change in {"unknown_worker", "wrong_worker"}:
        worker_path = root / "agent-commands" / (ticket["execution_request_id"] + ".json")
        worker = json.loads(worker_path.read_text(encoding="utf-8"))
        if change == "unknown_worker": worker["dispatch_in_progress"] = True
        else: worker["command_id"] = "other"
        write_json_snapshot(worker_path, worker)
    if change == "missing_input_response":
        (root / "responses" / (ticket["execution_request_id"] + ".json")).unlink()
    if change == "nonworkflow":
        save(root, "commands", "unknown", {"kind": "capture"})
    if change == "live_process":
        class Alive:
            def is_running(self): return True
            def status(self): return psutil.STATUS_RUNNING
            def create_time(self): return 123.0
        monkeypatch.setattr(psutil, "Process", lambda pid: Alive())
    if change == "unaccepted_continue":
        save(root, "commands", "unknown", {"kind": "learning_workflow", "request": {
            "action": "continue", "run_id": run["run_id"], "wait_id": value["wait"]["wait_id"]}})
    with pytest.raises(ValueError, match="session_input_"):
        inspect(root)


def test_changed_continue_wait_is_rejected(runtime_scene, monkeypatch):
    scene, eid, command, _ = arrange(runtime_scene, monkeypatch, "continue")
    root = scene[3]
    command["request"]["wait_id"] = "unaccepted-wait"
    save(root, "commands", eid, command)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(root)
