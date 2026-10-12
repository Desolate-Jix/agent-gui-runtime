"""取消只从原控制队列消费；Decision 返回后不能准备或派发未执行后缀。"""
import pytest

from app.core.instant_command_queue import enqueue_command
from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_cancellation import TaskPlanCancelPending
from app.instant_mcp import InstantCommand
from tests.test_task_plan_adaptive_review import OfflineAssessment, adaptive_plan, review_request
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import complete_original, scene


def queue_cancel(s, request_id="queued-plan-cancel", *, run_id=None):
    command = InstantCommand.model_validate({"kind": "task_plan", "request": {
        "action": "cancel", "run_id": run_id or s.run_id}}).command()
    enqueue_command(s.session, request_id, command)
    return command


def test_single_step_cancel_during_backend_authentication_preserves_original_ticket(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(count=1), decision=service)
    original = complete_original(s, native=False)
    validate = service.validate_result
    authentications = []
    def cancel_during_backend_authentication(value, **binding):
        authentications.append(binding)
        if len(authentications) == 2:
            queue_cancel(s)
        return validate(value, **binding)
    monkeypatch.setattr(service, "validate_result", cancel_during_backend_authentication)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == []
    assert waiting["pending"]["execution_request_id"] == original.command_id
    assert waiting["wait_reason"] == "verification_required"
    assert waiting["wait"]["error"]["message"] == "task_plan_cancel_pending:queued-plan-cancel"
    assert len(authentications) == 2
    assert not (tmp_path / "responses" / "queued-plan-cancel.json").exists()
    command = read_json_snapshot(tmp_path / "commands" / "queued-plan-cancel.json")
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["status"] == terminal["runner_state"] == "cancelled"
    assert len(terminal["history"]) == 1 and terminal["pending"] is None
    row = terminal["history"][0]
    assert row["execution_request_id"] == original.command_id and row["verdict"] == "cancelled"
    assert row["action_executed"] is True and row["original_input_status"] == "completed"
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2
    assert s.runtime.tick(force=True) is None


def test_single_step_cancel_during_backend_agent_review_preserves_original_ticket(tmp_path, monkeypatch):
    from app.execution import task_plan_backend as module
    service = OfflineAssessment()
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(count=1), decision=service)
    original = complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    validate = module.validate_review
    def cancel_during_backend_review(*args, **kwargs):
        packet = validate(*args, **kwargs)
        queue_cancel(s)
        return packet
    monkeypatch.setattr(module, "validate_review", cancel_during_backend_review)
    with pytest.raises(TaskPlanCancelPending, match="task_plan_cancel_pending:queued-plan-cancel"):
        s.runtime.control(review_request(s, waiting, original), "main-review-during-cancel")
    state = s.runtime.backend.status(s.run_id)
    assert state["history"] == [] and state["pending"]["execution_request_id"] == original.command_id
    assert not (tmp_path / "responses" / "queued-plan-cancel.json").exists()
    command = read_json_snapshot(tmp_path / "commands" / "queued-plan-cancel.json")
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["status"] == terminal["runner_state"] == "cancelled"
    assert len(terminal["history"]) == 1 and terminal["pending"] is None
    row = terminal["history"][0]
    assert row["execution_request_id"] == original.command_id and row["verdict"] == "cancelled"
    assert row["action_executed"] is True and row["original_input_status"] == "completed"
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2
    assert s.runtime.tick(force=True) is None


@pytest.mark.parametrize("version", ["task_plan.v1", "task_plan.v2"])
def test_settled_result_replay_stays_read_only_with_later_queued_cancel(tmp_path, monkeypatch, version):
    source = plan(count=1)
    source["schema_version"] = version
    s = scene(tmp_path, monkeypatch, source=source)
    original = complete_original(s)
    assert s.runtime.tick(force=True)["status"] == "completed"
    settled = s.runtime.backend.status(s.run_id)
    request_id = settled["history"][0]["verification_request_id"]
    queue_cancel(s)
    replayed = s.runtime.backend.record_verified_result(s.run_id, request_id, original.command_id,
        settled["verification_results"][request_id])
    assert replayed == settled == s.runtime.backend.status(s.run_id)
    assert len(replayed["history"]) == 1 and replayed["status"] == "completed"
    assert not (tmp_path / "responses" / "queued-plan-cancel.json").exists()
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


def test_cancel_enqueued_during_decision_retains_original_ticket_until_normal_control(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    service.during = lambda: queue_cancel(s)
    waiting = s.runtime.tick(force=True)
    state = s.runtime.backend.status(s.run_id)
    assert state["pending"]["execution_request_id"] == original.command_id
    assert state["history"] == [] and state["status"] != "cancel_requested"
    assert waiting["active_command_id"] == original.command_id
    assert len(service.calls) == 1
    assert sorted(path.stem for path in tmp_path.glob("commands/*.json")) == sorted([
        original.command_id, "queued-plan-cancel"])
    assert not (tmp_path / "responses" / "queued-plan-cancel.json").exists()
    command = read_json_snapshot(tmp_path / "commands" / "queued-plan-cancel.json")
    s.runtime.admit("queued-plan-cancel", command)
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["status"] == terminal["runner_state"] == "cancelled"
    assert terminal["pending"] is None and len(terminal["history"]) == 1
    row = terminal["history"][0]
    assert row["execution_request_id"] == original.command_id
    assert row["action_executed"] is True and row["original_input_status"] == "completed"
    assert row["verdict"] == "cancelled"
    for index in range(2):
        assert s.runtime.control({"action": "status", "run_id": s.run_id}, "cancel-status-" + str(index))["history"] == terminal["history"]
    assert s.runtime.tick(force=True) is None
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2


def test_already_queued_cancel_blocks_before_any_decision_request(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    queue_cancel(s)
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required"
    assert waiting["wait"]["error"]["message"] == "task_plan_cancel_pending:queued-plan-cancel"
    assert waiting["pending"]["execution_request_id"] == original.command_id
    assert waiting["history"] == [] and service.calls == []
    assert not (tmp_path / "responses" / "queued-plan-cancel.json").exists()


def test_another_runs_queued_cancel_does_not_cancel_or_block_current_verification(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    service.during = lambda: queue_cancel(s, run_id="trial-" + "f" * 64)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"][0]["execution_request_id"] == original.command_id
    assert waiting["history"][0]["verdict"] == "success"
    assert waiting["status"] == "pending" and waiting["wait_reason"] == "queue_busy"
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2


@pytest.mark.parametrize("malformed", ["broken_json", "unknown_input", "cancel_extra_field", "cancel_unknown_run_shape"])
def test_unconsumed_corrupt_or_unknown_envelope_fails_closed_without_settling_a(tmp_path, monkeypatch, malformed):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    def invalid_queue_entry():
        path = tmp_path / "commands" / "invalid-queued-control.json"
        if malformed == "broken_json":
            path.write_text("{broken", encoding="utf-8")
        else:
            command = {"kind": "task_plan", "request": {"action": "cancel", "run_id": s.run_id}}
            if malformed == "unknown_input":
                command = {"kind": "unknown_input"}
            elif malformed == "cancel_extra_field":
                command["request"]["authorizes_action"] = True
            else:
                command["request"]["run_id"] = "unknown-run"
            write_json_snapshot(path, command)
    service.during = invalid_queue_entry
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required"
    assert waiting["wait"]["error"]["message"].startswith("task_plan_queued_command_invalid:invalid-queued-control:")
    assert waiting["pending"]["execution_request_id"] == original.command_id
    assert waiting["history"] == [] and len(service.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert not (tmp_path / "responses" / "invalid-queued-control.json").exists()


def test_cancel_queued_after_settlement_before_dispatch_still_has_known_zero_suffix(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    record = s.runtime.backend.record_verified_result
    def queue_after_record(*args, **kwargs):
        result = record(*args, **kwargs)
        queue_cancel(s)
        return result
    monkeypatch.setattr(s.runtime.backend, "record_verified_result", queue_after_record)
    waiting = s.runtime.tick(force=True)
    suffix_id = waiting["pending"]["execution_request_id"]
    assert waiting["wait_reason"] == "queue_busy" and suffix_id != original.command_id
    assert waiting["wait"]["error"]["message"] == "task_plan_cancel_pending:queued-plan-cancel"
    assert not (tmp_path / "commands" / (suffix_id + ".json")).exists()
    monkeypatch.setattr(s.runtime.backend, "record_verified_result", record)
    command = read_json_snapshot(tmp_path / "commands" / "queued-plan-cancel.json")
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == terminal["status"] == "cancelled"
    assert [row["action_executed"] for row in terminal["history"]] == [True, False]
    assert terminal["history"][-1]["execution_request_id"] == suffix_id
    assert terminal["history"][-1]["original_input_status"] == "failed"
    receipt = read_json_snapshot(tmp_path / "responses" / (suffix_id + ".json"))
    assert receipt["result"]["action_executed"] is False
    assert receipt["result"]["reason"] == "cancelled_before_submission"
    assert len(service.calls) == 1 and s.runtime.tick(force=True) is None
