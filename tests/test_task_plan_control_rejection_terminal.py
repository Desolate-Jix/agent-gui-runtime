"""Control rejection proves zero input only with the producer's durable ordering."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_admission import TaskPlanRuntime
from app.learning_memory.workflow_runtime import WorkflowRuntime
from scripts.run_local_step_session import preserve_input_admission_rejection
from tests.test_session_input_task_plan import arranged, control
from tests.test_session_input_terminal import inspect, save
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import TARGET, complete_original, scene


def recorded_failure(runtime, request, request_id, **kwargs):
    command = {"kind": "task_plan", "request": deepcopy(request)}
    save(runtime.session, "commands", request_id, command)
    with pytest.raises(Exception) as caught:
        runtime.control(request, request_id, **kwargs)
    error = caught.value
    response = {"command": command, "status": "failed", "error_type": type(error).__name__,
        "error": str(error), "automatic_retry_allowed": False}
    preserve_input_admission_rejection(response, error, request_id)
    save(runtime.session, "responses", request_id, response)
    return response


def empty_runtime(root, *, requires_client_vision=False):
    for folder in ("commands", "responses", "agent-commands"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    co = SimpleNamespace(_memory_library_root=root.parent / "absent-learning", _decision_service=None)
    return TaskPlanRuntime(root, co, owner_id="owner-1", target_identity=lambda: deepcopy(TARGET),
        reviewed_runtime=WorkflowRuntime(root, co), requires_client_vision=requires_client_vision)


def test_only_rejected_start_does_not_require_nonexistent_run(tmp_path):
    runtime = empty_runtime(tmp_path / "session", requires_client_vision=True)
    recorded_failure(runtime, {"action": "start", "plan": plan(count=1)}, "rejected-start")
    proof = inspect(runtime.session)
    assert proof["commands"]["rejected-start"] == {
        "kind": "task_plan", "terminal_status": "not_dispatched", "action_executed": False}


def test_rejected_extra_start_does_not_poison_original_terminal_plan(tmp_path, monkeypatch):
    s, _ = arranged(tmp_path, monkeypatch, cancel=True, zero=True)
    s.runtime.requires_client_vision = True
    recorded_failure(s.runtime, {"action": "start", "plan": plan(count=1)}, "extra-start")
    assert inspect(s.session)["commands"]["extra-start"]["action_executed"] is False


def test_stale_review_is_zero_input_after_original_run_settles(tmp_path, monkeypatch):
    s, original = arranged(tmp_path, monkeypatch, reviewed=True)
    request = {"action": "review", "run_id": s.run_id, "step_id": "step-0",
        "execution_request_id": original.command_id, "verdict": "success", "reason": "Old review",
        "evidence_sha256": original.capture["sha256"]}
    recorded_failure(s.runtime, request, "stale-review")
    assert inspect(s.session)["commands"]["stale-review"]["action_executed"] is False


@pytest.mark.parametrize("invalid_request", [
    {"action": "start"}, {"action": "unknown"},
    {"action": "start", "plan": plan(count=1), "unexpected": True}])
def test_invalid_request_rejection_is_proven_before_schema_validation(tmp_path, invalid_request):
    runtime = empty_runtime(tmp_path / "session")
    recorded_failure(runtime, invalid_request, "invalid-control")
    assert inspect(runtime.session)["commands"]["invalid-control"]["action_executed"] is False


def test_outer_task_plan_admission_rejection_retains_original_input(tmp_path, monkeypatch):
    (tmp_path / "session").mkdir()
    s = scene(tmp_path / "session", monkeypatch, source=plan(count=1))
    start = {"kind": "task_plan", "request": {"action": "start", "plan": plan(count=1)}}
    save(s.session, "commands", "plan-start", start)
    save(s.session, "responses", "plan-start", {"status": "returned", "command": start, "result": s.first})
    request = {"action": "start", "plan": plan(count=1)}
    recorded_failure(s.runtime, request, "extra-before-control",
        before_control=lambda: s.runtime._admit_input("extra-before-control", {"kind": "task_plan", "request": request}))
    original = complete_original(s)
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    proof = inspect(s.session)
    assert proof["commands"]["extra-before-control"]["action_executed"] is False
    assert proof["commands"][original.command_id]["action_executed"] is True


def test_outer_active_agent_rejection_gets_same_proof(tmp_path):
    from scripts.run_local_step_session import check_agent_command_admission
    runtime = empty_runtime(tmp_path / "session")
    request = {"action": "start", "plan": plan(count=1)}
    recorded_failure(runtime, request, "agent-busy", before_control=lambda:
        check_agent_command_admission(SimpleNamespace(active=True), "task_plan", {"kind": "task_plan", "request": request}))
    assert inspect(runtime.session)["commands"]["agent-busy"]["action_executed"] is False


def test_invalid_observe_bindings_do_not_block_proven_pre_validation_rejection(tmp_path, monkeypatch):
    s, _ = arranged(tmp_path, monkeypatch, cancel=True, zero=True)
    recorded_failure(s.runtime, {"action": "observe", "run_id": s.run_id,
        "execution_request_id": [], "observation_request_id": []}, "invalid-observe")
    assert inspect(s.session)["commands"]["invalid-observe"]["action_executed"] is False


@pytest.mark.parametrize("damage", ["missing_record", "processing", "input_possible", "failed",
    "started", "owner", "session", "id", "command", "error", "result_input", "result_action",
    "reference", "response_missing", "record_changed", "record_truncated", "orphan"])
def test_missing_unfinished_or_changed_rejection_is_not_proof(tmp_path, damage):
    runtime = empty_runtime(tmp_path / "session", requires_client_vision=True)
    recorded_failure(runtime, {"action": "start", "plan": plan(count=1)}, "rejected-start")
    path = runtime.session / "task-plan-controls/rejected-start.json"
    record = read_json_snapshot(path)
    response_path = runtime.session / "responses/rejected-start.json"
    response = read_json_snapshot(response_path)
    if damage == "missing_record": path.unlink()
    if damage in {"processing", "input_possible", "failed"}: record["phase"] = damage
    if damage == "started": record["input_dispatch_started"] = True
    if damage == "owner": record["owner_id"] = ""
    if damage == "session": record["session_directory"] = str(runtime.session.parent)
    if damage == "id": record["request_id"] = "other"
    if damage == "command": record["command_sha256"] = "0" * 64
    if damage == "error": response["error"] = "unrelated error"
    if damage == "result_input": response["result"]["input_attempted"] = True
    if damage == "result_action": response["result"]["action_executed"] = True
    if damage == "reference": response["result"]["record"]["sha256"] = "0" * 64
    if damage == "record_changed": record["unexpected"] = True
    if damage == "response_missing": response_path.unlink()
    else: write_json_snapshot(response_path, response)
    if damage == "orphan":
        write_json_snapshot(path.with_name("orphan.json"), record)
    elif damage == "record_truncated": path.write_bytes(b'{"schema":')
    elif damage != "missing_record": write_json_snapshot(path, record)
    with pytest.raises((ValueError, KeyError)):
        inspect(runtime.session)


def test_base_exception_leaves_processing_instead_of_rejection(tmp_path, monkeypatch):
    runtime = empty_runtime(tmp_path / "session")
    request = {"action": "start", "plan": plan(count=1)}
    command = {"kind": "task_plan", "request": request}
    save(runtime.session, "commands", "interrupted", command)
    def crash(*args):
        raise KeyboardInterrupt("host interrupted")
    monkeypatch.setattr(runtime, "_control", crash)
    with pytest.raises(KeyboardInterrupt):
        runtime.control(request, "interrupted")
    record = read_json_snapshot(runtime.session / "task-plan-controls/interrupted.json")
    assert record["phase"] == "processing"
    save(runtime.session, "responses", "interrupted", {"status": "failed", "command": command,
        "error": "interrupted", "error_type": "KeyboardInterrupt", "automatic_retry_allowed": False})
    with pytest.raises(ValueError, match="session_input_"):
        inspect(runtime.session)


@pytest.mark.parametrize("published", [False, True])
def test_failed_dispatch_marker_never_reaches_trial_or_queue(tmp_path, monkeypatch, published):
    from app.core import task_plan_control_receipt as receipts
    runtime = empty_runtime(tmp_path / "session")
    original_write = receipts._write
    def broken(path, value):
        if value["phase"] == "input_possible":
            if published:
                original_write(path, value)
            raise OSError("dispatch marker failed")
        original_write(path, value)
    monkeypatch.setattr(receipts, "_write", broken)
    response = recorded_failure(runtime, {"action": "start", "plan": plan(count=1)}, "marker-failed")
    assert response.get("result") is None
    assert not list(runtime.session.glob("task-plans/trial-*.json"))
    assert {p.stem for p in runtime.session.glob("commands/*.json")} == {"marker-failed"}
    with pytest.raises(ValueError, match="session_input_"):
        inspect(runtime.session)


def test_legacy_error_text_without_receipt_is_still_unknown(tmp_path):
    runtime = empty_runtime(tmp_path / "session", requires_client_vision=True)
    recorded_failure(runtime, {"action": "start", "plan": plan(count=1)}, "legacy")
    (runtime.session / "task-plan-controls/legacy.json").unlink()
    path = runtime.session / "responses/legacy.json"
    response = read_json_snapshot(path)
    response.pop("result")
    write_json_snapshot(path, response)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(runtime.session)


def test_legacy_late_continue_error_without_producer_proof_remains_unknown(tmp_path, monkeypatch):
    s, _ = arranged(tmp_path, monkeypatch, cancel=True, zero=True)
    response = recorded_failure(s.runtime, {"action": "continue", "run_id": s.run_id,
        "wait_id": s.first["wait"]["wait_id"]}, "legacy-late-continue")
    assert response["error"] == "workflow_runner_wait_id_mismatch"
    (s.session / "task-plan-controls/legacy-late-continue.json").unlink()
    response.pop("result")
    save(s.session, "responses", "legacy-late-continue", response)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)


def test_rejected_control_does_not_hide_unknown_original_input(tmp_path, monkeypatch):
    s, original = arranged(tmp_path, monkeypatch, cancel=True, zero=True)
    recorded_failure(s.runtime, {"action": "continue", "run_id": s.run_id,
        "wait_id": s.first["wait"]["wait_id"]}, "rejected-continue")
    worker_path = s.session / "agent-commands" / (original.command_id + ".json")
    worker = read_json_snapshot(worker_path)
    worker["dispatch_in_progress"] = True
    write_json_snapshot(worker_path, worker)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)


@pytest.mark.parametrize("reserved", [False, True])
def test_failed_observe_proof_cannot_hide_a_started_observation(tmp_path, monkeypatch, reserved):
    from tests.test_task_plan_adaptive_review import adaptive_plan
    from tests.test_task_plan_manual_observation import manual_scene, observe_request
    from app.execution import task_plan_manual_observation as manual
    root = tmp_path / "session"
    root.mkdir()
    source = adaptive_plan(count=1)
    s, original, waiting, _, _ = manual_scene(root, monkeypatch, source=source)
    start = {"kind": "task_plan", "request": {"action": "start", "plan": source}}
    save(root, "commands", "plan-start", start)
    save(root, "responses", "plan-start", {"command": start, "status": "returned", "result": s.first})
    observation = observe_request(s, waiting)
    original_write = manual.write_json_snapshot
    with monkeypatch.context() as patch:
        if reserved:
            def capture_failed(*args, **kwargs):
                raise OSError("capture failed")
            def rejection_write_failed(path, value):
                entries = value.get("manual_observations", {}).get(original.command_id, {}).get("requests", {})
                if any(row["status"] == "rejected" for row in entries.values()):
                    raise OSError("cannot persist rejection")
                return original_write(path, value)
            patch.setattr(manual, "capture_followup", capture_failed)
            patch.setattr(manual, "write_json_snapshot", rejection_write_failed)
        else:
            observation["review_packet_sha256"] = "0" * 64
        recorded_failure(s.runtime, observation, "failed-observe")
    control(s, {"action": "cancel", "run_id": s.run_id}, "cancel-original")
    assert s.runtime.tick(force=True)["runner_state"] == "cancelled"
    if reserved:
        state = read_json_snapshot(s.runtime.backend._path(s.run_id))
        assert state["manual_observations"][original.command_id]["requests"]["manual-one"]["status"] == "reserved"
        with pytest.raises(ValueError, match="session_input_task_plan_control_observation_unsettled"):
            inspect(root)
    else:
        assert inspect(root)["commands"]["failed-observe"]["action_executed"] is False
