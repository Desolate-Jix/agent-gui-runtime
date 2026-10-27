"""Use the original plan backend, shared runner and persisted queue; no desktop input."""
from copy import deepcopy
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_session_input_terminal import inspect, save
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import complete_original, scene


def control(s, request, request_id):
    result = s.runtime.control(request, request_id)
    command = {"kind": "task_plan", "request": deepcopy(request)}
    save(s.session, "commands", request_id, command)
    save(s.session, "responses", request_id, {"status": "returned", "command": command, "result": result})
    return result


def arranged(tmp_path, monkeypatch, *, reviewed=False, cancel=False, zero=False):
    root = tmp_path / "session"
    root.mkdir()
    source = plan(count=1, **({"verification": {"kind": "agent_judgment"}} if reviewed else {}))
    s = scene(root, monkeypatch, source=source)
    command = {"kind": "task_plan", "request": {"action": "start", "plan": source}}
    save(root, "commands", "plan-start", command)
    save(root, "responses", "plan-start", {"status": "returned", "command": command, "result": s.first})
    original = complete_original(s, native=not reviewed, status="failure" if zero else "success")
    if zero:
        acceptance = deepcopy(original.receipt)
        acceptance["result"] = {"contract_version": "agent_command.v1", "command_id": original.command_id,
                                "status": "running", "action_executed": False}
        save(root, "responses", original.command_id, acceptance)
        save(root, "agent-commands", original.command_id, {
            "contract_version": "agent_command.v1", "command_id": original.command_id, "status": "failed",
            "action_executed": False, "dispatch_in_progress": False, "dispatch_attempts": [],
            "result": original.result, "observation": original.result["observation"]})
    if cancel:
        control(s, {"action": "cancel", "run_id": s.run_id}, "cancel-original")
    if reviewed and not cancel:
        waiting = s.runtime.tick(force=True)
        control(s, {"action": "review", "run_id": s.run_id, "step_id": "step-0",
            "execution_request_id": original.command_id, "verdict": "success", "reason": "Inspect original frame",
            "evidence_sha256": original.capture["sha256"]}, "review-original")
        final = control(s, {"action": "continue", "run_id": s.run_id,
            "wait_id": waiting["wait"]["wait_id"]}, "continue-original")
    else:
        final = s.runtime.tick(force=True)
    assert final["runner_state"] == ("cancelled" if cancel else "completed")
    return s, original


@pytest.mark.parametrize("reviewed,cancel,zero", [(False, False, False), (True, False, False),
    (False, True, False), (False, True, True)])
def test_original_plan_controls_close_only_with_terminal_dispatch(tmp_path, monkeypatch, reviewed, cancel, zero):
    s, original = arranged(tmp_path, monkeypatch, reviewed=reviewed, cancel=cancel, zero=zero)
    before = {p: p.read_bytes() for p in s.session.rglob("*") if p.is_file()}
    proof = inspect(s.session)
    entries = [v for v in proof["commands"].values() if v["kind"] == "task_plan"]
    assert entries and all(v["action_executed"] is (not zero) for v in entries)
    assert all(v["terminal_status"] == ("cancelled" if cancel else "completed") for v in entries)
    assert any(path.startswith("task-plans/") for path in proof["files"])
    assert original.command_id in proof["commands"]
    assert before == {p: p.read_bytes() for p in s.session.rglob("*") if p.is_file()}


@pytest.mark.parametrize("damage", ["active_trial", "active_runner", "ticket", "wait", "missing_source",
    "missing_runner", "source_changed", "missing_response", "response_changed", "image_changed", "image_missing",
    "history_action", "history_command", "start_plan", "start_origin", "runner_count", "continue_origin",
    "continue_wait", "review", "orphan_runner", "missing_start"])
def test_unknown_or_changed_plan_evidence_never_settles(tmp_path, monkeypatch, damage):
    s, original = arranged(tmp_path, monkeypatch, reviewed=True)
    trial_path = s.runtime.backend._path(s.run_id)
    runner_path = s.runtime.runner._path(s.run_id)
    trial, runner = read_json_snapshot(trial_path), read_json_snapshot(runner_path)
    if damage == "active_trial": trial["status"] = "pending"
    if damage == "history_action": trial["history"][0]["action_executed"] = False
    if damage == "history_command": trial["history"][0]["command_sha256"] = "0" * 64
    if damage in {"active_trial", "history_action", "history_command"}: write_json_snapshot(trial_path, trial)
    if damage == "active_runner": runner["runner_state"] = "waiting"
    if damage == "ticket": runner["ticket"] = deepcopy(original.pending)
    if damage == "wait": runner["wait"] = {"wait_id": "unsettled"}
    if damage == "runner_count": runner["steps_completed"] = 0
    if damage == "start_origin": runner["control_requests"]["plan-start"]["command_sha256"] = "0" * 64
    if damage == "continue_origin": runner["control_requests"].pop("continue-original")
    if damage == "continue_wait": runner["resume_requests"]["continue-original"] = "other-wait"
    if damage in {"active_runner", "ticket", "wait", "runner_count", "start_origin", "continue_origin", "continue_wait"}:
        write_json_snapshot(runner_path, runner)
    if damage == "missing_source": s.runtime.backend._source_path(trial["plan_id"]).unlink()
    if damage == "missing_runner": runner_path.unlink()
    if damage == "source_changed":
        path = s.runtime.backend._source_path(trial["plan_id"])
        source = read_json_snapshot(path)
        source["plan"]["steps"][0]["action"]["goal"] = "Changed target"
        write_json_snapshot(path, source)
    if damage == "missing_response": (s.session / "responses" / (original.command_id + ".json")).unlink()
    if damage == "response_changed":
        response = read_json_snapshot(s.session / "responses" / (original.command_id + ".json"))
        response["result"]["changed"] = True
        save(s.session, "responses", original.command_id, response)
    if damage == "image_changed": original.after.write_bytes(b"changed")
    if damage == "image_missing": original.after.unlink()
    if damage == "start_plan":
        command = read_json_snapshot(s.session / "commands" / "plan-start.json")
        command["request"]["plan"]["title"] = "Changed source"
        save(s.session, "commands", "plan-start", command)
        response = read_json_snapshot(s.session / "responses" / "plan-start.json")
        response["command"] = command
        save(s.session, "responses", "plan-start", response)
    if damage == "review":
        save(s.session, "task-plan-reviews", "review-original", {"action": "review", "reason": "changed"})
    if damage == "orphan_runner": save(s.session, "task-plan-runners", "trial-" + "a" * 64, runner)
    if damage == "missing_start": (s.session / "commands" / "plan-start.json").unlink()
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)


def test_late_continue_only_proven_wait_rejection_is_zero_input(tmp_path, monkeypatch):
    s, _ = arranged(tmp_path, monkeypatch, cancel=True, zero=True)
    command = {"kind": "task_plan", "request": {"action": "continue", "run_id": s.run_id,
        "wait_id": s.first["wait"]["wait_id"]}}
    with pytest.raises(ValueError, match="workflow_runner_wait_id_mismatch") as caught:
        s.runtime.control(command["request"], "late-continue")
    save(s.session, "commands", "late-continue", command)
    response = {"command": command, "status": "failed", "error_type": "ValueError",
                "error": "workflow_runner_wait_id_mismatch", "result": None, "automatic_retry_allowed": False}
    from scripts.run_local_step_session import preserve_input_admission_rejection
    preserve_input_admission_rejection(response, caught.value, "late-continue")
    save(s.session, "responses", "late-continue", response)
    assert inspect(s.session)["commands"]["late-continue"]["action_executed"] is False
    response["error"] = "unexpected_after_dispatch"
    save(s.session, "responses", "late-continue", response)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)


@pytest.mark.parametrize("damage", ["worker_running", "dispatching", "unknown_dispatch", "action_unknown", "missing_worker"])
def test_plan_cancellation_cannot_hide_unsettled_original_worker(tmp_path, monkeypatch, damage):
    s, original = arranged(tmp_path, monkeypatch, cancel=True, zero=True)
    path = s.session / "agent-commands" / (original.command_id + ".json")
    worker = read_json_snapshot(path)
    if damage == "worker_running": worker["status"] = "running"
    if damage == "dispatching": worker["dispatch_in_progress"] = True
    if damage == "unknown_dispatch":
        worker["dispatch_attempts"] = [{"index": 1, "operation": "execute_recognition_plan", "status": "unknown", "action_executed": None}]
    if damage == "action_unknown": worker["action_executed"] = None
    if damage == "missing_worker": path.unlink()
    else: write_json_snapshot(path, worker)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)


def test_plan_catalog_change_during_read_is_rejected(tmp_path, monkeypatch):
    s, _ = arranged(tmp_path, monkeypatch)
    from app.execution.task_plan_backend import TaskPlanBackend
    original = TaskPlanBackend.status
    def changed(self, run_id):
        result = original(self, run_id)
        path = self._source_path(result["plan_id"])
        path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(TaskPlanBackend, "status", changed)
    with pytest.raises(ValueError, match="session_input_catalog_changed"):
        inspect(s.session)


def test_terminal_plan_cancel_keeps_original_dispatch_but_proves_control_noop(tmp_path, monkeypatch):
    s, original = arranged(tmp_path, monkeypatch)
    before = s.runtime.backend.status(s.run_id)
    result = control(s, {"action": "cancel", "run_id": s.run_id}, "cancel-already-complete")
    assert result["runner_state"] == "completed" and s.runtime.backend.status(s.run_id) == before
    proof = inspect(s.session)
    assert proof["commands"][original.command_id]["action_executed"] is True
    assert proof["commands"]["cancel-already-complete"]["action_executed"] is False
    response = read_json_snapshot(s.session / "responses" / "cancel-already-complete.json")
    response["result"]["runner_state"] = "waiting"
    save(s.session, "responses", "cancel-already-complete", response)
    with pytest.raises(ValueError, match="session_input_task_plan_cancel_binding"):
        inspect(s.session)


@pytest.mark.parametrize("earlier,damage", [(False, None), (True, None), (True, "missing_call"),
    (True, "call_capture"), (True, "duplicate_call"), (True, "unknown_dispatch"), (True, "missing_receipt"),
    (True, "reordered"), (True, "last_mismatch")])
def test_api_grounding_preserves_earlier_sequence_focus(tmp_path, earlier, damage):
    from tests.test_agent_continue_terminal_proof import arrange_batch
    from app.core.session_input_terminal import _worker, _continued_grounding_action
    from app.core.task_plan_input_terminal import settle_api_grounding
    root = tmp_path / "session"
    worker, rows = arrange_batch(root)
    worker["api_request"] = {"request_id": "newer-ground" if earlier else "ground", "phase": "grounding_ready"}
    worker["recognition_calls"] = [{"request_id": "ground", "capture_id": "original-capture", "source": "external_api"}]
    grounding = read_json_snapshot(root / "grounding" / "ground.json")
    grounding.update(owner_id="owner-1", execution_id="api-original", capture={"capture_id": "original-capture"})
    grounding["execution_result"]["local_input_scope_closed"] = True
    rows[0]["receipt"]["local_input_scope_closed"] = True
    command = read_json_snapshot(root / "commands" / "input.json")
    if damage == "missing_call": worker["recognition_calls"] = []
    if damage == "call_capture": worker["recognition_calls"][0]["capture_id"] = "other"
    if damage == "duplicate_call": worker["recognition_calls"] *= 2
    if damage == "unknown_dispatch": worker["dispatch_attempts"][0]["status"] = "unknown"
    if damage == "missing_receipt": rows[0].pop("receipt")
    if damage == "reordered": rows.reverse()
    if damage == "last_mismatch": worker["last_execution"]["receipt"]["extra"] = "changed"
    values = {"grounding/ground.json": grounding, "agent-commands/input.json": worker,
        "commands/input.json": command, "task-plans/trial-synthetic.json": {
            "owner_id": "owner-1", "history": [{"execution_request_id": "input"}]}}
    if damage:
        with pytest.raises(ValueError, match="session_input_"):
            settle_api_grounding("grounding/ground.json", values, {"input": {"action_executed": True}},
                _worker, _continued_grounding_action)
    else:
        assert settle_api_grounding("grounding/ground.json", values, {"input": {"action_executed": True}},
            _worker, _continued_grounding_action) == ("input", 1)


@pytest.mark.parametrize("damage", [None, "dispatching", "unknown", "receipt", "duplicate", "owner", "api_id"])
def test_internal_api_grounding_binds_exact_plan_dispatch(tmp_path, monkeypatch, damage):
    s, original = arranged(tmp_path, monkeypatch)
    command_id = original.command_id
    response = read_json_snapshot(s.session / "responses" / (command_id + ".json"))
    receipt = deepcopy(response["result"])
    receipt.update(contract_version="local_direct_step_v1", operation="execute_recognition_plan", local_input_scope_closed=True)
    worker = {"contract_version": "agent_command.v1", "command_id": command_id, "status": "completed",
        "action_executed": True, "dispatch_in_progress": False,
        "dispatch_attempts": [{"index": 1, "operation": "execute_recognition_plan", "status": "returned", "action_executed": True}],
        "last_execution": {"attempt_index": 1, "operation": "execute_recognition_plan", "receipt": receipt},
        "api_request": {"request_id": "ag-original"}}
    # Grounding validation is independent of trial byte refs; test the strict binder directly.
    from app.core.session_input_terminal import _worker, _continued_grounding_action
    from app.core.task_plan_input_terminal import settle_api_grounding
    grounding = {"contract_version": "grounding_handoff.v1", "request_id": "ag-original",
        "owner_id": "owner-1", "phase": "completed", "execution_id": "api-original",
        "input_attempted": True, "input_dispatched": None, "execution_result": deepcopy(receipt)}
    values = {"grounding/ag-original.json": grounding,
        "agent-commands/" + command_id + ".json": worker,
        "commands/" + command_id + ".json": response["command"],
        "task-plans/" + s.run_id + ".json": s.runtime.backend.status(s.run_id)}
    if damage == "dispatching": worker["dispatch_in_progress"] = True
    if damage == "unknown": worker["dispatch_attempts"][0]["status"] = "unknown"
    if damage == "receipt": grounding["execution_result"]["step_id"] = "other"
    if damage == "owner": grounding["owner_id"] = "other-owner"
    if damage == "api_id": worker["api_request"]["request_id"] = "other"
    if damage == "duplicate": values["agent-commands/other.json"] = deepcopy(worker)
    results = {command_id: {"action_executed": True}}
    if damage:
        with pytest.raises(ValueError, match="session_input_"):
            settle_api_grounding("grounding/ag-original.json", values, results, _worker, _continued_grounding_action)
    else:
        assert settle_api_grounding("grounding/ag-original.json", values, results, _worker, _continued_grounding_action) == (command_id, 1)
