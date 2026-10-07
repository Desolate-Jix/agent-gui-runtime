"""规则判断须回读原请求、终态回执及本轮观察证据。"""
from copy import deepcopy
from hashlib import sha256
import json

from PIL import Image
import pytest

from app.learning_memory.workflow_verification import verify_step
from tests.test_workflow_trial import services, response, WORKFLOW
from tests.test_workflow_rule_definition import definition


def setup_run(services, *, expected="new", actual="new"):
    programs, trials, saved, session = services
    value = definition(saved)
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "rules")
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": expected}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    path = response(session, ticket)
    source = json.loads(path.read_text(encoding="utf-8"))
    identity = {"handle": 1, "process_id": 2, "process_create_time": 3.0}
    source["result"]["target_identity"] = {"target_window_handle": 1, "process_id": 2, "process_create_time": 3.0}
    source["result"]["capture"] = {"capture_id": "before-1"}
    path.write_text(json.dumps(source), encoding="utf-8")
    directory = session / "workflow-observations"
    directory.mkdir()
    image = directory / "current.png"
    Image.new("RGB", (160, 100), "white").save(image)
    frame = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
             "capture_id": "after-1", "image_size": {"width": 160, "height": 100}, "window_identity": identity}
    normalized = {"run_id": run["run_id"], "step_id": "search", "request_id": "verify", "execution_request_id": ticket["execution_request_id"],
        "status": "completed", "action_executed": True, "pre_capture_id": "before-1", "post_capture_id": "after-1",
        "post_capture_sha256": frame["sha256"], "window_identity": identity, "scope_id": "current-query",
        "evidence_ref": str(path.relative_to(session))}
    observation = {key: normalized[key] for key in ("run_id", "step_id", "request_id", "execution_request_id", "window_identity", "scope_id")}
    observation.update(capture_id=frame["capture_id"], capture_sha256=frame["sha256"], complete=True,
        source="uia_value", values={"field_value": actual}, evidence_ref="workflow-observations/verify.json")
    envelope = {"contract_version": "workflow_observation.v1", "receipt": normalized, "observation": observation,
                "frame": frame, "source_receipt_sha256": sha256(path.read_bytes()).hexdigest()}
    (directory / "verify.json").write_text(json.dumps(envelope), encoding="utf-8")
    result = verify_step(saved["definition"]["steps"][0], inputs=run["inputs"], outputs={}, receipt=normalized, observation=observation)
    return trials, run, ticket, result, envelope


def test_rule_verdict_is_persisted_once_and_outputs_feed_next_step(services):
    trials, run, ticket, result, _ = setup_run(services)
    final = trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    assert final["status"] == "ready" and final["current_step_id"] == "open"
    assert final["outputs"] == {"search.result_title": "new"}
    assert final["history"][0]["judged_by"] == "rule"
    assert final["history"][0]["verification"] == result
    assert trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result) == final
    assert trials.prepare(run["run_id"], "next")["step_id"] == "open"


@pytest.mark.parametrize("change", ["invented_output", "old_run", "wrong_window", "changed_receipt", "changed_image"])
def test_rule_evidence_cannot_be_replaced_or_relabelled(services, change):
    trials, run, ticket, result, envelope = setup_run(services)
    if change == "invented_output": result["outputs"]["result_title"] = "invented"
    if change == "old_run": result["observations"]["run_id"] = "old"
    if change == "wrong_window":
        envelope["receipt"]["window_identity"]["handle"] = 999
        envelope["observation"]["window_identity"]["handle"] = 999
        envelope["frame"]["window_identity"]["handle"] = 999
        result["observations"]["window_identity"]["handle"] = 999
        (trials.session / "workflow-observations/verify.json").write_text(json.dumps(envelope), encoding="utf-8")
    if change == "changed_receipt":
        path = trials.session / "responses" / (ticket["execution_request_id"] + ".json")
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    if change == "changed_image": (trials.session / "workflow-observations/current.png").write_bytes(b"bad")
    with pytest.raises(ValueError):
        trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    assert trials.status(run["run_id"])["pending"] is not None
    assert trials.status(run["run_id"])["outputs"] == {}


def test_old_visible_value_is_failure_not_new_output(services):
    trials, run, ticket, result, _ = setup_run(services, expected="new", actual="previous")
    assert result["verdict"] == "failure"
    state = trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    assert state["status"] == "failed" and state["outputs"] == {}
