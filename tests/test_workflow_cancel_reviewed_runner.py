"""取消已审核的原票据，应立即解除调度占用且不派发下一步。"""
from copy import deepcopy

import pytest

from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import WORKFLOW, click_response, response, services


@pytest.mark.parametrize("verdict", ["success", "failure", "uncertain"])
def test_cancel_after_agent_review_closes_runner_without_continue(runtime_scene, verdict):
    runtime, trials, run, session, coordinator = runtime_scene
    run_id = run["run_id"]
    runtime.control({"action": "run", "run_id": run_id, "mode": "until_wait"}, "run-start")
    ticket = trials.status(run_id)["pending"]
    receipt_path = response(session, ticket)
    waiting = runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required"
    outputs = {"result_title": "reviewed result"} if verdict == "success" else {}
    reviewed = trials.review(run_id, "review-first", ticket["execution_request_id"], verdict,
                             {"results_visible": True}, outputs)
    assert reviewed["pending"] is None
    original_history = deepcopy(reviewed["history"])
    original_receipt = receipt_path.read_bytes()
    command_files = {path.name: path.read_bytes() for path in session.glob("commands/*.json")}

    cancelled = runtime.control({"action": "cancel", "run_id": run_id}, "cancel-reviewed")

    assert cancelled["status"] == cancelled["runner_state"] == "cancelled"
    assert cancelled["pending"] is None
    assert cancelled["wait"] is None
    assert cancelled["active_command_id"] is None
    assert cancelled["history"] == original_history
    assert cancelled["outputs"] == reviewed["outputs"]
    assert runtime.tick(force=True) is None
    runtime.admit("after-cancel", ticket["suggested_command"])
    assert runtime.runner._load(run_id)["steps_completed"] == 1
    assert runtime.control({"action": "cancel", "run_id": run_id}, "cancel-reviewed") == cancelled
    assert runtime.runner._load(run_id)["steps_completed"] == 1
    with pytest.raises(ValueError, match="cancel_conflict"):
        runtime.control({"action": "cancel", "run_id": run_id}, "different-cancel")
    reopened = type(runtime)(session, coordinator)
    assert reopened.control({"action": "status", "run_id": run_id}, "reopened-status")["runner_state"] == "cancelled"
    reopened.admit("after-reopen", ticket["suggested_command"])
    assert reopened.tick(force=True) is None
    assert receipt_path.read_bytes() == original_receipt
    assert {path.name: path.read_bytes() for path in session.glob("commands/*.json")} == command_files

    new_run = trials.start(WORKFLOW, run["program_id"], "search", {"query": "next"}, "next-start")
    next_snapshot = reopened.control({"action": "run", "run_id": new_run["run_id"],
                                      "mode": "until_wait"}, "next-run")
    assert next_snapshot["wait_reason"] == "execution_pending"
    assert next_snapshot["active_command_id"] != ticket["execution_request_id"]
    assert len(list(session.glob("commands/*.json"))) == 2


def test_cancel_without_review_keeps_original_ticket_and_input_gate(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    run_id = run["run_id"]
    runtime.control({"action": "run", "run_id": run_id, "mode": "until_wait"}, "run-start")
    ticket = trials.status(run_id)["pending"]
    response(session, ticket)
    assert runtime.tick(force=True)["wait_reason"] == "verification_required"

    cancelled = runtime.control({"action": "cancel", "run_id": run_id}, "cancel-unreviewed")

    assert cancelled["status"] == cancelled["runner_state"] == "cancel_requested"
    assert cancelled["pending"] == ticket
    assert cancelled["active_command_id"] == ticket["execution_request_id"]
    with pytest.raises(ValueError, match="workflow_run_active"):
        runtime.admit("competing", ticket["suggested_command"])
    assert len(list(session.glob("commands/*.json"))) == 1


def test_cancel_does_not_settle_a_different_reviewed_ticket(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    run_id = run["run_id"]
    runtime.control({"action": "run", "run_id": run_id, "mode": "until_wait"}, "run-start")
    ticket = trials.status(run_id)["pending"]
    response(session, ticket)
    assert runtime.tick(force=True)["wait_reason"] == "verification_required"
    trials.review(run_id, "review-first", ticket["execution_request_id"], "success",
                  {"results_visible": True}, {"result_title": "reviewed result"})
    next_ticket = trials.prepare(run_id, "external-prepare-next")
    click_response(session, next_ticket)
    trials.review(run_id, "external-review-next", next_ticket["execution_request_id"], "success", {}, {})

    cancelled = runtime.control({"action": "cancel", "run_id": run_id}, "cancel-other-ticket")

    assert cancelled["status"] == "cancelled"
    assert cancelled["runner_state"] == "cancel_requested"
    assert cancelled["active_command_id"] == ticket["execution_request_id"]
    assert cancelled["history"][-1]["execution_request_id"] == next_ticket["execution_request_id"]
    with pytest.raises(ValueError, match="workflow_run_active"):
        runtime.admit("competing", ticket["suggested_command"])
