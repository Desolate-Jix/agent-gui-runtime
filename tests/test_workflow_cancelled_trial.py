import hashlib
import json

import pytest

from test_workflow_trial import WORKFLOW, services


def write_async_receipt(session, ticket, *, terminal_status=None, action_executed=None, command=None):
    identity = ticket["execution_request_id"]
    (session / "commands").mkdir(exist_ok=True)
    (session / "commands" / (identity + ".json")).write_text(
        json.dumps(command or ticket["suggested_command"]), encoding="utf-8")
    receipt = {"status": "returned", "command": ticket["suggested_command"],
               "result": {"contract_version": "agent_command.v1", "command_id": identity, "status": "running"}}
    response_path = session / "responses" / (identity + ".json")
    response_path.write_text(json.dumps(receipt), encoding="utf-8")
    if terminal_status is not None:
        (session / "agent-commands").mkdir(exist_ok=True)
        result = {"contract_version": "input_sequence_v1", "status": terminal_status}
        if action_executed is not None:
            result["action_executed"] = action_executed
        (session / "agent-commands" / (identity + ".json")).write_text(json.dumps({
            "contract_version": "agent_command.v1", "command_id": identity,
            "status": terminal_status, "result": result}), encoding="utf-8")
    return response_path


@pytest.mark.parametrize("terminal_status,action_executed", [
    ("cancelled", False), ("cancelled", True), ("failed", None), ("completed", True)])
def test_cancelled_execution_settles_with_actual_terminal_evidence(services, terminal_status, action_executed):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start-cancel")
    ticket = trials.prepare(run["run_id"], "prepare-cancel")
    trials.cancel(run["run_id"], "cancel-request")
    receipt = write_async_receipt(session, ticket, terminal_status=terminal_status,
                                  action_executed=action_executed)
    result = trials.record_cancelled_execution(run["run_id"], "settle-cancel", ticket["execution_request_id"])
    assert result["status"] == "cancelled" and result["pending"] is None
    assert result["outputs"] == {}
    entry = result["history"][-1]
    assert entry["verdict"] == "uncertain" and entry["judged_by"] == "runtime"
    assert entry["runtime_verdict"] == "uncertain" and entry["action_executed"] is action_executed
    assert entry["receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert entry["terminal_receipt"]["status"] == terminal_status
    assert trials.record_cancelled_execution(run["run_id"], "settle-cancel", ticket["execution_request_id"]) == result
    next_run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "B"}, "next-run")
    assert next_run["run_id"] != run["run_id"]


def test_cancelled_execution_rejects_pending_or_mismatched_receipts(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start-cancel")
    ticket = trials.prepare(run["run_id"], "prepare-cancel")
    with pytest.raises(ValueError, match="cancel_requested"):
        trials.record_cancelled_execution(run["run_id"], "settle-early", ticket["execution_request_id"])
    trials.cancel(run["run_id"], "cancel-request")
    with pytest.raises(ValueError, match="receipt"):
        trials.record_cancelled_execution(run["run_id"], "settle-missing", ticket["execution_request_id"])
    write_async_receipt(session, ticket)
    with pytest.raises(ValueError, match="not_terminal"):
        trials.record_cancelled_execution(run["run_id"], "settle-running", ticket["execution_request_id"])
    write_async_receipt(session, ticket, terminal_status="awaiting_grounding")
    with pytest.raises(ValueError, match="not_terminal"):
        trials.record_cancelled_execution(run["run_id"], "settle-awaiting", ticket["execution_request_id"])
    write_async_receipt(session, ticket, terminal_status="cancelled", action_executed=False,
                        command={"kind": "read_text", "max_chars": 10000})
    with pytest.raises(ValueError, match="command_mismatch"):
        trials.record_cancelled_execution(run["run_id"], "settle-mismatch", ticket["execution_request_id"])
    assert trials.status(run["run_id"])["pending"] is not None


def test_conflicting_terminal_execution_flags_remain_unknown(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start-cancel")
    ticket = trials.prepare(run["run_id"], "prepare-cancel")
    trials.cancel(run["run_id"], "cancel-request")
    write_async_receipt(session, ticket, terminal_status="cancelled", action_executed=False)
    path = session / "agent-commands" / (ticket["execution_request_id"] + ".json")
    terminal = json.loads(path.read_text(encoding="utf-8"))
    terminal["action_executed"] = True
    path.write_text(json.dumps(terminal), encoding="utf-8")
    result = trials.record_cancelled_execution(run["run_id"], "settle-cancel", ticket["execution_request_id"])
    assert result["history"][-1]["action_executed"] is None


def test_cancelled_original_failed_receipt_without_result_retains_error_and_unknown_input(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start-cancel-failed")
    ticket = trials.prepare(run["run_id"], "prepare-cancel-failed")
    identity = ticket["execution_request_id"]
    trials.cancel(run["run_id"], "cancel-failed")
    (session / "commands").mkdir(exist_ok=True)
    (session / "commands" / (identity + ".json")).write_text(
        json.dumps(ticket["suggested_command"]), encoding="utf-8")
    (session / "responses" / (identity + ".json")).write_text(json.dumps({
        "command": ticket["suggested_command"], "status": "failed",
        "error_type": "AgentCommandError", "error": "capability_unknown"}), encoding="utf-8")
    settled = trials.record_cancelled_execution(run["run_id"], "settle-cancel-failed", identity)
    assert settled["status"] == "cancelled" and settled["pending"] is None
    assert settled["history"][-1]["action_executed"] is None
    assert settled["history"][-1]["error_type"] == "AgentCommandError"
    assert settled["history"][-1]["error"] == "capability_unknown"
