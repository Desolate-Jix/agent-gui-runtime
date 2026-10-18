import json
import shutil
import psutil

import pytest

from app.core.json_snapshot import write_json_snapshot
from tests.test_workflow_terminal_recovery import terminal, service
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


def inspect(root):
    from app.execution.session_input_terminal import inspect_session_input_terminal
    return inspect_session_input_terminal(root, root.parent / "memory-library")


def save(root, folder, eid, value):
    (root / folder).mkdir(parents=True, exist_ok=True)
    write_json_snapshot(root / folder / (eid + ".json"), value)


def step():
    return {"phase": "returned", "response": {"data": {"action_executed": True}}}


def job(root, kind="desktop_click"):
    command = {"kind": kind, "request": {"goal": "fresh"}}
    save(root, "commands", "input", command)
    save(root, "responses", "input", {"command": command, "status": "returned", "result": {"contract_version": "agent_command.v1", "command_id": "input", "status": "running", "action_executed": False}})
    worker = {"contract_version": "agent_command.v1", "command_id": "input", "status": "completed", "action_executed": True,
              "dispatch_in_progress": False, "dispatch_attempts": [{"index": 1, "operation": "execute_recognition_plan", "status": "returned", "action_executed": True}],
              "last_execution": {"attempt_index": 1, "operation": "execute_recognition_plan", "receipt": step()}}
    save(root, "agent-commands", "input", worker)
    return command, worker


def test_async_desktop_and_control_bind_original_without_replay(tmp_path):
    root = tmp_path / "session"
    job(root)
    control = {"kind": "agent_command_continue", "request": {"command_id": "input"}}
    save(root, "commands", "continue", control)
    save(root, "responses", "continue", {"command": control, "status": "returned", "result": {"contract_version": "agent_command.v1", "command_id": "input"}})
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    result = inspect(root)
    assert set(result["commands"]) == {"input"} and result["commands"]["input"]["action_executed"] is True
    assert result["input_terminal_settlement_verified"] is True
    assert before == {str(p): p.read_bytes() for p in root.rglob("*.json")}


@pytest.mark.parametrize("change", ["running", "unknown", "dispatch", "index", "action", "last", "id", "orphan"])
def test_worker_uncertainty_or_identity_rejected(tmp_path, change):
    root = tmp_path / "session"
    _, worker = job(root)
    if change == "running": worker["status"] = "running"
    if change == "unknown": worker["dispatch_attempts"][0]["status"] = "unknown"
    if change == "dispatch": worker["dispatch_in_progress"] = True
    if change == "index": worker["dispatch_attempts"][0]["index"] = True
    if change == "action": worker["action_executed"] = None
    if change == "last": worker["last_execution"]["receipt"] = {}
    if change == "id": worker["command_id"] = "other"
    save(root, "agent-commands", "orphan" if change == "orphan" else "input", worker)
    with pytest.raises(ValueError, match="session_input_"): inspect(root)


@pytest.mark.parametrize("mode", ["missing", "mismatch", "failed_unknown", "unknown_kind"])
def test_unproven_response_rejected(tmp_path, mode):
    root = tmp_path / "session"
    command = {"kind": "step", "operation": "type_text"}
    if mode == "unknown_kind": command["kind"] = "future_kind"
    save(root, "commands", "input", command)
    if mode != "missing": save(root, "responses", "input", {"command": {} if mode == "mismatch" else command, "status": "failed" if mode == "failed_unknown" else "returned", "result": {} if mode == "failed_unknown" else step()})
    with pytest.raises(ValueError, match="session_input_"): inspect(root)


def test_close_missing_response_and_empty_catalog(tmp_path):
    root = tmp_path / "session"
    save(root, "commands", "close", {"kind": "close"})
    result = inspect(root)
    assert result["commands"]["close"]["terminal_status"] == "owner_exited_without_close_response"
    assert result["commands"]["close"]["action_executed"] is None


def test_real_persisted_settlement_is_revalidated(runtime_scene, monkeypatch):
    runtime, trials, run, root, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-original")
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
    recovery.settle(recovery.preview(run["run_id"]), "settle-original")
    _, trials, run, root, _, _, _ = scene
    library = root.parent / "memory-library" / "desktop-review"
    shutil.copytree(trials.programs.library._workspace_root, library)
    (library / ".owner.lock").write_bytes(b"0")
    result = inspect(root)
    assert run["run_id"] in result["workflow_settlements"]
    trial_path = root / "workflow-trials" / (run["run_id"] + ".json")
    state = json.loads(trial_path.read_text(encoding="utf-8"))
    state["recovery_settlement"]["action_executed"] = False
    write_json_snapshot(trial_path, state)
    with pytest.raises(ValueError, match="session_input_"): inspect(root)


@pytest.mark.parametrize("unknown", [False, True])
def test_synchronous_batch_actual_step_facts(tmp_path, unknown):
    root = tmp_path / "session"
    command = {"kind": "input_sequence", "request": {}}
    result = {"contract_version": "input_sequence_v1", "status": "interrupted", "action_executed": True,
              "steps": [{"operation": "type_text", "status": "result_unknown" if unknown else "returned", "action_executed": None if unknown else True, "receipt": step()}]}
    save(root, "commands", "input", command)
    save(root, "responses", "input", {"command": command, "status": "returned", "result": result})
    if unknown:
        with pytest.raises(ValueError, match="session_input_"): inspect(root)
    else:
        assert inspect(root)["commands"]["input"]["action_executed"] is True


@pytest.mark.parametrize("unknown", [False, True])
def test_grounding_real_nullable_dispatch_contract(tmp_path, unknown):
    root = tmp_path / "session"
    command = {"kind": "grounding_execute", "request": {"grounding_request_id": "ground"}}
    result = step()
    if unknown: result["phase"] = "result_unknown"
    save(root, "commands", "input", command)
    save(root, "responses", "input", {"command": command, "status": "returned", "result": result})
    save(root, "grounding", "ground", {"contract_version": "grounding_handoff.v1", "request_id": "ground", "execution_id": "input", "phase": "completed", "input_attempted": True, "input_dispatched": None, "execution_result": result})
    if unknown:
        with pytest.raises(ValueError, match="session_input_"): inspect(root)
    else:
        assert inspect(root)["commands"]["input"]["action_executed"] is True


def test_catalog_drift_and_external_library_rejected(tmp_path, monkeypatch):
    from app.execution import session_input_terminal as module
    root = tmp_path / "session"
    job(root)
    original = module._worker
    def changed(worker, eid):
        result = original(worker, eid)
        save(root, "commands", "extra", {"kind": "capture"})
        return result
    monkeypatch.setattr(module, "_worker", changed)
    with pytest.raises(ValueError, match="session_input_catalog_changed"): inspect(root)
    with pytest.raises(ValueError, match="session_input_library_binding"):
        module.inspect_session_input_terminal(root, tmp_path / "external")


@pytest.mark.parametrize("folder,value", [("responses", {"status": "returned"}), ("sequence-progress", {"status": "running"}), ("grounding", {"execution_id": "orphan", "request_id": "orphan"})])
def test_orphan_evidence_is_not_ignored(tmp_path, folder, value):
    root = tmp_path / "session"
    save(root, folder, "orphan", value)
    with pytest.raises(ValueError, match="session_input_orphan"): inspect(root)


@pytest.mark.parametrize("damage", [None, "unknown", "receipt", "action", "schema"])
def test_continue_known_input_with_unavailable_observation(tmp_path, damage):
    from copy import deepcopy
    from tests.test_agent_continue_terminal_proof import arrange
    root = tmp_path / "session"
    _, _, grounding, worker = arrange(root)
    receipt = {"contract_version": "local_direct_step_v1", "step_id": "native-original",
               "operation": "execute_recognition_plan", "phase": "returned_observation_unavailable",
               "effect_verified": False, "automatic_retry_allowed": False,
               "response": {"success": True, "data": {"result": {
                   "execution_path": {"action_executed": True}}}},
               "observation": {"status": "unavailable", "readiness": "unknown",
                   "authorizes_action": False, "automatic_retry_allowed": False}}
    if damage == "unknown": receipt["phase"] = "result_unknown"
    if damage == "schema": receipt["contract_version"] = "future_receipt"
    if damage == "action": receipt["response"]["data"]["result"]["execution_path"]["action_executed"] = None
    worker["status"] = "failed"
    worker["last_execution"]["receipt"] = deepcopy(receipt)
    worker["result"] = deepcopy(receipt)
    grounding["execution_result"] = deepcopy(receipt)
    if damage == "receipt": grounding["execution_result"]["step_id"] = "another-native-step"
    save(root, "agent-commands", "input", worker)
    save(root, "grounding", "ground", grounding)
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    if damage:
        with pytest.raises(ValueError, match="session_input_"): inspect(root)
    else:
        proof = inspect(root)
        assert proof["commands"]["input"]["terminal_status"] == "failed"
        assert proof["commands"]["input"]["action_executed"] is True
        assert worker["result"]["effect_verified"] is False
        assert worker["result"]["automatic_retry_allowed"] is False
    assert before == {str(p): p.read_bytes() for p in root.rglob("*.json")}
