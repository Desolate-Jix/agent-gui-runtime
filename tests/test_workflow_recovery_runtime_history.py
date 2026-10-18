"""运行时失败历史须由原回执重算，不以历史声明证明失败。"""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_workflow_trial import services, response, WORKFLOW
from tests.test_workflow_recovery_history import catalog, verify


@pytest.fixture(params=["sync", "async"])
def runtime_history_scene(services, request):
    programs, trials, saved, session = services
    definition = deepcopy(saved["definition"])
    definition["steps"][0]["branches"]["failure"] = "open"
    saved = programs.save(WORKFLOW, saved["content_sha256"], definition, "failure-branch")
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "中文输入"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    path = response(session, ticket, action_executed=True)
    receipt = read_json_snapshot(path)
    if request.param == "sync":
        receipt.update(status="failed", error_type="ControlledFailure", error="原中文错误")
    else:
        worker = {"contract_version": "agent_command.v1", "command_id": ticket["execution_request_id"],
            "status": "failed", "action_executed": True, "result": receipt["result"],
            "error_type": "ControlledFailure", "error": "原中文错误"}
        (session / "agent-commands").mkdir()
        write_json_snapshot(session / "agent-commands" / path.name, worker)
        receipt["result"] = {"contract_version": "agent_command.v1", "command_id": ticket["execution_request_id"], "status": "running"}
    write_json_snapshot(path, receipt)
    state = trials.record_failed_execution(run["run_id"], "runtime-failure", ticket["execution_request_id"])
    return trials, state, programs.load(state["workflow_id"], state["program_id"]), session


def test_original_runtime_failure_consumes_step_without_outputs(runtime_history_scene):
    scene = runtime_history_scene
    before = catalog(scene[3])
    result = verify(scene)
    assert result["consumed_step_ids"] == ["search"]
    assert result["outputs"] == {}
    assert scene[1]["current_step_id"] == "open"
    assert result["history"][0]["action_executed"] is True
    assert result["history"][0]["error"] == "原中文错误"
    assert catalog(scene[3]) == before


@pytest.mark.parametrize("change", ["reason", "error", "type", "action", "request", "review", "extra", "uncertain", "receipt", "terminal", "imported"])
def test_runtime_claim_tampering_rejects(runtime_history_scene, change):
    trials, original, program, session = runtime_history_scene
    state = deepcopy(original)
    entry = state["history"][0]
    if change == "reason":
        entry["runtime_reason"] = "invented"
    elif change == "error":
        entry["error"] = "伪造错误"
    elif change == "type":
        entry["error_type"] = "OtherFailure"
    elif change == "action":
        entry["action_executed"] = False
    elif change == "request":
        state["requests"]["runtime-failure"] = "0" * 64
    elif change == "review":
        entry["review_request"]["request_id"] = "other-request"
    elif change == "extra":
        entry["outputs"] = {"result_title": "伪造输出"}
    elif change == "uncertain":
        entry.update(runtime_reason="cancel_requested_original_execution_terminal", runtime_verdict="uncertain", verdict="uncertain")
    elif change == "imported":
        state["recovery_import"] = {"contract_version": "workflow_recovery_import.v1"}
    else:
        eid = entry["execution_request_id"]
        path = session / ("agent-commands" if change == "terminal" and (session / "agent-commands").exists() else "responses") / (eid + ".json")
        value = read_json_snapshot(path)
        value.update(status="returned" if path.parent.name == "responses" else "completed", error="替换来源")
        write_json_snapshot(path, value)
    write_json_snapshot(trials._path(state["run_id"]), state)
    with pytest.raises(ValueError):
        verify((trials, state, program, session))


@pytest.mark.parametrize("action", [False, None])
def test_explicit_no_input_is_valid_but_unknown_action_is_not(services, action):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "中文输入"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    path = response(session, ticket, action_executed=action)
    receipt = read_json_snapshot(path)
    receipt.update(status="failed", error_type="ControlledFailure", error="原中文错误")
    write_json_snapshot(path, receipt)
    state = trials.record_failed_execution(run["run_id"], "runtime-failure", ticket["execution_request_id"])
    scene = trials, state, programs.load(state["workflow_id"], state["program_id"]), session
    before = catalog(session)
    if action is None:
        with pytest.raises(ValueError, match="runtime_action_unknown"):
            verify(scene)
    else:
        result = verify(scene)
        assert result["history"][0]["action_executed"] is False
        assert result["outputs"] == {}
    assert catalog(session) == before
