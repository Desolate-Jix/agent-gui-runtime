"""原历史须回读原命令、回执和规则证据；不代表独立准确率验收。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tests.test_workflow_trial import services, response, WORKFLOW
from tests.test_workflow_verified_trial import setup_run


def catalog(session):
    return {str(path.relative_to(session)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
            for path in session.rglob("*") if path.is_file()}


@pytest.fixture(params=["agent", "rule"])
def history_scene(services, request):
    programs, trials, saved, session = services
    if request.param == "rule":
        trials, run, ticket, result, _ = setup_run(services, expected="中文新值", actual="中文新值")
        state = trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    else:
        run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "中文新值"}, "start")
        ticket = trials.prepare(run["run_id"], "prepare")
        response(session, ticket)
        state = trials.review(run["run_id"], "review", ticket["execution_request_id"], "success",
                              {"results_visible": True}, {"result_title": "中文结果"})
    return trials, state, programs.load(state["workflow_id"], state["program_id"]), session


def verify(scene, hashes=None):
    from app.learning_memory.workflow_recovery_history import verify_recovery_history
    trials, state, program, session = scene
    return verify_recovery_history(trials.programs.library, session, state, program,
                                   file_hashes=catalog(session) if hashes is None else hashes)


def test_original_agent_and_rule_history_verifies_without_changing_source(history_scene):
    before = catalog(history_scene[3])
    result = verify(history_scene)
    assert result["contract_version"] == "workflow_recovery_history.v1"
    assert result["history"] == history_scene[1]["history"]
    assert result["outputs"] == history_scene[1]["outputs"]
    assert result["consumed_step_ids"] == ["search"]
    assert catalog(history_scene[3]) == before
    from app.desktop_review.external_mapping import canonical_json_bytes
    assert result["content_sha256"] == sha256(canonical_json_bytes({k: v for k, v in result.items() if k != "content_sha256"})).hexdigest()


@pytest.mark.parametrize("change", ["receipt", "command", "state", "request", "output", "terminal", "duplicate", "program"])
def test_relabelled_or_changed_original_history_rejects(history_scene, change):
    trials, state, program, session = history_scene
    state = deepcopy(state)
    program = deepcopy(program)
    eid = state["history"][0]["execution_request_id"]
    if change in {"receipt", "command"}:
        path = session / ("responses" if change == "receipt" else "commands") / (eid + ".json")
        value = json.loads(path.read_text(encoding="utf-8"))
        if change == "receipt":
            value["result"]["action_executed"] = False
        else:
            value["request"]["text"] = "替换值"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    elif change == "state":
        state["inputs"]["query"] = "替换值"
    elif change == "request":
        state["requests"] = {key: "0" * 64 for key in state["requests"]}
    elif change == "output":
        state["outputs"]["search." + next(iter(state["history"][0]["outputs"]))] = "替换输出"
    elif change == "terminal":
        state["history"][0]["terminal_receipt"] = {"status": "completed", "sha256": "0" * 64}
    elif change == "duplicate":
        state["history"].append(deepcopy(state["history"][0]))
    else:
        program["content_sha256"] = "0" * 64
    if change != "state":
        trials._path(state["run_id"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        verify((trials, state, program, session))


@pytest.mark.parametrize("origin", ["runtime", "recovery_import"])
def test_unsupported_history_origin_is_explicit(history_scene, origin):
    trials, state, program, session = history_scene
    state = deepcopy(state)
    state["history"][0]["judged_by"] = origin
    trials._path(state["run_id"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="workflow_recovery_history_origin_not_supported"):
        verify((trials, state, program, session))


def test_rule_frame_bytes_are_required_in_admission_catalog(services):
    trials, run, ticket, result, _ = setup_run(services)
    state = trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    scene = trials, state, trials.programs.load(state["workflow_id"], state["program_id"]), trials.session
    hashes = catalog(trials.session)
    del hashes["workflow-observations/current.png"]
    with pytest.raises(ValueError):
        verify(scene, hashes)
    (trials.session / "workflow-observations/current.png").write_bytes(b"invalid png")
    with pytest.raises(ValueError):
        verify(scene)


def test_async_original_terminal_requires_its_original_bytes(services):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "新值"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    path = response(session, ticket)
    original = json.loads(path.read_text(encoding="utf-8"))
    worker = {"contract_version": "agent_command.v1", "command_id": ticket["execution_request_id"],
              "status": "completed", "result": original["result"]}
    original["result"] = {"contract_version": "agent_command.v1", "command_id": ticket["execution_request_id"], "status": "running"}
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    folder = session / "agent-commands"
    folder.mkdir()
    worker_path = folder / path.name
    worker_path.write_text(json.dumps(worker, ensure_ascii=False), encoding="utf-8")
    state = trials.review(run["run_id"], "review", ticket["execution_request_id"], "success",
                          {"results_visible": True}, {"result_title": "新输出"})
    scene = trials, state, programs.load(state["workflow_id"], state["program_id"]), session
    assert worker_path.relative_to(session).as_posix() in verify(scene)["files"]
    worker["result"]["action_executed"] = False
    worker_path.write_text(json.dumps(worker, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        verify(scene)


@pytest.mark.parametrize("origin", ["no_proof", "recorded_submit", "source_review_command"])
def test_agent_failure_requires_actual_submitted_outputs_proof(services, origin):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "新值"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    response(session, ticket)
    submitted = {"result_title": "原提交值"}
    state = trials.review(run["run_id"], "review", ticket["execution_request_id"], "success",
                          {"results_visible": False}, submitted)
    state = deepcopy(state)
    state["history"][0].pop("review_request", None)
    if origin == "recorded_submit":
        state["history"][0]["review_request"] = {"request_id": "review", "submitted_outputs": submitted}
    elif origin == "source_review_command":
        request = {"action": "review", "run_id": run["run_id"], "execution_request_id": ticket["execution_request_id"],
                   "verdict": "success", "observations": {"results_visible": False}, "outputs": submitted}
        (session / "commands/review.json").write_text(json.dumps({"kind": "learning_workflow", "request": request}, ensure_ascii=False), encoding="utf-8")
    trials._path(state["run_id"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    scene = trials, state, programs.load(state["workflow_id"], state["program_id"]), session
    if origin == "no_proof":
        with pytest.raises(ValueError, match="submitted_outputs_unavailable"):
            verify(scene)
    else:
        assert verify(scene)["outputs"] == {}


def test_original_read_history_proves_png_without_claiming_input(services):
    from PIL import Image
    programs, trials, saved, session = services
    definition = deepcopy(saved["definition"])
    definition["steps"][1]["action"] = {"kind": "read_text", "goal": "读取结果"}
    definition["steps"][1]["preconditions"] = []
    program = programs.save(WORKFLOW, saved["content_sha256"], definition, "read-program")
    run = trials.start(WORKFLOW, program["program_id"], "open", {"query": "新值"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    (session / "commands").mkdir()
    (session / "commands" / (ticket["execution_request_id"] + ".json")).write_text(json.dumps(ticket["suggested_command"]), encoding="utf-8")
    image = session / "read.png"
    Image.new("RGB", (4, 3), "white").save(image)
    receipt = {"status": "returned", "command": ticket["suggested_command"],
               "result": {"status": "agent_read_required", "action_executed": False},
               "observation": {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(), "capture_id": "read-current"}}
    (session / "responses" / (ticket["execution_request_id"] + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
    state = trials.review(run["run_id"], "review", ticket["execution_request_id"], "success", {}, {})
    proof = verify((trials, state, programs.load(WORKFLOW, program["program_id"]), session))
    assert proof["history"][0]["input_route_succeeded"] is None
    assert "read.png" in proof["files"]


def test_source_changed_during_rule_computation_rejects_at_final_readback(services, monkeypatch):
    from app.learning_memory import workflow_recovery_history as module
    trials, run, ticket, result, _ = setup_run(services)
    state = trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    scene = trials, state, trials.programs.load(state["workflow_id"], state["program_id"]), trials.session
    original = module.verify_step

    def changing(*args, **kwargs):
        computed = original(*args, **kwargs)
        image = trials.session / "workflow-observations/current.png"
        image.write_bytes(image.read_bytes() + b"changed")
        return computed

    monkeypatch.setattr(module, "verify_step", changing)
    with pytest.raises(ValueError, match="source_changed"):
        verify(scene)
