"""审核等待使用原票据和真实时钟，不冒充模型调用或重发输入。"""
import json

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.measurement import load_events
from tests.test_workflow_trial import services, response, click_response
from tests.test_workflow_runtime import runtime_scene


def waiting_scene(scene, monkeypatch):
    runtime, trials, run, session, co = scene
    clock = [100]
    monkeypatch.setattr("app.learning_memory.workflow_runner.perf_counter_ns", lambda: clock[0], raising=False)
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run")
    ticket = trials.status(run["run_id"])["pending"]
    response(session, ticket)
    waiting = runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required"
    return runtime, trials, run, session, co, clock, ticket, waiting


def review_and_continue(runtime, trials, run, ticket, waiting, verdict="success"):
    trials.review(run["run_id"], "review", ticket["execution_request_id"], verdict,
                  {"results_visible": True}, {"result_title": "current"} if verdict == "success" else {})
    return runtime.control({"action": "continue", "run_id": run["run_id"],
                            "wait_id": waiting["wait"]["wait_id"]}, "continue-reviewed")


@pytest.mark.parametrize("verdict,expected", [("success", "success"), ("uncertain", "waiting"), ("failure", "failure")])
def test_review_wait_is_measured_once_without_counting_model_calls(runtime_scene, monkeypatch, verdict, expected):
    runtime, trials, run, session, co, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    assert waiting["metrics"]["verification_waits"] == {"measured": 0, "unmeasured": 0, "pending": 1}
    clock[0] = 200
    runtime.control({"action": "continue", "run_id": run["run_id"],
                     "wait_id": waiting["wait"]["wait_id"]}, "too-early")
    runtime = type(runtime)(session, co)
    clock[0] = 500
    done = review_and_continue(runtime, trials, run, ticket, waiting, verdict)
    for _ in range(2):
        runtime.runner.status(run["run_id"])
    events = load_events(session, run["run_id"])
    assert len(events) == 1
    event = events[0]
    assert (event["started_ns"], event["ended_ns"], event["status"]) == (100, 500, expected)
    assert event["source"] == "workflow_verification_wait" and event["phase"] == "wait"
    assert event["request_id"] == ticket["execution_request_id"] and event["step_id"] == "search"
    assert event["usage"] is None
    metrics = done["metrics"]
    assert metrics["observed"]["phase_elapsed_ns"]["wait"] == 400
    assert sum(metrics["observed"]["model_calls"].values()) == 0
    assert metrics["total_model_calls"] is None and metrics["total_usage"] is None
    assert metrics["verification_waits"] == {"measured": 1, "unmeasured": 0, "pending": 0}
    assert len(list(session.glob("commands/*.json"))) == 1


def test_cancel_closes_wait_once_without_reopening_during_reconciliation(runtime_scene, monkeypatch):
    runtime, trials, run, session, _, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    clock[0] = 350
    cancelled = runtime.control({"action": "cancel", "run_id": run["run_id"]}, "cancel")
    assert cancelled["metrics"]["verification_waits"]["measured"] == 1
    clock[0] = 900
    runtime.tick(force=True)
    runtime.runner.verify_step = lambda rid, req, eid: trials.record_cancelled_execution(rid, req, eid)
    final = runtime.runner.advance(run["run_id"])
    events = load_events(session, run["run_id"])
    assert len(events) == 1 and events[0]["status"] == "cancelled"
    assert (events[0]["started_ns"], events[0]["ended_ns"]) == (100, 350)
    assert final["runner_state"] == "cancelled"
    assert len(list(session.glob("commands/*.json"))) == 1


def test_process_clock_change_is_unmeasured_not_negative_or_fabricated(runtime_scene, monkeypatch):
    runtime, trials, run, session, co, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    monkeypatch.setattr("app.learning_memory.workflow_runner._CLOCK_ID", "new-process", raising=False)
    clock[0] = 10
    reopened = type(runtime)(session, co)
    done = review_and_continue(reopened, trials, run, ticket, waiting)
    assert done["metrics"]["verification_waits"] == {"measured": 0, "unmeasured": 1, "pending": 0}
    assert load_events(session, run["run_id"]) == []
    state = json.loads((session / "workflow-runners" / (run["run_id"] + ".json")).read_text(encoding="utf-8"))
    assert state["verification_waits"][0]["unmeasured_reason"] == "clock_changed"


def test_legacy_wait_does_not_gain_an_invented_start_time(runtime_scene, monkeypatch):
    runtime, trials, run, session, _, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    path = session / "workflow-runners" / (run["run_id"] + ".json")
    state = json.loads(path.read_text(encoding="utf-8"))
    state.pop("verification_wait", None)
    state.pop("verification_waits", None)
    write_json_snapshot(path, state)
    clock[0] = 800
    done = review_and_continue(runtime, trials, run, ticket, waiting)
    assert done["metrics"]["verification_waits"] == {"measured": 0, "unmeasured": 0, "pending": 0}
    assert load_events(session, run["run_id"]) == []


@pytest.mark.parametrize("tamper", ["execution", "step", "clock", "command", "response", "status", "duplicate"])
def test_wait_metrics_reject_mismatched_evidence_without_changing_execution(runtime_scene, monkeypatch, tamper):
    runtime, trials, run, session, _, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    clock[0] = 500
    review_and_continue(runtime, trials, run, ticket, waiting)
    path = session / "workflow-runners" / (run["run_id"] + ".json")
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state.get("verification_waits"), "closed wait evidence is missing"
    if tamper == "execution":
        state["verification_waits"][0]["execution_request_id"] = "unrelated"
    elif tamper == "step":
        state["verification_waits"][0]["step_id"] = "unrelated"
    elif tamper == "clock":
        state["verification_waits"][0]["measurement"]["ended_ns"] = 1
    elif tamper == "command":
        write_json_snapshot(session / "commands" / (ticket["execution_request_id"] + ".json"), {"kind": "capture"})
    elif tamper == "status":
        state["verification_waits"][0]["status"] = []
    elif tamper == "duplicate":
        state["verification_waits"].append(state["verification_waits"][0])
    else:
        receipt = session / "responses" / (ticket["execution_request_id"] + ".json")
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["result"]["status"] = "failed"
        write_json_snapshot(receipt, value)
    write_json_snapshot(path, state)
    snapshot = runtime.runner.status(run["run_id"])
    assert snapshot["metrics"]["status"] == "unavailable"
    assert snapshot["metrics"]["observed"] is None
    assert len(list(session.glob("commands/*.json"))) == 1


def test_two_step_continuous_run_keeps_distinct_waits_and_original_commands(runtime_scene, monkeypatch):
    runtime, trials, run, session, _, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    clock[0] = 300
    review_and_continue(runtime, trials, run, ticket, waiting)
    runtime.tick(force=True)
    second = trials.status(run["run_id"])["pending"]
    click_response(session, second)
    clock[0] = 400
    waiting = runtime.tick(force=True)
    trials.review(run["run_id"], "review-second", second["execution_request_id"], "success", {}, {})
    clock[0] = 700
    done = runtime.control({"action": "continue", "run_id": run["run_id"],
                            "wait_id": waiting["wait"]["wait_id"]}, "continue-second")
    assert done["runner_state"] == "completed"
    assert done["metrics"]["observed"]["phase_elapsed_ns"]["wait"] == 500
    assert done["metrics"]["verification_waits"] == {"measured": 2, "unmeasured": 0, "pending": 0}
    assert {event["request_id"] for event in load_events(session, run["run_id"])} == {
        ticket["execution_request_id"], second["execution_request_id"]}
    assert len(list(session.glob("commands/*.json"))) == 2


def test_real_monotonic_clock_records_review_wait(runtime_scene):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run")
    ticket = trials.status(run["run_id"])["pending"]
    response(session, ticket)
    waiting = runtime.tick(force=True)
    done = review_and_continue(runtime, trials, run, ticket, waiting)
    assert done["metrics"]["observed"]["phase_elapsed_ns"]["wait"] > 0
    assert done["metrics"]["total_model_calls"] is None
