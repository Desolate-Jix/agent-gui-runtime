"""真实共用运行器及持久队列，桌面边界仅提供原收据与全新合成图。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_admission import TaskPlanRuntime
from app.learning_memory.workflow_runtime import WorkflowRuntime
from tests.test_task_plan_contract import plan


TARGET = {"handle": 11, "process_id": 22, "process_create_time": 33.0}


def scene(tmp_path, monkeypatch, *, source=None, decision=None, owner="owner-1"):
    for directory in ("commands", "responses", "captures", "agent-commands"):
        (tmp_path / directory).mkdir(exist_ok=True)
    def learning_forbidden(*args, **kwargs):
        pytest.fail("execution-only plan must not open learning storage")
    monkeypatch.setattr("app.learning_memory.workflow_runner.MemoryWorkspace", learning_forbidden)
    co = SimpleNamespace(_memory_library_root=tmp_path / "absent-learning", _decision_service=decision)
    reviewed = WorkflowRuntime(tmp_path, co)
    target = deepcopy(TARGET)
    runtime = TaskPlanRuntime(tmp_path, co, owner_id=owner, target_identity=lambda: deepcopy(target), reviewed_runtime=reviewed)
    first = runtime.control({"action": "start", "plan": source or plan()}, "plan-start")
    return SimpleNamespace(runtime=runtime, reviewed=reviewed, co=co, session=tmp_path,
                           first=first, run_id=first["run_id"], target=target)


def complete_original(s, *, status="success", native=True, proof_patch=None, identity=None, async_receipt=False):
    pending = s.runtime.backend.status(s.run_id)["pending"]
    command_id = pending["execution_request_id"]
    assert read_json_snapshot(s.session / "commands" / (command_id + ".json")) == pending["suggested_command"]
    before = s.session / "captures" / (command_id + "-before.png")
    after = s.session / "captures" / (command_id + "-after.png")
    Image.new("RGB", (80, 60), "black").save(before)
    Image.new("RGB", (80, 60), "white").save(after)
    capture = {"capture_id": command_id + "-after", "image_path": str(after), "sha256": sha256(after.read_bytes()).hexdigest(),
               "window_identity": deepcopy(identity or TARGET), "window_size": {"width": 80, "height": 60}}
    baseline = {"status": "absent"}
    samples = [{"status": "matched", "elapsed_ms": t, "runtime_id": [42, 7], "bbox": [2, 3, 10, 12],
                "target_window_handle": TARGET["handle"], "process_id": TARGET["process_id"]} for t in (10, 110, 210)]
    proof = {"status": "condition_met", "source": "uia_exact_name", "expected": pending["suggested_command"].get("observation_condition"),
             "after_sha256": capture["sha256"], "after_capture_rechecked": True, "baseline": baseline, "samples": samples}
    proof.update(proof_patch or {})
    observation = {"status": "captured", "capture": capture, "condition": proof if native else {"status": "timeout"}}
    result = {"phase": "returned", "status": "completed", "action_executed": True,
              "target_identity": {"target_window_handle": (identity or TARGET)["handle"],
                                  "process_id": (identity or TARGET)["process_id"],
                                  "process_create_time": (identity or TARGET)["process_create_time"]},
              "capture": {"capture_id": command_id + "-before", "image_path": str(before), "sha256": sha256(before.read_bytes()).hexdigest()},
              "observation": observation,
              "response": {"success": True, "data": {"result": {"execution_path": {"action_executed": True}}}}}
    if pending["suggested_command"]["kind"] == "input_sequence":
        result["steps"] = [{"name": "search", "action_executed": True, "receipt": {"observation": deepcopy(observation), "target_identity": result["target_identity"]}}]
    if status != "success":
        result.update(success=False, phase="failed", action_executed=status == "partial")
        result["response"].update(success=False)
        result["response"]["data"]["result"]["execution_path"]["action_executed"] = status == "partial"
        if status == "unknown":
            result.pop("action_executed")
            result["response"]["data"]["result"]["execution_path"].pop("action_executed")
    receipt = {"status": "returned", "command": deepcopy(pending["suggested_command"]), "result": result, "observation": capture}
    if async_receipt:
        receipt["result"] = {"contract_version": "agent_command.v1", "command_id": command_id, "status": "running"}
        write_json_snapshot(s.session / "agent-commands" / (command_id + ".json"), {
            "contract_version": "agent_command.v1", "command_id": command_id, "status": "completed",
            "result": result, "observation": observation, "action_executed": True})
    write_json_snapshot(s.session / "responses" / (command_id + ".json"), receipt)
    return SimpleNamespace(pending=pending, command_id=command_id, before=before, after=after,
                           capture=capture, receipt=receipt, result=result)


def test_two_step_plan_runs_without_learning_installation(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    assert s.first["wait_reason"] == "execution_pending"
    first = complete_original(s)
    second = s.runtime.tick(force=True)
    assert second["wait_reason"] == "execution_pending"
    assert second["pending"]["step_id"] == "step-1"
    last = complete_original(s, async_receipt=True)
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert [row["execution_request_id"] for row in final["history"]] == [first.command_id, last.command_id]
    assert all(row["judged_by"] == "native_condition" for row in final["history"])
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert not (tmp_path / "absent-learning").exists()
    assert s.runtime.tick(force=True) is None


def test_same_start_id_same_plan_is_idempotent(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    for _ in range(3):
        repeated = s.runtime.control({"action": "start", "plan": plan()}, "plan-start")
        assert repeated["run_id"] == s.run_id
        assert repeated["active_command_id"] == s.first["active_command_id"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_same_start_id_changed_plan_rejected(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    changed = plan()
    changed["steps"][0]["action"]["goal"] = "Other panel"
    with pytest.raises(ValueError, match="start_idempotency_conflict"):
        s.runtime.control({"action": "start", "plan": changed}, "plan-start")
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("status,runner_state", [("failure", "failed"), ("unknown", "waiting"), ("partial", "waiting")])
def test_failed_or_unknown_first_step_never_dispatches_second(tmp_path, monkeypatch, status, runner_state):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s, status=status)
    result = s.runtime.tick(force=True)
    assert result["runner_state"] == runner_state
    assert result["wait_reason"] == (None if runner_state == "failed" else "verification_required")
    for _ in range(3):
        s.runtime.control({"action": "status", "run_id": s.run_id}, "read-only-status")
        s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt


def test_cancel_preserves_dispatched_action(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s)
    cancelled = s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-one")
    assert cancelled["status"] == "cancel_requested"
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "cancelled"
    assert final["history"][0]["action_executed"] is True
    assert final["history"][0]["verdict"] == "cancelled"
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt


@pytest.mark.parametrize("verification", [{"kind": "agent_judgment"}, None])
def test_cancel_after_existing_review_wait_keeps_one_settlement_tick_and_original_action(tmp_path, monkeypatch, verification):
    source = plan(verification=verification)
    s = scene(tmp_path, monkeypatch, source=source)
    original = complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required" and "error" not in waiting["wait"]
    assert s.runtime.tick(force=True) is None
    cancelled = s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-after-wait")
    assert cancelled["status"] == "cancel_requested" and cancelled["runner_state"] == "cancel_requested"
    assert cancelled["pending"]["execution_request_id"] == original.command_id
    assert s.runtime._enabled_run == s.run_id
    for index in range(3):
        snapshot = s.runtime.control({"action": "status", "run_id": s.run_id}, "cancel-status-" + str(index))
        assert snapshot["status"] == "cancel_requested" and snapshot["history"] == []
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["runner_state"] == "cancelled"
    assert final["pending"] is None
    assert len(final["history"]) == 1
    row = final["history"][0]
    assert row["execution_request_id"] == original.command_id and row["step_id"] == "step-0"
    assert row["action_executed"] is True and row["verdict"] == "cancelled"
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
    for index in range(3):
        assert s.runtime.control({"action": "status", "run_id": s.run_id}, "finished-status-" + str(index))["status"] == "cancelled"
        assert s.runtime.tick(force=True) is None
    assert s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-after-wait")["status"] == "cancelled"
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_cancel_after_unknown_review_wait_gets_bounded_reconciliation_without_claiming_cancelled(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=plan(verification={"kind": "agent_judgment"}))
    original = complete_original(s, status="unknown")
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required" and s.runtime._enabled_run is None
    cancelling = s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-unknown-after-wait")
    assert cancelling["status"] == "cancel_requested" and s.runtime._enabled_run == s.run_id
    unsettled = s.runtime.tick(force=True)
    assert unsettled["status"] == "cancel_requested" and unsettled["history"] == []
    assert unsettled["pending"]["execution_request_id"] == original.command_id
    assert unsettled["wait_reason"] == "verification_required"
    assert s.runtime.tick(force=True) is None
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_target_change_stops_before_queue_or_execution(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    complete_original(s)
    s.target["process_create_time"] += 1
    result = s.runtime.tick(force=True)
    assert result["wait_reason"] == "result_unknown"
    assert "target_changed_before_dispatch" in result["wait"]["error"]["message"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    pending = result["pending"]
    with pytest.raises(ValueError, match="target_changed_before_execution"):
        s.runtime.admit(pending["execution_request_id"], pending["suggested_command"])


@pytest.mark.parametrize("kind", ["step", "select", "launch", "input_sequence", "learning_workflow"])
def test_one_plan_owner_blocks_competing_input(tmp_path, monkeypatch, kind):
    s = scene(tmp_path, monkeypatch)
    command = {"kind": kind, "request": {"action": "run"} if kind == "learning_workflow" else {}}
    with pytest.raises(ValueError, match="task_plan_run_active"):
        s.runtime.admit("other-input", command)
    pending = s.runtime.backend.status(s.run_id)["pending"]
    s.runtime.admit(pending["execution_request_id"], pending["suggested_command"])
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_owner_reopen_is_read_only_and_source_cannot_be_reclassified(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    other = TaskPlanRuntime(tmp_path, s.co, owner_id="owner-2", target_identity=lambda: TARGET, reviewed_runtime=s.reviewed)
    assert other.control({"action": "status", "run_id": s.run_id}, "other-status")["run_id"] == s.run_id
    for request in ({"action": "cancel", "run_id": s.run_id},
                    {"action": "continue", "run_id": s.run_id, "wait_id": s.first["wait"]["wait_id"]}):
        with pytest.raises(ValueError, match="owner_mismatch"):
            other.control(request, "other-control")
    path = s.runtime.backend._source_path(s.first["plan_id"])
    original = read_json_snapshot(path)
    write_json_snapshot(path, {**original, "source_kind": "reviewed_program"})
    with pytest.raises(ValueError, match="source_binding_mismatch"):
        s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_unknown_cancel_stops_ticks_and_preserves_pending_evidence(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s, status="unknown")
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-unknown")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancel_requested" and final["wait_reason"] == "verification_required"
    assert final["pending"]["execution_request_id"] == original.command_id
    assert s.runtime.tick(force=True) is None
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_queue_busy_cancel_creates_zero_input_original_fact(tmp_path, monkeypatch):
    (tmp_path / "commands").mkdir()
    write_json_snapshot(tmp_path / "commands" / "other-input.json", {"kind": "read_text", "max_chars": 100})
    s = scene(tmp_path, monkeypatch)
    assert s.first["wait_reason"] == "queue_busy"
    original_id = s.first["active_command_id"]
    assert not (tmp_path / "commands" / (original_id + ".json")).exists()
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-deferred")
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "cancelled"
    assert final["history"][0]["action_executed"] is False
    assert final["history"][0]["original_input_status"] == "failed"
    receipt = read_json_snapshot(tmp_path / "responses" / (original_id + ".json"))
    assert receipt["result"]["reason"] == "cancelled_before_submission"
    assert receipt["result"]["action_executed"] is False
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert not (tmp_path / "responses" / "other-input.json").exists()


def test_input_sequence_native_proof_wraps_original_final_search(tmp_path, monkeypatch):
    source = plan(count=1)
    source["inputs"]["query"] = "\u65b0\u5185\u5bb9"
    source["steps"][0]["action"] = {"kind": "input_sequence", "field_goal": "Search field", "text": {
        "source": "input", "name": "query"}, "clear_existing": True, "submit_search": True}
    s = scene(tmp_path, monkeypatch, source=source)
    original = complete_original(s)
    assert original.pending["suggested_command"]["request"]["text"] == "\u65b0\u5185\u5bb9"
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert final["history"][0]["execution_request_id"] == original.command_id


def test_read_text_requires_agent_review_and_keeps_original_observation(tmp_path, monkeypatch):
    source = plan(count=1, verification={"kind": "agent_judgment"})
    source["steps"][0]["action"] = {"kind": "read_text", "goal": "Observe result"}
    s = scene(tmp_path, monkeypatch, source=source)
    original = complete_original(s)
    original.receipt["result"].update(status="text_observed", contract_version="captured_text_v1", text="\u65b0\u5185\u5bb9")
    original.receipt["result"].pop("target_identity")
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required"
    s.runtime.control({"action": "review", "run_id": s.run_id, "execution_request_id": original.command_id,
                       "step_id": "step-0", "verdict": "success", "reason": "Read original observation",
                       "evidence_sha256": original.capture["sha256"]}, "read-review")
    final = s.runtime.control({"action": "continue", "run_id": s.run_id,
                              "wait_id": waiting["wait"]["wait_id"]}, "finish-read")
    assert final["runner_state"] == "completed" and final["outputs"] == {}
    assert final["history"][0]["action_executed"] is False


def test_fabricated_persisted_history_cannot_advance_shared_runner(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s)
    state = s.runtime.backend.status(s.run_id)
    state.update(pending=None, status="ready", current_step_id="step-1")
    state["history"].append({"step_id": "step-0", "execution_request_id": original.command_id,
                             "command_sha256": original.pending["command_sha256"], "verdict": "success"})
    write_json_snapshot(s.runtime.backend._path(s.run_id), state)
    with pytest.raises(ValueError, match="settlement_binding_invalid"):
        s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
