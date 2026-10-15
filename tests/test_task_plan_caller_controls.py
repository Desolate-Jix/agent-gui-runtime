"""调用方参数只从当前原证据投影；审核和续行仍由调用方分别提交。"""
import asyncio
from copy import deepcopy
import json

import pytest

from app.execution.task_plan_admission import validate_task_plan_request
from app.execution.task_plan_review import digest
from app.core.json_snapshot import write_json_snapshot
from app.instant_mcp import build_server
from tests.test_instant_mcp import session
from tests.test_task_plan_adaptive_review import OfflineAssessment, adaptive_plan
from tests.test_task_plan_client import Session, client
from tests.test_task_plan_manual_observation import manual_scene, module, observe_request
from tests.test_task_plan_observation import ObservingAssessment, observation_scene
from tests.test_task_plan_runner import complete_original, scene


def test_mcp_review_rejection_names_missing_unknown_and_allowed_fields_without_queueing(session):
    request = {"action": "review", "run_id": "trial-" + "a" * 64,
        "step_id": "step-0", "execution_request_id": "original-input", "wait_id": "original-wait",
        "verdict": "success", "reason": "private-review-reason"}
    result = asyncio.run(build_server(session).call_tool("instant_submit", {
        "request_id": "invalid-review", "command": {"kind": "task_plan", "request": request}}))
    value = json.loads(result.content[0].text)
    assert value["status"] == "validation_rejected" and value["action_executed"] is False
    error = value["error"]
    assert error["missing_fields"] == ["evidence_sha256"]
    assert error["unknown_fields"] == ["wait_id"]
    assert "evidence_sha256" in error["allowed_fields"] and "wait_id" not in error["allowed_fields"]
    assert "task_plan_control_fields_invalid" in error["message"]
    assert "evidence_sha256" in error["message"] and "wait_id" in error["message"]
    assert "private-review-reason" not in json.dumps(error)
    assert not list((session.session / "commands").glob("*.json"))


@pytest.mark.parametrize("count", [1, 2])
def test_current_review_projection_requires_caller_verdict_before_explicit_continue(tmp_path, monkeypatch, count):
    source = adaptive_plan(count=count)
    if count == 2:
        source["steps"][1]["verification"] = {"kind": "native_condition", "condition": {
            "text": "Panel 1", "control_type": "Text"}}
    s = scene(tmp_path, monkeypatch, source=source, decision=OfflineAssessment())
    assert "caller_controls" not in s.first
    original = complete_original(s, native=False)
    receipt_path = tmp_path / "responses" / (original.command_id + ".json")
    receipt_bytes = receipt_path.read_bytes()
    waiting = s.runtime.tick(force=True)
    packet = deepcopy(waiting["review_packet"])
    controls = waiting["caller_controls"]
    assert controls["authorizes_action"] is False and "continue" not in controls
    assert controls["review"]["caller_supplied_fields"] == ["verdict", "reason"]
    request = controls["review"]["request"]
    assert request == {"action": "review", "run_id": s.run_id, "step_id": "step-0",
        "execution_request_id": original.command_id, "evidence_sha256": original.capture["sha256"],
        "review_packet_sha256": packet["packet_sha256"], "evidence_set_sha256": packet["evidence_set_sha256"],
        "assessment_round": packet["assessment_round"]}
    with pytest.raises(ValueError):
        validate_task_plan_request(request)
    assert s.runtime.control({"action": "status", "run_id": s.run_id}, "same-wait")["review_packet"] == packet
    assert digest({key: value for key, value in packet.items() if key != "packet_sha256"}) == packet["packet_sha256"]
    reviewed = s.runtime.control({**request, "verdict": "success", "reason": "Main inspected original evidence"}, "main-review")
    continuation = reviewed["caller_controls"]
    assert "review" not in continuation and continuation["authorizes_action"] is False
    assert continuation["continue"]["request"] == {"action": "continue", "run_id": s.run_id,
        "wait_id": waiting["wait"]["wait_id"]}
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    s.runtime.control(continuation["continue"]["request"], "continue-original")
    if count == 2:
        s.runtime.tick(force=True)
        complete_original(s)
        final = s.runtime.tick(force=True)
    else:
        final = s.runtime.control({"action": "status", "run_id": s.run_id}, "final-status")
    assert final["runner_state"] == "completed" and "caller_controls" not in final
    assert receipt_path.read_bytes() == receipt_bytes


def test_review_projection_binds_latest_packet_but_original_after(tmp_path, monkeypatch):
    s, original, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    old_request = waiting["caller_controls"]["review"]["request"]
    current = s.runtime.control(observe_request(s, waiting), "observe-control")
    packet = current["review_packet"]
    request = current["caller_controls"]["review"]["request"]
    assert request["review_packet_sha256"] == packet["packet_sha256"] != old_request["review_packet_sha256"]
    assert request["evidence_set_sha256"] == packet["evidence_set_sha256"] != old_request["evidence_set_sha256"]
    assert request["evidence_sha256"] == original.capture["sha256"] != packet["latest_observation"]["sha256"]
    with pytest.raises(ValueError, match="review_packet_binding"):
        s.runtime.control({**old_request, "verdict": "success", "reason": "Old packet"}, "stale-review")
    reviewed = s.runtime.control({**request, "verdict": "success", "reason": "Current evidence inspected"}, "fresh-review")
    assert "continue" in reviewed["caller_controls"]


def test_observation_pending_has_no_recipe_then_review_uses_actual_assessment_round(tmp_path, monkeypatch):
    s, original, clock, _ = observation_scene(tmp_path, monkeypatch,
        service=ObservingAssessment(final="review_required"))
    pending = s.runtime.tick(force=True)
    assert pending["observation_pending"] is True and "caller_controls" not in pending
    clock.seconds = .6
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    waiting = s.runtime.tick(force=True)
    packet = waiting["review_packet"]
    request = waiting["caller_controls"]["review"]["request"]
    assert packet["schema"] == "review_packet.v2" and request["assessment_round"] == 2
    assert request["evidence_sha256"] == original.capture["sha256"]
    assert request["evidence_set_sha256"] == packet["evidence_set_sha256"]
    s.runtime.control({**request, "verdict": "success", "reason": "Current observation inspected"}, "observed-review")


def test_failed_review_never_projects_a_continue_request(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    request = waiting["caller_controls"]["review"]["request"]
    reviewed = s.runtime.control({**request, "verdict": "failure", "reason": "Expected detail absent"}, "failed-review")
    assert reviewed["history"][-1]["verdict"] == "failure"
    assert "caller_controls" not in reviewed
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("status", ["unknown", "partial", "failure"])
def test_unverified_input_has_no_review_or_continue_recipe(tmp_path, monkeypatch, status):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    complete_original(s, status=status, native=False)
    result = s.runtime.tick(force=True)
    assert "caller_controls" not in result


def test_cancellation_and_unsettled_observation_have_no_recipe(tmp_path, monkeypatch):
    s, _, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    m = module()
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("Synthetic capture interruption")
    monkeypatch.setattr(m, "capture_followup", crash)
    with pytest.raises(KeyboardInterrupt):
        m.observe_task_plan(s.runtime, observe_request(s, waiting))
    unsettled = s.runtime.control({"action": "status", "run_id": s.run_id}, "unsettled-status")
    assert unsettled["allowed_controls"] == ["cancel"] and "caller_controls" not in unsettled
    cancelled = s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-unsettled")
    assert "caller_controls" not in cancelled


def test_existing_client_delivers_current_review_projection_without_submitting_it(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    session = Session([waiting])
    opened = client(tmp_path, session)
    result = asyncio.run(opened.run_plan("read-status", {"kind": "task_plan", "request": {
        "action": "status", "run_id": s.run_id}}))
    assert result["client_state"] == "review_required"
    assert result["result"]["caller_controls"] == waiting["caller_controls"]
    assert len(session.calls) == 1 and session.calls[0][1]["command"]["request"]["action"] == "status"


@pytest.mark.parametrize("detail", ["full", "compact"])
def test_mcp_status_and_run_deliver_actionable_controls_from_original_runtime(session, monkeypatch, detail):
    s = scene(session.session, monkeypatch, source=adaptive_plan(count=1), decision=OfflineAssessment())
    original = complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    write_json_snapshot(session.session / "report.json", {"phase": "ready", "task_plan_run": waiting})
    def submit(request_id, command):
        value = s.runtime.control(command["request"], request_id)
        write_json_snapshot(session.session / "commands" / (request_id + ".json"), command)
        write_json_snapshot(session.session / "responses" / (request_id + ".json"), {
            "status": "returned", "command": deepcopy(command), "result": value})
        write_json_snapshot(session.session / "report.json", {"phase": "ready", "task_plan_run": value})
        return session.result(request_id)
    monkeypatch.setattr(session, "submit", submit)
    server = build_server(session)
    async def scenario():
        status = await server.call_tool("instant_status", {})
        snapshot = json.loads(status.content[0].text)["task_plan_run"]
        request = snapshot["caller_controls"]["review"]["request"]
        assert request["evidence_sha256"] == original.capture["sha256"] and "wait_id" not in request
        reviewed = await server.call_tool("instant_run", {"request_id": "mcp-review", "command": {
            "kind": "task_plan", "request": {**request, "verdict": "success", "reason": "Main reviewed evidence"}},
            "detail": detail, "images": "none", "wait_ms": 0})
        result = json.loads(reviewed.content[0].text)["result"]
        assert result["caller_controls"]["continue"]["request"]["wait_id"] == waiting["wait"]["wait_id"]
        continued = await server.call_tool("instant_run", {"request_id": "mcp-continue", "command": {
            "kind": "task_plan", "request": result["caller_controls"]["continue"]["request"]},
            "detail": detail, "images": "none", "wait_ms": 0})
        return json.loads(continued.content[0].text)
    final = asyncio.run(scenario())
    assert final["result"]["runner_state"] == "completed" and "caller_controls" not in final["result"]
    assert len([path for path in (session.session / "commands").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["kind"] != "task_plan"]) == 1
