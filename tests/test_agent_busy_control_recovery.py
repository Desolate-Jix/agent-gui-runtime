"""忙碌拒绝只结算当前请求；原输入仍须独立证明终态。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.run_local_step_session import (
    AgentCommandAdmissionError, check_agent_command_admission,
    preserve_input_admission_rejection,
)
from tests.test_session_input_terminal import inspect, job, save


GATED = [
    {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Find"}},
    {"kind": "desktop_click", "request": {"goal": "Find"}},
    {"kind": "input_sequence", "request": {}},
    {"kind": "form_fill", "request": {}},
    {"kind": "capture"},
    {"kind": "discover"},
    {"kind": "select", "handle": 123, "process_id": 321},
    {"kind": "learning_start", "request": {"scope": "workflow"}},
    {"kind": "learning_workflow", "request": {"action": "run", "run_id": "trial-current", "mode": "until_wait"}},
    {"kind": "learning_workflow", "request": {"action": "prepare", "run_id": "trial-current"}},
    {"kind": "learning_workflow", "request": {"action": "read", "workflow_id": "workflow-current"}},
]

SAFE = [
    {"kind": "close"},
    {"kind": "agent_command_status", "request": {"command_id": "input"}},
    {"kind": "grounding_status", "request": {"grounding_request_id": "ground"}},
    *[{"kind": "learning_workflow", "request": {"action": action}} for action in
      ("status", "cancel", "continue", "review", "verify", "takeover_preview", "takeover_commit")],
]


def rejected(root, command):
    with pytest.raises(AgentCommandAdmissionError) as caught:
        check_agent_command_admission(SimpleNamespace(active=True), command["kind"], command)
    response = {"command": command, "status": "failed",
                "error_type": type(caught.value).__name__, "error": str(caught.value)}
    preserve_input_admission_rejection(response, caught.value, "rejected")
    save(root, "commands", "rejected", command)
    save(root, "responses", "rejected", response)
    return response


@pytest.mark.parametrize("command", GATED, ids=lambda command: command["kind"] + "-" + command.get("request", {}).get("action", ""))
def test_real_busy_gate_rejection_is_known_zero_input(tmp_path, command):
    root = tmp_path / "session"
    rejected(root, command)
    before = {str(path): path.read_bytes() for path in root.rglob("*.json")}
    result = inspect(root)
    assert result["commands"]["rejected"] == {
        "kind": command["kind"], "terminal_status": "failed", "action_executed": False}
    assert before == {str(path): path.read_bytes() for path in root.rglob("*.json")}
    assert not (root / "agent-commands").exists()


@pytest.mark.parametrize("command", SAFE, ids=lambda command: command["kind"] + "-" + command.get("request", {}).get("action", ""))
def test_allowed_controls_cannot_fabricate_a_busy_rejection(tmp_path, command):
    root = tmp_path / "session"
    check_agent_command_admission(SimpleNamespace(active=True), command["kind"], command)
    error = AgentCommandAdmissionError()
    response = {"command": command, "status": "failed", "error_type": type(error).__name__,
                "error": str(error), "result": error.before_dispatch_result("rejected")}
    save(root, "commands", "rejected", command)
    save(root, "responses", "rejected", response)
    with pytest.raises(ValueError, match="session_input_admission_rejection_unproven"):
        inspect(root)


@pytest.mark.parametrize("change", ("binding", "worker", "action", "attempted", "legacy", "exception", "unknown_kind"))
def test_workflow_busy_proof_must_remain_exact(tmp_path, change):
    root = tmp_path / "session"
    command = deepcopy(GATED[8])
    response = rejected(root, command)
    if change == "binding":
        response["command"] = GATED[9]
    elif change == "worker":
        save(root, "agent-commands", "rejected", {"command_id": "rejected"})
    elif change == "action":
        response["result"]["action_executed"] = True
    elif change == "attempted":
        response["result"]["input_attempted"] = None
    elif change == "legacy":
        response.pop("result")
    elif change == "exception":
        response["error_type"] = "ValueError"
    else:
        command["kind"] = "future_kind"
        response["command"] = command
        save(root, "commands", "rejected", command)
    save(root, "responses", "rejected", response)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(root)


def test_rejected_workflow_does_not_settle_original_active_input(tmp_path):
    root = tmp_path / "session"
    _, worker = job(root)
    worker["status"] = "running"
    save(root, "agent-commands", "input", worker)
    rejected(root, deepcopy(GATED[8]))
    with pytest.raises(ValueError, match="session_input_"):
        inspect(root)
