"""连续工作流只向原 Instant 队列提交原票据，并回读真实持久回执。"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from app.core.json_snapshot import write_json_snapshot
from tests.test_workflow_trial import services, WORKFLOW, response, click_response


@pytest.fixture
def runtime_scene(services, monkeypatch):
    programs, trials, saved, session = services
    (session / "commands").mkdir(exist_ok=True)
    from app.learning_memory.workflow_runtime import WorkflowRuntime
    facade = SimpleNamespace(
        status_workflow_trial=lambda folder, run: trials.status(run),
        prepare_workflow_trial=lambda folder, run, request, **kw: trials.prepare(run, request, **kw),
        cancel_workflow_trial=lambda folder, run, request: trials.cancel(run, request),
        load_workflow_program=programs.load,
    )
    @contextmanager
    def workspace(root):
        yield facade
    monkeypatch.setattr("app.learning_memory.workflow_runner.MemoryWorkspace", workspace)
    co = SimpleNamespace(_memory_library_root=programs.library._workspace_root)
    monkeypatch.setattr("app.learning_memory.runtime_verification.verify_trial_step",
                        lambda *a, **kw: {"status": "verification_required"})
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "current"}, "start")
    runtime = WorkflowRuntime(session, co)
    return runtime, trials, run, session, co


def test_runtime_control_and_pump_use_original_queue_and_reviewed_results(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    assert not list(session.glob("commands/*.json"))
    request = {"action": "run", "run_id": run["run_id"], "mode": "until_wait"}
    first = runtime.control(request, "run-start")
    assert first["wait_reason"] == "execution_pending"
    ticket = trials.status(run["run_id"])["pending"]
    paths = list(session.glob("commands/*.json"))
    assert len(paths) == 1
    assert json.loads(paths[0].read_text(encoding="utf-8")) == ticket["suggested_command"]
    runtime.tick()
    assert len(list(session.glob("commands/*.json"))) == 1
    response(session, ticket)
    trials.review(run["run_id"], "review-one", ticket["execution_request_id"], "success",
                  {"results_visible": True}, {"result_title": "new result"})
    second = runtime.tick(force=True)
    assert second["wait_reason"] == "execution_pending"
    next_ticket = trials.status(run["run_id"])["pending"]
    assert next_ticket["step_id"] == "open"
    assert len(list(session.glob("commands/*.json"))) == 2
    click_response(session, next_ticket)
    trials.review(run["run_id"], "review-two", next_ticket["execution_request_id"], "success", {}, {})
    final = runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert len(list(session.glob("commands/*.json"))) == 2


def test_async_grounding_wait_uses_original_persisted_command_and_never_resubmits(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    command_id = ticket["execution_request_id"]
    initial = {"contract_version": "agent_command.v1", "command_id": command_id, "status": "running"}
    write_json_snapshot(session / "responses" / (command_id + ".json"),
                        {"status": "returned", "command": ticket["suggested_command"], "result": initial})
    current = {**initial, "status": "awaiting_grounding", "pending_grounding": {"request_id": "ground-new"}}
    (session / "agent-commands").mkdir()
    write_json_snapshot(session / "agent-commands" / (command_id + ".json"), current)
    waiting = runtime.tick(force=True)
    assert waiting["wait_reason"] == "grounding_required"
    assert waiting["wait"]["pending_grounding"] == {"request_id": "ground-new"}
    assert len(list(session.glob("commands/*.json"))) == 1
    runtime.control({"action": "continue", "run_id": run["run_id"],
                     "wait_id": waiting["wait"]["wait_id"]}, "continue-once")
    assert len(list(session.glob("commands/*.json"))) == 1


def test_runtime_reopening_and_status_never_restart_input(runtime_scene):
    runtime, trials, run, session, co = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    from app.learning_memory.workflow_runtime import WorkflowRuntime
    reopened = WorkflowRuntime(session, co)
    assert reopened.tick(force=True) is None
    assert reopened.control({"action": "status", "run_id": run["run_id"]}, "status")['pending']
    assert len(list(session.glob("commands/*.json"))) == 1


def test_failed_original_receipt_settles_without_agent_verification_or_replay(runtime_scene, monkeypatch):
    runtime, trials, run, session, co = runtime_scene
    @contextmanager
    def workspace(root):
        yield trials.programs.library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    runtime.runner.verify_step = lambda *args: pytest.fail("failed input must not request agent verification")
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-failed")
    ticket = trials.status(run["run_id"])["pending"]
    identity = ticket["execution_request_id"]
    write_json_snapshot(session / "responses" / (identity + ".json"), {
        "command": ticket["suggested_command"], "status": "failed",
        "error_type": "AgentCommandError", "error": "capability_unknown"})
    settled = runtime.tick(force=True)
    assert settled["runner_state"] == "failed" and settled["wait_reason"] is None
    assert settled["pending"] is None and settled["history"][-1]["action_executed"] is None
    assert settled["history"][-1]["error_type"] == "AgentCommandError"
    assert settled["history"][-1]["error"] == "capability_unknown"
    assert len(list(session.glob("commands/*.json"))) == 1
    reopened = type(runtime)(session, co)
    assert reopened.control({"action": "status", "run_id": run["run_id"]}, "read-failed")["runner_state"] == "failed"
    assert reopened.tick(force=True) is None
    assert len(list(session.glob("commands/*.json"))) == 1


def test_cancelled_failed_original_receipt_settles_without_replay(runtime_scene, monkeypatch):
    runtime, trials, run, session, _ = runtime_scene
    @contextmanager
    def workspace(root):
        yield trials.programs.library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    runtime.runner.verify_step = lambda *args: pytest.fail("failed input must not request agent verification")
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-cancel-failed")
    ticket = trials.status(run["run_id"])["pending"]
    identity = ticket["execution_request_id"]
    runtime.control({"action": "cancel", "run_id": run["run_id"]}, "cancel-failed")
    write_json_snapshot(session / "responses" / (identity + ".json"), {
        "command": ticket["suggested_command"], "status": "failed",
        "error_type": "AgentCommandError", "error": "capability_unknown"})
    settled = runtime.tick(force=True)
    assert settled["runner_state"] == "cancelled" and settled["pending"] is None
    assert settled["history"][-1]["action_executed"] is None
    assert settled["history"][-1]["error"] == "capability_unknown"
    assert len(list(session.glob("commands/*.json"))) == 1


def test_active_workflow_rejects_competing_input_and_allows_original_ticket(runtime_scene):
    runtime, trials, run, _, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    runtime.admit(ticket["execution_request_id"], ticket["suggested_command"])
    with pytest.raises(ValueError, match="workflow_run_active"):
        runtime.admit("unrelated", ticket["suggested_command"])
    runtime.admit("status", {"kind": "learning_workflow", "request": {"action": "status", "run_id": run["run_id"]}})
    runtime.admit("close", {"kind": "close"})


def test_run_and_continue_are_live_only_closed_control_contracts():
    from app.instant_mcp import InstantCommand
    from app.learning_memory.workflow_control import workflow_control
    request = {"action": "run", "run_id": "trial-" + "a" * 64, "mode": "single"}
    command = {"kind": "learning_workflow", "request": request}
    assert InstantCommand.model_validate(command).command() == command
    with pytest.raises(ValueError, match="live_host"):
        workflow_control(None, None, request, "offline")
    with pytest.raises(ValueError):
        InstantCommand.model_validate({**command, "request": {**request, "bindings": {}}}).command()


def test_queued_status_defers_original_ticket_then_submits_once(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    status = {"kind": "learning_workflow", "request": {"action": "status", "run_id": run["run_id"]}}
    write_json_snapshot(session / "commands" / "status-racing.json", status)
    waiting = runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    assert waiting["wait_reason"] == "queue_busy"
    ticket = trials.status(run["run_id"])["pending"]
    original_id = ticket["execution_request_id"]
    assert not (session / "commands" / (original_id + ".json")).exists()
    write_json_snapshot(session / "responses" / "status-racing.json", {"command": status, "status": "returned"})
    resumed = runtime.tick(force=True)
    assert resumed["wait_reason"] == "execution_pending"
    assert resumed["active_command_id"] == original_id
    assert json.loads((session / "commands" / (original_id + ".json")).read_text(encoding="utf-8")) == ticket["suggested_command"]
    runtime.tick(force=True)
    assert len(list(session.glob("commands/*.json"))) == 2


def test_cancel_from_verification_wait_reconciles_without_manual_continue(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    response(session, ticket)
    waiting = runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required"
    runtime.runner.verify_step = lambda rid, req, eid: trials.record_cancelled_execution(rid, req, eid)
    runtime.control({"action": "cancel", "run_id": run["run_id"]}, "cancel-now")
    final = runtime.tick(force=True)
    assert final is not None and final["runner_state"] == "cancelled"
    assert final["history"][-1]["judged_by"] == "runtime"
    assert final["outputs"] == {} and final["pending"] is None
    assert len(list(session.glob("commands/*.json"))) == 1


def test_cancel_before_queue_submission_records_no_input_and_never_dispatches(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    write_json_snapshot(session / "commands" / "status-racing.json", {"kind": "capture"})
    waiting = runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    assert waiting["wait_reason"] == "queue_busy"
    original_id = waiting["active_command_id"]
    runtime.runner.verify_step = lambda rid, req, eid: trials.record_cancelled_execution(rid, req, eid)
    cancelled = runtime.control({"action": "cancel", "run_id": run["run_id"]}, "cancel-before-submit")
    final = runtime.tick(force=True)
    assert final["runner_state"] == "cancelled"
    assert final["history"][-1]["action_executed"] is False
    receipt = json.loads((session / "responses" / (original_id + ".json")).read_text(encoding="utf-8"))
    assert receipt["result"]["reason"] == "cancelled_before_submission"
    assert cancelled["status"] in {"cancel_requested", "cancelled"}
    assert len(list(session.glob("commands/*.json"))) == 2


def api_attempt_receipt(session, ticket, *, status="success", usage=None):
    command_id = ticket["execution_request_id"]
    initial = {"contract_version": "agent_command.v1", "command_id": command_id, "status": "running"}
    write_json_snapshot(session / "responses" / (command_id + ".json"),
                        {"status": "returned", "command": ticket["suggested_command"], "result": initial})
    current = {**initial, "status": "running", "recognition_calls": [{
        "source": "external_api", "request_id": "ag-current", "capture_id": "capture-current",
        "attempt": {"started_ns": 10, "ended_ns": 30, "status": status, "usage": usage}}]}
    (session / "agent-commands").mkdir(exist_ok=True)
    write_json_snapshot(session / "agent-commands" / (command_id + ".json"), current)
    return current


@pytest.mark.parametrize("status", ["success", "failure", "timeout"])
def test_api_attempt_metrics_follow_original_run_ticket_once(runtime_scene, status):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    api_attempt_receipt(session, ticket, status=status)
    for index in range(2):
        snapshot = runtime.control({"action": "status", "run_id": run["run_id"]}, "status-" + str(index))
        metrics = snapshot["metrics"]
        assert metrics["observed"]["model_calls"]["grounding"] == 1
        assert metrics["observed"]["status_counts"] == {status: 1}
        assert metrics["observed"]["phase_elapsed_ns"]["grounding"] == 20
        assert metrics["observed"]["usage"] is None
        assert metrics["total_model_calls"] is None
        assert len(list(session.glob("commands/*.json"))) == 1
    from app.learning_memory.measurement import load_events
    events = load_events(session, run["run_id"])
    assert len(events) == 1 and events[0]["step_id"] == ticket["step_id"]
    assert events[0]["evidence_refs"] == ["agent-commands/" + ticket["execution_request_id"] + ".json"]


def test_reviewed_history_still_accounts_for_original_api_attempt(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    current = api_attempt_receipt(session, ticket, usage={"input_tokens": 7, "output_tokens": 3})
    # 测试用终态回执来自原任务，审核可先于调度器下一次回读。
    current.update(status="completed", action_executed=True,
                   result={"contract_version": "input_sequence_v1", "status": "completed", "action_executed": True})
    write_json_snapshot(session / "agent-commands" / (ticket["execution_request_id"] + ".json"), current)
    trials.review(run["run_id"], "review-one", ticket["execution_request_id"], "success",
                  {"results_visible": True}, {"result_title": "new result"})
    snapshot = runtime.tick(force=True)
    assert snapshot["pending"]["step_id"] == "open"
    assert snapshot["metrics"]["observed"]["model_calls"]["grounding"] == 1
    assert snapshot["metrics"]["observed"]["usage"]["total_tokens"] == 10


def test_bad_measurement_does_not_hide_pending_execution_or_resubmit(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    first = runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    path = session / "measurements" / run["run_id"] / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{broken log')
    snapshot = runtime.control({"action": "status", "run_id": run["run_id"]}, "read-state")
    assert snapshot["pending"] == first["pending"]
    assert snapshot["wait_reason"] == "execution_pending"
    assert snapshot["metrics"]["status"] == "unavailable"
    assert snapshot["metrics"]["observed"] is None
    assert len(list(session.glob("commands/*.json"))) == 1
    assert path.read_bytes() == b'{broken log'


@pytest.mark.parametrize("drift", ["command", "identity"])
def test_api_metrics_reject_unbound_evidence_but_keep_execution_status(runtime_scene, drift):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-start")
    ticket = trials.status(run["run_id"])["pending"]
    current = api_attempt_receipt(session, ticket)
    command_id = ticket["execution_request_id"]
    if drift == "identity":
        current["command_id"] = "unrelated-command"
        write_json_snapshot(session / "agent-commands" / (command_id + ".json"), current)
    else:
        write_json_snapshot(session / "commands" / (command_id + ".json"), {"kind": "capture"})
    snapshot = runtime.control({"action": "status", "run_id": run["run_id"]}, "read-state")
    assert snapshot["pending"]["execution_request_id"] == command_id
    assert snapshot["metrics"]["status"] == "unavailable"
    assert snapshot["metrics"]["observed"] is None
    assert not list(session.glob("measurements/*/events.jsonl"))
