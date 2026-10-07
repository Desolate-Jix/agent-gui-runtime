"""真实交接边界的计时不冒充模型推理或调用数。"""

from copy import deepcopy
from time import perf_counter_ns

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.measurement import load_events
from app.learning_memory.workflow_metrics import load_run_metrics
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_agent_command_jobs import env, _found, _start, _wait


def _trial(jobs, store, initial):
    command = jobs._jobs["job-1"].command
    for folder in ("commands", "responses"):
        (store.session_root / folder).mkdir(exist_ok=True)
    write_json_snapshot(store.session_root / "commands/job-1.json", command)
    write_json_snapshot(store.session_root / "responses/job-1.json",
                        {"command": command, "result": initial})
    return {"run_id": "run-1", "history": [], "pending": {
        "execution_request_id": "job-1", "step_id": "open", "suggested_command": command}}


@pytest.mark.parametrize("outcome", ["success", "cancelled", "timeout", "failure"])
def test_real_handoff_clock_is_projected_once_without_counting_a_model_call(env, outcome):
    jobs, coordinator, store = env
    now = [1000.0]
    store._clock = lambda: now[0]
    store._ttl = 1
    before = perf_counter_ns()
    initial = _start(jobs)
    state = _wait(jobs, "job-1", "awaiting_grounding")
    trial = _trial(jobs, store, initial)
    pending = state["pending_grounding"]
    wait = state.get("grounding_wait")
    assert wait is not None, "the pending handoff must retain its actual start clock"
    assert wait["request_id"] == pending["request_id"]
    assert before <= wait["started_ns"] <= perf_counter_ns()
    assert "ended_ns" not in wait
    assert load_run_metrics(store.session_root, "run-1", trial=trial)["observed"]["event_count"] == 0
    assert jobs.get("job-1") == state
    if outcome == "success":
        store.resolve(pending["request_id"], _found(pending))
        jobs.resume("job-1", pending["request_id"], "exec-one")
        terminal = _wait(jobs, "job-1", "completed")
    elif outcome == "cancelled":
        jobs.cancel("job-1")
        terminal = _wait(jobs, "job-1", "cancelled")
    elif outcome == "timeout":
        now[0] = 1002.0
        terminal = _wait(jobs, "job-1", "failed")
    else:
        result = _found(pending)
        result.update(status="absent", candidates=[], selected_candidate_id=None)
        store.resolve(pending["request_id"], result)
        terminal = _wait(jobs, "job-1", "failed")
    after = perf_counter_ns()
    handoff = terminal["recognition_handoffs"][0]
    assert terminal["grounding_wait"] is None
    assert handoff["request_id"] == pending["request_id"]
    assert handoff["capture_id"] == pending["capture"]["capture_id"]
    assert handoff["source"] == "agent_current"
    interval = handoff["wait"]
    assert interval["status"] == outcome
    # Windows 单调时钟允许同一 tick 内完成，不补造严格正的等待时长。
    assert before <= interval["started_ns"] <= interval["ended_ns"] <= after
    assert len(coordinator.calls) == (1 if outcome == "success" else 0)
    for _ in range(2):
        metrics = load_run_metrics(store.session_root, "run-1", trial=trial)
        assert metrics["observed"]["event_count"] == 1
        assert metrics["observed"]["phase_elapsed_ns"]["wait"] == interval["ended_ns"] - interval["started_ns"]
        assert metrics["observed"]["model_calls"]["total"] == 0
        assert metrics["total_model_calls"] is metrics["total_usage"] is None
    events = load_events(store.session_root, "run-1")
    assert events[0]["phase"] == "wait" and events[0]["usage"] is None
    assert events[0]["status"] == outcome
    assert events[0]["evidence_refs"] == ["agent-commands/job-1.json"]
    trial["history"].append(trial.pop("pending"))
    assert load_run_metrics(store.session_root, "run-1", trial=trial)["observed"]["event_count"] == 1


def test_delegate_handoff_preserves_source_and_original_receipt_binding(env):
    jobs, coordinator, store = env
    jobs.configuration = RecognitionSourceConfig(source="agent_delegate", delegate_profile="existing-worker")
    initial = jobs.start("job-1", {"kind": "step", "operation": "execute_recognition_plan",
        "request": {"goal": "Search"}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "delegation": "supported",
         "model_selection": "supported", "delegate_vision": "supported"})
    _wait(jobs, "job-1", "awaiting_grounding")
    trial = _trial(jobs, store, initial)
    jobs.cancel("job-1")
    terminal = _wait(jobs, "job-1", "cancelled")
    assert terminal.get("recognition_handoffs"), "cancelled delegate waits must remain observable"
    assert terminal["recognition_handoffs"][0]["source"] == "agent_delegate"
    bad_trial = deepcopy(trial)
    bad_trial["pending"]["suggested_command"]["request"]["goal"] = "Different target"
    bad = load_run_metrics(store.session_root, "run-1", trial=bad_trial)
    assert bad["status"] == "unavailable"
    assert bad["observed"] is None
    assert load_run_metrics(store.session_root, "run-1", trial=trial)["observed"]["event_count"] == 1
    assert coordinator.calls == []


@pytest.mark.parametrize("corrupt", [
    {"source": []}, {"capture_id": "../old"},
    {"wait": {"started_ns": 10, "ended_ns": 9, "status": "success"}},
    {"wait": {"started_ns": 1, "ended_ns": 9, "status": "waiting"}},
])
def test_invalid_handoff_evidence_preserves_readable_job_without_fabricating_metrics(env, corrupt):
    jobs, coordinator, store = env
    initial = _start(jobs)
    _wait(jobs, "job-1", "awaiting_grounding")
    trial = _trial(jobs, store, initial)
    jobs.cancel("job-1")
    terminal = _wait(jobs, "job-1", "cancelled")
    terminal["recognition_handoffs"][0].update(corrupt)
    path = store.session_root / "agent-commands/job-1.json"
    write_json_snapshot(path, terminal)
    raw = path.read_bytes()
    metrics = load_run_metrics(store.session_root, "run-1", trial=trial)
    assert metrics["status"] == "unavailable" and metrics["observed"] is None
    assert metrics["total_model_calls"] is None
    assert jobs.get("job-1")["status"] == "cancelled"
    assert coordinator.calls == [] and path.read_bytes() == raw


def test_handoff_uses_same_clock_domain_as_api_and_rule_observations(env):
    jobs, _, store = env
    before = perf_counter_ns()
    _start(jobs)
    _wait(jobs, "job-1", "awaiting_grounding")
    jobs.cancel("job-1")
    terminal = _wait(jobs, "job-1", "cancelled")
    after = perf_counter_ns()
    interval = terminal["recognition_handoffs"][0]["wait"]
    assert before <= interval["started_ns"] <= interval["ended_ns"] <= after
