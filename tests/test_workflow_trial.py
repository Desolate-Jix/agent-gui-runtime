"""原始回执、局部变量和版本隔离的试运行契约。"""
from copy import deepcopy
import json
import hashlib
from pathlib import Path

import pytest

from app.learning_memory.workflow_program import WorkflowProgramService
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_trial import _command


WORKFLOW = "workflow-" + "a" * 64
SNAPSHOT = "workflow-project-snapshot-" + "b" * 64


class Library:
    def __init__(self, root):
        self._workspace_root = Path(root)


@pytest.fixture
def services(tmp_path, monkeypatch):
    memory = {"snapshot_id": SNAPSHOT, "graph": {"workflow": {"goal": "搜索"},
        "nodes": [{"node_id": "home"}, {"node_id": "results"}], "edges": []}}
    monkeypatch.setattr("app.learning_memory.workflow_program.read_project",
                        lambda library, workflow_id, snapshot_id=None: deepcopy(memory))
    library = Library(tmp_path / "library")
    programs = WorkflowProgramService(library)
    draft = programs.load(WORKFLOW)
    definition = {"title": "搜索", "inputs": [{"name": "query", "type": "text", "required": True}], "outputs": [],
        "steps": [{"step_id": "search", "title": "搜索", "source_node_id": "home", "target_node_id": "results",
            "action": {"kind": "input_sequence", "field_goal": "搜索框", "text": {"source": "input", "name": "query"},
                       "clear_existing": True, "submit_search": True},
            "preconditions": [], "success_conditions": [{"left": {"source": "observation", "name": "results_visible"}, "operator": "agent_assertion"}],
            "branches": {"success": "open", "failure": None, "uncertain": None},
            "outputs": [{"name": "result_title", "type": "text"}], "review_status": "reviewed", "provenance": "manual"},
            {"step_id": "open", "title": "打开结果", "source_node_id": "results", "target_node_id": None,
             "action": {"kind": "click", "goal": "打开结果"},
             "preconditions": [{"left": {"source": "output", "step_id": "search", "name": "result_title"}, "operator": "exists"}],
             "success_conditions": [], "branches": {"success": None, "failure": None, "uncertain": None},
             "outputs": [], "review_status": "pending", "provenance": "manual"}]}
    saved = programs.save(WORKFLOW, draft["content_sha256"], definition, "save-one")
    session = tmp_path / "session"
    (session / "responses").mkdir(parents=True)
    return programs, TrialService(library, session), saved, session


def response(session, ticket, *, command=None, status="completed", action_executed=True):
    result = {"contract_version": "input_sequence_v1", "status": status, "action_executed": action_executed}
    path = session / "responses" / (ticket["execution_request_id"] + ".json")
    commands = session / "commands"
    commands.mkdir(exist_ok=True)
    (commands / path.name).write_text(json.dumps(ticket["suggested_command"]), encoding="utf-8")
    path.write_text(json.dumps({"status": "returned", "command": command or ticket["suggested_command"], "result": result}), encoding="utf-8")
    return path


def click_response(session, ticket):
    path = session / "responses" / (ticket["execution_request_id"] + ".json")
    commands = session / "commands"
    commands.mkdir(exist_ok=True)
    (commands / path.name).write_text(json.dumps(ticket["suggested_command"]), encoding="utf-8")
    path.write_text(json.dumps({"status": "returned", "command": ticket["suggested_command"],
        "result": {"contract_version": "local_direct_step_v1", "phase": "returned",
                   "response": {"success": True, "data": {"execution_path": {"action_executed": True}}}}}), encoding="utf-8")


def test_command_compilation_retains_target_reference_and_new_input():
    reference = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
    click = {"action": {"kind": "click", "goal": "打开", "target_memory": reference}}
    assert _command(click, {}, {})["request"]["target_memory"] == reference
    entry = {"action": {"kind": "input_sequence", "field_goal": "搜索", "text": {"source": "input", "name": "query"},
                        "clear_existing": True, "submit_search": False, "target_memory": reference}}
    command = _command(entry, {"query": "另一个词"}, {})
    assert command["request"]["text"] == "另一个词"
    assert command["request"]["target_memory"] == reference


def test_changed_command_and_one_pending_ticket(services):
    programs, trials, saved, _ = services
    from app.instant_mcp import InstantCommand
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "新的地点"}, "start")
    assert trials.start(WORKFLOW, saved["program_id"], "search", {"query": "新的地点"}, "start") == run
    ticket = trials.prepare(run["run_id"], "prepare")
    assert ticket["suggested_command"]["request"]["text"] == "新的地点"
    assert InstantCommand.model_validate(ticket["suggested_command"]).command() == ticket["suggested_command"]
    assert trials.prepare(run["run_id"], "another") == ticket
    assert len(list((trials.session / "responses").glob("*.json"))) == 0


def test_vision_capabilities_are_part_of_exact_command(services):
    _, trials, saved, _ = services
    from app.instant_mcp import InstantCommand
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "caps")
    capabilities = {"image_transport": "supported", "current_vision": "supported"}
    ticket = trials.prepare(run["run_id"], "prepare-caps", vision_capabilities=capabilities)
    command = ticket["suggested_command"]
    assert command["vision_capabilities"]["image_transport"] == "supported"
    assert InstantCommand.model_validate(command).command() == command


def test_legacy_pending_without_prepare_index_keeps_same_ticket(services):
    _, trials, saved, _ = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "legacy")
    original = trials.prepare(run["run_id"], "first")
    path = trials._path(run["run_id"])
    old = json.loads(path.read_text(encoding="utf-8"))
    old.pop("prepare_requests")
    path.write_text(json.dumps(old), encoding="utf-8")
    reused = trials.prepare(run["run_id"], "recovered")
    assert reused == original
    assert trials.status(run["run_id"])["pending"]["execution_request_id"] == original["execution_request_id"]
    assert trials.status(run["run_id"])["prepare_requests"]["recovered"]["result"] == original


def test_unknown_mismatch_and_failed_receipt_keep_pending(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    args = (run["run_id"], "review", ticket["execution_request_id"], "success", {"results_visible": True}, {"result_title": "A"})
    with pytest.raises(ValueError, match="receipt_missing"):
        trials.review(*args)
    path = response(session, ticket, command={"kind": "capture"})
    with pytest.raises(ValueError, match="command_mismatch"):
        trials.review(*args)
    response(session, ticket, status="running")
    with pytest.raises(ValueError, match="not_terminal"):
        trials.review(*args)
    response(session, ticket, status="interrupted", action_executed=False)
    with pytest.raises(ValueError, match="input_not_succeeded"):
        trials.review(*args)
    assert trials.status(run["run_id"])["pending"]["execution_request_id"] == ticket["execution_request_id"]
    assert path.exists()


def test_original_failed_receipt_without_result_settles_failure_with_unknown_input(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start-failed-original")
    ticket = trials.prepare(run["run_id"], "prepare-failed-original")
    identity = ticket["execution_request_id"]
    (session / "commands").mkdir(exist_ok=True)
    (session / "commands" / (identity + ".json")).write_text(
        json.dumps(ticket["suggested_command"]), encoding="utf-8")
    receipt = {"command": ticket["suggested_command"], "status": "failed",
               "error_type": "AgentCommandError", "error": "capability_unknown"}
    path = session / "responses" / (identity + ".json")
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="input_not_succeeded"):
        trials.review(run["run_id"], "review-failed-as-success", identity, "success",
                      {"results_visible": True}, {"result_title": "A"})
    settled = trials.record_failed_execution(run["run_id"], "settle-failed-original", identity)
    assert settled["status"] == "failed" and settled["pending"] is None
    assert settled["history"][-1]["verdict"] == "failure"
    assert settled["history"][-1]["action_executed"] is None
    assert settled["history"][-1]["error_type"] == "AgentCommandError"
    assert settled["history"][-1]["error"] == "capability_unknown"
    assert trials.record_failed_execution(run["run_id"], "settle-failed-original", identity) == settled


def test_original_failed_receipt_rejects_wrong_command(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start-failed-mismatch")
    ticket = trials.prepare(run["run_id"], "prepare-failed-mismatch")
    identity = ticket["execution_request_id"]
    (session / "commands").mkdir(exist_ok=True)
    (session / "commands" / (identity + ".json")).write_text(
        json.dumps({"kind": "read_text", "max_chars": 10000}), encoding="utf-8")
    (session / "responses" / (identity + ".json")).write_text(json.dumps({
        "command": ticket["suggested_command"], "status": "failed",
        "error_type": "AgentCommandError", "error": "capability_unknown"}), encoding="utf-8")
    with pytest.raises(ValueError, match="command_mismatch"):
        trials.record_failed_execution(run["run_id"], "settle-failed-mismatch", identity)
    assert trials.status(run["run_id"])["pending"] is not None


def test_success_branch_output_is_run_local_and_new_program_has_no_validation(services):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    response(session, ticket)
    advanced = trials.review(run["run_id"], "review", ticket["execution_request_id"], "success",
                             {"results_visible": True}, {"result_title": "A result"})
    assert advanced["current_step_id"] == "open" and advanced["status"] == "ready"
    assert advanced["history"][0]["judged_by"] == "agent"
    assert trials.prepare(run["run_id"], "prepare") == ticket
    assert trials.status(run["run_id"])["pending"] is None
    assert trials.review(run["run_id"], "review", ticket["execution_request_id"], "success",
                         {"results_visible": True}, {"result_title": "A result"}) == advanced
    fresh = trials.start(WORKFLOW, saved["program_id"], "open", {"query": "A"}, "partial")
    assert trials.prepare(fresh["run_id"], "missing")["reason"] == "precondition_missing_output"
    assert trials.status(fresh["run_id"])["status"] == "blocked"
    assert trials.status(fresh["run_id"])["reason"] == "precondition_missing_output"
    next_ticket = trials.prepare(run["run_id"], "next")
    assert next_ticket["suggested_command"]["request"]["goal"] == "打开结果"
    assert next_ticket["execution_request_id"] != ticket["execution_request_id"]
    assert trials.prepare(run["run_id"], "prepare") == ticket
    assert trials.status(run["run_id"])["pending"]["execution_request_id"] == next_ticket["execution_request_id"]
    with pytest.raises(ValueError, match="idempotency_conflict"):
        trials.prepare(run["run_id"], "prepare", observations={"new": True})
    with pytest.raises(ValueError, match="unresolved_execution"):
        trials.start(WORKFLOW, saved["program_id"], "open", {"query": "A"}, "while-pending")
    click_response(session, next_ticket)
    completed = trials.review(run["run_id"], "review-next", next_ticket["execution_request_id"], "success", {}, {})
    assert completed["status"] == "completed" and completed["current_step_id"] is None
    assert len(completed["history"]) == 2
    assert trials.prepare(run["run_id"], "prepare") == ticket
    assert trials.prepare(run["run_id"], "next") == next_ticket
    assert trials.status(run["run_id"]) == completed
    definition = deepcopy(saved["definition"])
    definition["steps"][1]["action"]["goal"] = "修改后的目标"
    newer = programs.save(WORKFLOW, saved["content_sha256"], definition, "save-two")
    new_run = trials.start(WORKFLOW, newer["program_id"], "open", {"query": "A"}, "new-version")
    assert new_run["history"] == [] and new_run["outputs"] == {}
    assert trials.prepare(new_run["run_id"], "missing-new")["status"] == "blocked"
    assert trials.status(run["run_id"])["program_id"] == saved["program_id"]


def test_uncertain_condition_pauses_and_failure_branch_does_not_pass(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    response(session, ticket)
    state = trials.review(run["run_id"], "review", ticket["execution_request_id"], "success", {}, {"result_title": "A"})
    assert state["status"] == "paused_uncertain" and state["history"][0]["verdict"] == "uncertain"
    assert state["outputs"] == {}
    with pytest.raises(ValueError, match="not_preparable"):
        trials.prepare(run["run_id"], "again")
    second = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "B"}, "start-b")
    second_ticket = trials.prepare(second["run_id"], "prepare-b")
    response(session, second_ticket, status="interrupted", action_executed=False)
    failed = trials.review(second["run_id"], "review-b", second_ticket["execution_request_id"], "failure", {}, {})
    assert failed["status"] == "failed" and failed["history"][0]["verdict"] == "failure"


def test_false_success_condition_takes_failure_branch(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "false-condition")
    ticket = trials.prepare(run["run_id"], "prepare-false")
    response(session, ticket)
    state = trials.review(run["run_id"], "review-false", ticket["execution_request_id"], "success",
                          {"results_visible": False}, {"result_title": "A"})
    assert state["status"] == "failed" and state["history"][0]["condition_result"] == "false"


def test_async_terminal_required_and_bound_to_original_receipt(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "async")
    ticket = trials.prepare(run["run_id"], "prepare-async")
    identifier = ticket["execution_request_id"]
    receipt = {"status": "returned", "command": ticket["suggested_command"],
        "result": {"contract_version": "agent_command.v1", "command_id": identifier, "status": "running"}}
    path = session / "responses" / (identifier + ".json")
    commands = session / "commands"
    commands.mkdir(exist_ok=True)
    (commands / path.name).write_text(json.dumps(ticket["suggested_command"]), encoding="utf-8")
    path.write_text(json.dumps(receipt), encoding="utf-8")
    args = (run["run_id"], "review-async", identifier, "success", {"results_visible": True}, {"result_title": "A"})
    with pytest.raises(ValueError, match="not_terminal"):
        trials.review(*args)
    terminal_path = session / "agent-commands" / (identifier + ".json")
    terminal_path.parent.mkdir()
    terminal_path.write_text(json.dumps({"contract_version": "agent_command.v1", "command_id": identifier,
        "status": "completed", "result": {"contract_version": "input_sequence_v1", "status": "completed", "action_executed": True}}), encoding="utf-8")
    state = trials.review(*args)
    assert state["history"][0]["receipt_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert state["history"][0]["terminal_receipt"]["status"] == "completed"
    assert state["history"][0]["terminal_receipt"]["sha256"]


def test_cancel_pending_preserves_ticket_and_does_not_resume_branch(services):
    _, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "A"}, "cancel")
    ticket = trials.prepare(run["run_id"], "prepare-cancel")
    cancelled = trials.cancel(run["run_id"], "cancel-request")
    assert cancelled["status"] == "cancel_requested" and cancelled["pending"] is not None
    with pytest.raises(ValueError, match="unresolved_execution"):
        trials.start(WORKFLOW, saved["program_id"], "search", {"query": "B"}, "another")
    response(session, ticket)
    state = trials.review(run["run_id"], "review-cancel", ticket["execution_request_id"], "success",
                          {"results_visible": True}, {"result_title": "A"})
    assert state["status"] == "cancelled" and state["current_step_id"] == "open"
    with pytest.raises(ValueError, match="not_preparable"):
        trials.prepare(run["run_id"], "after-cancel")


def test_agent_read_uses_verified_original_image_and_never_claims_input(services):
    programs, trials, saved, session = services
    definition = deepcopy(saved["definition"])
    definition["steps"][1]["action"] = {"kind": "read_text", "goal": "读取结果"}
    definition["steps"][1]["preconditions"] = []
    newer = programs.save(WORKFLOW, saved["content_sha256"], definition, "read-version")
    run = trials.start(WORKFLOW, newer["program_id"], "open", {"query": "A"}, "read")
    ticket = trials.prepare(run["run_id"], "prepare-read")
    assert ticket["suggested_command"] == {"kind": "read_text", "max_chars": 10000}
    image = session / "read.png"
    from PIL import Image
    Image.new("RGB", (4, 3), "white").save(image)
    receipt = {"status": "returned", "command": ticket["suggested_command"],
        "result": {"status": "agent_read_required", "text": None, "action_executed": False},
        "observation": {"image_path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "capture_id": "fresh"}}
    path = session / "responses" / (ticket["execution_request_id"] + ".json")
    commands = session / "commands"
    commands.mkdir(exist_ok=True)
    (commands / path.name).write_text(json.dumps(ticket["suggested_command"]), encoding="utf-8")
    path.write_text(json.dumps(receipt), encoding="utf-8")
    original = image.read_bytes()
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="read_observation_invalid"):
        trials.review(run["run_id"], "review-read", ticket["execution_request_id"], "success", {}, {})
    image.write_bytes(original)
    state = trials.review(run["run_id"], "review-read", ticket["execution_request_id"], "success", {}, {})
    assert state["status"] == "completed" and state["history"][0]["input_route_succeeded"] is None
    assert state["history"][0]["read_observation"]["sha256"] == receipt["observation"]["sha256"]


def test_blocked_reason_persists_and_successful_prepare_clears_it(services):
    programs, trials, saved, _ = services
    definition = deepcopy(saved["definition"])
    definition["steps"][0]["preconditions"] = [{"left": {"source": "observation", "name": "ready"},
        "operator": "agent_assertion"}]
    newer = programs.save(WORKFLOW, saved["content_sha256"], definition, "conditional-version")
    run = trials.start(WORKFLOW, newer["program_id"], "search", {"query": "A"}, "conditional")
    blocked = trials.prepare(run["run_id"], "missing-observation")
    assert blocked["status"] == "blocked" and blocked["reason"] == "precondition_unknown"
    assert trials.status(run["run_id"])["reason"] == "precondition_unknown"
    assert trials.prepare(run["run_id"], "missing-observation") == blocked
    with pytest.raises(ValueError, match="idempotency_conflict"):
        trials.prepare(run["run_id"], "missing-observation", observations={"ready": True})
    ticket = trials.prepare(run["run_id"], "with-observation", observations={"ready": True})
    assert ticket["status"] == "pending"
    assert trials.prepare(run["run_id"], "missing-observation") == blocked
    state = trials.status(run["run_id"])
    assert state["status"] == "pending" and "reason" not in state and "blocked_request" not in state
