"""只由固定试运行票据构造当次目标绑定。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.desktop_review.external_mapping import canonical_json_bytes
from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.target_recipe import action_semantics_sha256
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_target_bindings import (
    contextual_target_goal, load_workflow_target_bindings,
)
from app.learning_memory.workspace import MemoryWorkspace


WORKFLOW = "workflow-" + "a" * 64
SNAPSHOT = "workflow-project-snapshot-" + "b" * 64
REF = {"recipe_id": "target-recipe-" + "c" * 64, "interface_key": "search", "state_key": "results"}
RULE = {"kind": "visible_row", "container": {"name": "结果列表", "control_type": "List"},
        "row": {"control_type": "ListItem"},
        "properties": [{"property": "title", "control_type": "Text", "read": "name"}],
        "constraints": [{"property": "title", "operator": "eq", "value": {"source": "input", "name": "query"}}],
        "action": {"name": "打开", "control_type": "Button"}}


@pytest.fixture
def ticket(tmp_path, monkeypatch):
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "results",
             "application": {"executable_name": "fixture.exe"},
             "anchors": [{"kind": "uia", "name": "结果页", "control_type": "Pane"}]}
    action = {"kind": "input_sequence", "field_goal": "搜索框", "text": {"source": "input", "name": "query"},
              "clear_existing": True, "submit_search": False, "target_memory": REF}
    recipe = {"scope": scope, "strategies": [RULE], "action_semantics_sha256": action_semantics_sha256(
        action, scope=scope, strategies=[RULE])}
    memory = {"snapshot_id": SNAPSHOT, "graph": {"workflow": {"goal": "搜索"}, "nodes": [], "edges": []}}
    monkeypatch.setattr("app.learning_memory.workflow_program.read_project", lambda *_: deepcopy(memory))
    monkeypatch.setattr("app.learning_memory.workflow_program.load_target_recipe", lambda *_: recipe)
    root, session = tmp_path / "library", tmp_path / "session"
    with MemoryWorkspace(root) as library:
        draft = library.load_workflow_program(WORKFLOW)
        definition = {"title": "搜索", "inputs": [{"name": "query", "type": "text", "required": True}],
                      "outputs": [], "steps": [{"step_id": "search", "title": "搜索", "source_node_id": None,
                      "target_node_id": None, "action": action, "preconditions": [], "success_conditions": [],
                      "branches": {"success": None, "failure": None, "uncertain": None}, "outputs": [],
                      "review_status": "reviewed", "provenance": "manual"}]}
        saved = library.save_workflow_program(WORKFLOW, draft["content_sha256"], definition, "save")
        run = library.start_workflow_trial(session, WORKFLOW, saved["program_id"], "search",
                                           {"query": "本次编号42"}, "start")
        pending = library.prepare_workflow_trial(session, run["run_id"], "prepare")
    return root, session, run, pending, recipe


def test_exact_pending_ticket_loads_current_run_bindings(ticket):
    root, session, run, pending, recipe = ticket
    command = pending["suggested_command"]
    result = load_workflow_target_bindings(root, session,
        execution_request_id=pending["execution_request_id"], command=command)
    assert result == {"run_id": run["run_id"], "step_id": "search",
        "execution_request_id": pending["execution_request_id"],
        "command_sha256": sha256(canonical_json_bytes(command)).hexdigest(),
        "action": {"kind": "input_sequence", "field_goal": "搜索框",
            "text": {"source": "input", "name": "query"}, "clear_existing": True,
            "submit_search": False, "target_memory": REF},
        "inputs": {"query": "本次编号42"}, "outputs": {}}
    assert "本次编号42" in contextual_target_goal(recipe, result)
    assert "结果列表" in contextual_target_goal(recipe, result)


def test_manual_command_without_ticket_returns_none(ticket):
    root, session, _, pending, _ = ticket
    assert load_workflow_target_bindings(root, session, execution_request_id="manual-new",
        command=pending["suggested_command"]) is None


def test_mismatched_cancelled_and_duplicate_ticket_rejected(ticket):
    root, session, run, pending, _ = ticket
    command = pending["suggested_command"]
    with pytest.raises(ValueError, match="command_mismatch"):
        load_workflow_target_bindings(root, session,
            execution_request_id=pending["execution_request_id"], command={**command, "request": {}})
    path = session / "workflow-trials" / (run["run_id"] + ".json")
    state = json.loads(path.read_text(encoding="utf-8"))
    state["status"] = "cancel_requested"
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="not_pending"):
        load_workflow_target_bindings(root, session,
            execution_request_id=pending["execution_request_id"], command=command)
    state["status"] = "pending"
    path.write_text(json.dumps(state), encoding="utf-8")
    duplicate = deepcopy(state)
    duplicate["run_id"] = "trial-" + "d" * 64
    (session / "workflow-trials" / (duplicate["run_id"] + ".json")).write_text(
        json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="ticket_ambiguous"):
        load_workflow_target_bindings(root, session,
            execution_request_id=pending["execution_request_id"], command=command)


def test_historical_prepare_ticket_is_not_manual_fallback(ticket):
    root, session, run, pending, _ = ticket
    path = session / "workflow-trials" / (run["run_id"] + ".json")
    state = json.loads(path.read_text(encoding="utf-8"))
    state["pending"] = None
    state["status"] = "cancelled"
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="not_pending"):
        load_workflow_target_bindings(root, session,
            execution_request_id=pending["execution_request_id"], command=pending["suggested_command"])


def test_dynamic_goal_rejects_missing_and_stale_values(ticket):
    _, _, run, pending, recipe = ticket
    bindings = {"run_id": run["run_id"], "step_id": "search",
        "execution_request_id": pending["execution_request_id"], "command_sha256": "0" * 64,
        "action": {"kind": "input_sequence", "field_goal": "搜索框", "submit_search": False},
        "inputs": {}, "outputs": {}}
    with pytest.raises(ValueError, match="missing_input"):
        contextual_target_goal(recipe, bindings)
    changed = deepcopy(recipe)
    changed["strategies"][0]["constraints"][0]["value"] = {
        "source": "output", "step_id": "read", "name": "id"}
    bindings["inputs"] = {"query": "本次编号42"}
    bindings["outputs"] = {"read.id": {"run_id": "older-run", "value": "42"}}
    with pytest.raises(ValueError, match="stale_output"):
        contextual_target_goal(changed, bindings)


def test_verified_prior_output_is_wrapped_with_current_run_and_old_ticket_rejected(ticket, tmp_path):
    root, _, _, _, recipe = ticket
    session = tmp_path / "second-session"
    with MemoryWorkspace(root) as library:
        prior = library.load_workflow_program(WORKFLOW)
        definition = deepcopy(prior["definition"])
        first = definition["steps"][0]
        first["outputs"] = [{"name": "record_id", "type": "text"}]
        first["branches"]["success"] = "second"
        second = deepcopy(first)
        second.update(step_id="second", title="第二次搜索", outputs=[],
                      branches={"success": None, "failure": None, "uncertain": None})
        definition["steps"].append(second)
        saved = library.save_workflow_program(WORKFLOW, prior["content_sha256"], definition, "two-steps")
        trial = TrialService(library, session)
        run = trial.start(WORKFLOW, saved["program_id"], "search", {"query": "本次编号42"}, "start-two")
        original = trial.prepare(run["run_id"], "prepare-one")
        identifier = original["execution_request_id"]
        (session / "commands").mkdir(parents=True)
        (session / "responses").mkdir(parents=True)
        write_json_snapshot(session / "commands" / (identifier + ".json"), original["suggested_command"])
        write_json_snapshot(session / "responses" / (identifier + ".json"), {
            "status": "returned", "command": original["suggested_command"],
            "result": {"contract_version": "input_sequence_v1", "status": "completed",
                       "action_executed": True}})
        trial.review(run["run_id"], "review-one", identifier, "success", {}, {"record_id": "42"})
        current = trial.prepare(run["run_id"], "prepare-two")
    bound = load_workflow_target_bindings(root, session,
        execution_request_id=current["execution_request_id"], command=current["suggested_command"])
    assert bound["outputs"] == {"search.record_id": {"run_id": run["run_id"], "value": "42"}}
    output_rule = deepcopy(recipe)
    output_rule["strategies"][0]["constraints"][0]["value"] = {
        "source": "output", "step_id": "search", "name": "record_id"}
    assert '"value":"42"' in contextual_target_goal(output_rule, bound)
    with pytest.raises(ValueError, match="not_pending"):
        load_workflow_target_bindings(root, session, execution_request_id=identifier,
                                      command=original["suggested_command"])
