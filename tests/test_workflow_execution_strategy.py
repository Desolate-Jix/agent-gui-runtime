"""步骤复用策略固定在原运行中，保留当前数据与原请求核验。"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.learning_memory.workflow_control import workflow_control
from app.learning_memory.workflow_trial import TrialService
from tests.test_workflow_trial import WORKFLOW, response, services


def start_request(saved, strategy):
    return {"action": "start", "workflow_id": WORKFLOW, "program_id": saved["program_id"],
            "start_step_id": "search", "inputs": {"query": "本次编号42"},
            "execution_strategy": strategy}


def test_strategy_is_pinned_at_start_and_part_of_idempotency(services):
    programs, trials, saved, session = services
    from app.instant_mcp import InstantCommand
    request = start_request(saved, "steps_only")
    command = {"kind": "learning_workflow", "request": request}
    assert InstantCommand.model_validate(command).command() == command
    run = workflow_control(programs.library, session, request, "start-strategy")
    assert run["execution_strategy"] == "steps_only"
    assert workflow_control(programs.library, session, request, "start-strategy") == run
    assert TrialService(programs.library, session).status(run["run_id"]) == run
    with pytest.raises(ValueError, match="idempotency_conflict"):
        workflow_control(programs.library, session, start_request(saved, "learned"), "start-strategy")
    normal = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "C"}, "normal")
    assert normal["execution_strategy"] == "learned"


@pytest.mark.parametrize("strategy", [None, True, {}, "B", "unknown"])
def test_invalid_strategy_does_not_create_a_run(services, strategy):
    programs, _, saved, session = services
    with pytest.raises(ValueError, match="execution_strategy"):
        workflow_control(programs.library, session, start_request(saved, strategy), "bad-strategy")
    assert not list((session / "workflow-trials").glob("trial-*.json"))


@pytest.mark.parametrize("kind", ["click", "input_sequence"])
def test_steps_only_keeps_bound_identity_without_native_target_memory(services, monkeypatch, kind):
    programs, trials, saved, session = services
    from app.learning_memory.target_recipe import action_semantics_sha256
    from tests.test_workflow_target_bindings import REF, RULE
    definition = deepcopy(saved["definition"])
    step = definition["steps"][0]
    if kind == "click":
        step["action"] = {"kind": "click", "goal": "打开对应记录"}
    step["action"]["target_memory"] = REF
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "results",
             "application": {"executable_name": "fixture.exe"},
             "anchors": [{"kind": "uia", "name": "结果页", "control_type": "Pane"}]}
    recipe = {"scope": scope, "strategies": [RULE], "action_semantics_sha256": action_semantics_sha256(
        step["action"], scope=scope, strategies=[RULE])}
    monkeypatch.setattr("app.learning_memory.workflow_program.load_target_recipe", lambda *_: deepcopy(recipe))
    monkeypatch.setattr("app.learning_memory.target_recipe.load_target_recipe", lambda *_: deepcopy(recipe))
    saved = programs.save(WORKFLOW, saved["content_sha256"], definition, "with-target")
    before = programs.load(WORKFLOW, saved["program_id"])
    run = workflow_control(programs.library, session, start_request(saved, "steps_only"), "start-B")
    ticket = trials.prepare(run["run_id"], "prepare-B")
    command = ticket["suggested_command"]
    assert "target_memory" not in command["request"]
    goal_key = "goal" if kind == "click" else "field_goal"
    assert "本次编号42" in command["request"][goal_key]
    assert "结果列表" in command["request"][goal_key]
    if kind == "input_sequence":
        assert command["request"]["text"] == "本次编号42"
    assert ticket["execution_strategy"] == "steps_only"
    assert ticket["preview"]["execution_strategy"] == "steps_only"
    assert "target_memory" not in ticket["preview"]["action"]
    assert ticket["preview"]["program_review_status"] == before["definition"]["steps"][0]["review_status"]
    assert ticket["preview"]["review_status"] == "pending"
    assert trials.prepare(run["run_id"], "another-read") == ticket
    assert programs.load(WORKFLOW, saved["program_id"]) == before
    from app.instant_mcp import InstantCommand
    assert InstantCommand.model_validate(command).command() == command
    normal = TrialService(programs.library, session / "normal")
    run_c = normal.start(WORKFLOW, saved["program_id"], "search", {"query": "不同编号"}, "start-C")
    ticket_c = normal.prepare(run_c["run_id"], "prepare-C")
    assert ticket_c["suggested_command"]["request"]["target_memory"] == REF
    assert ticket_c["preview"]["action"] == before["definition"]["steps"][0]["action"]


def test_steps_only_waits_for_agent_even_when_native_rule_exists(services, monkeypatch):
    programs, trials, saved, session = services
    from tests.test_workflow_rule_definition import definition
    from app.learning_memory.runtime_verification import verify_trial_step
    saved = programs.save(WORKFLOW, saved["content_sha256"], definition(saved), "with-rule")
    run = workflow_control(programs.library, session, start_request(saved, "steps_only"), "start-B")
    ticket = trials.prepare(run["run_id"], "prepare-B")
    response(session, ticket)

    @contextmanager
    def workspace(_):
        yield programs.library

    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    def no_observation(*args, **kwargs):
        raise AssertionError("steps_only invoked native result verification")
    monkeypatch.setattr("app.learning_memory.verification_observation.read_step_observation", no_observation)
    artifact = session / "workflow-observations" / "verify-B.json"
    artifact.parent.mkdir()
    artifact.write_text("invalid prior artifact", encoding="utf-8")
    coordinator = SimpleNamespace(_memory_library_root=programs.library._workspace_root,
                                  _owner=SimpleNamespace(call=lambda callback: callback()))
    request = {"action": "verify", "run_id": run["run_id"],
               "execution_request_id": ticket["execution_request_id"]}
    result = verify_trial_step(coordinator, session_dir=session, request=request, request_id="verify-B")
    assert result["status"] == "verification_required"
    assert result["reason"] == "steps_only_agent_review_required"
    assert result["execution_strategy"] == "steps_only"
    assert trials.status(run["run_id"])["history"] == []
    with pytest.raises(ValueError, match="steps_only_requires_agent_review"):
        trials.record_verified_result(run["run_id"], "rule-bypass", ticket["execution_request_id"],
            {"verdict": "success", "source": "rule", "observations": {}, "outputs": {},
             "evidence_refs": [], "reason": "rule_passed"})


def test_steps_only_agent_review_preserves_outputs_and_success_branches(services):
    programs, trials, saved, session = services
    definition = deepcopy(saved["definition"])
    definition["steps"][1]["action"] = {"kind": "input_sequence", "field_goal": "当前状态",
        "text": {"source": "output", "step_id": "search", "name": "result_title"},
        "clear_existing": True, "submit_search": False}
    saved = programs.save(WORKFLOW, saved["content_sha256"], definition, "downstream")
    run = workflow_control(programs.library, session, start_request(saved, "steps_only"), "start-B")
    ticket = trials.prepare(run["run_id"], "prepare-one")
    response(session, ticket)
    advanced = trials.review(run["run_id"], "agent-review", ticket["execution_request_id"],
                             "success", {"results_visible": True}, {"result_title": "刚读取的新状态"})
    assert advanced["history"][0]["judged_by"] == "agent"
    assert advanced["history"][0]["execution_strategy"] == "steps_only"
    assert advanced["current_step_id"] == "open"
    next_ticket = trials.prepare(run["run_id"], "prepare-two")
    assert next_ticket["suggested_command"]["request"]["text"] == "刚读取的新状态"
    response(session, next_ticket)
    complete = trials.review(run["run_id"], "review-two", next_ticket["execution_request_id"], "success", {}, {})
    assert complete["status"] == "completed"
    assert complete["execution_strategy"] == "steps_only"
    assert all(item["judged_by"] == "agent" for item in complete["history"])


def test_pending_ticket_strategy_drift_is_rejected(services):
    import json
    programs, trials, saved, session = services
    run = workflow_control(programs.library, session, start_request(saved, "steps_only"), "start-B")
    trials.prepare(run["run_id"], "prepare")
    path = trials._path(run["run_id"])
    state = json.loads(path.read_text(encoding="utf-8"))
    state["execution_strategy"] = "learned"
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="execution_strategy_mismatch"):
        trials.prepare(run["run_id"], "read-again")


def test_steps_only_rejects_outputs_not_supported_by_current_history(services):
    import json
    programs, trials, saved, session = services
    run = workflow_control(programs.library, session, start_request(saved, "steps_only"), "start-B")
    path = trials._path(run["run_id"])
    state = json.loads(path.read_text(encoding="utf-8"))
    state["outputs"]["search.result_title"] = "旧运行的值"
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    result = trials.prepare(run["run_id"], "prepare-corrupt")
    assert result["status"] == "blocked"
    assert result["reason"] == "workflow_target_outputs_mismatch"
    assert trials.status(run["run_id"])["pending"] is None


def test_workspace_start_forwards_the_strategy(services):
    from threading import RLock
    from app.learning_memory.workspace import MemoryWorkspace
    programs, trials, saved, session = services
    view = SimpleNamespace(_guard=RLock(), _workspace_root=programs.library._workspace_root,
                           _require_open=lambda: None)
    run = MemoryWorkspace.start_workflow_trial(view, session, WORKFLOW, saved["program_id"],
        "search", {"query": "当前"}, "workspace-B", execution_strategy="steps_only")
    assert trials.status(run["run_id"])["execution_strategy"] == "steps_only"


def test_steps_only_pending_cannot_restore_native_target_memory(services):
    import json
    from tests.test_workflow_target_bindings import REF
    programs, trials, saved, session = services
    run = workflow_control(programs.library, session, start_request(saved, "steps_only"), "start-B")
    trials.prepare(run["run_id"], "prepare")
    path = trials._path(run["run_id"])
    state = json.loads(path.read_text(encoding="utf-8"))
    state["pending"]["suggested_command"]["request"]["target_memory"] = REF
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="steps_only_target_memory_forbidden"):
        trials.prepare(run["run_id"], "reopen")


def test_blocked_prepare_still_identifies_its_pinned_strategy(services):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "open", {"query": "new"}, "start-B",
                       execution_strategy="steps_only")
    result = trials.prepare(run["run_id"], "missing-upstream")
    assert result["status"] == "blocked"
    assert result["execution_strategy"] == "steps_only"


def test_default_agent_verification_wait_identifies_learned_strategy(services, monkeypatch):
    from app.learning_memory.runtime_verification import verify_trial_step
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "new"}, "start-C")
    ticket = trials.prepare(run["run_id"], "prepare")
    @contextmanager
    def workspace(_):
        yield programs.library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    co = SimpleNamespace(_memory_library_root=programs.library._workspace_root)
    result = verify_trial_step(co, session_dir=session, request={"action": "verify",
        "run_id": run["run_id"], "execution_request_id": ticket["execution_request_id"]}, request_id="verify-C")
    assert result["status"] == "verification_required"
    assert result["execution_strategy"] == "learned"
