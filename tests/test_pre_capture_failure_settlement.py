"""识别前截图失败只结算已证明的零输入；未知派发仍保留原票据。"""
from copy import deepcopy
from time import monotonic, sleep

import pytest

from app.core.input_sequence_partial import original_input_status
from app.core.screenshot import CaptureVisibilityError
from app.vision.agent_command_jobs import AgentCommandJobs
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_input_sequence_focus_partial import REQUEST, TARGET, queued
from tests.test_local_step_timings import timed_scene


@pytest.fixture
def pre_capture(timed_scene, tmp_path):
    co, state, *_ = timed_scene
    captures = []

    def capture():
        captures.append(True)
        raise CaptureVisibilityError("capture_window_occluded")

    store = GroundingHandoffStore(tmp_path / "job", owner_id="capture-owner")
    jobs = AgentCommandJobs(co, store, capture, RecognitionSourceConfig(source="agent_current"))
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    jobs.start("pre-capture", command, {"handle": 321, "process_id": 12},
        {"image_transport": "supported", "current_vision": "supported"})
    end = monotonic() + 3
    while monotonic() < end:
        snapshot = jobs.get("pre-capture")
        if snapshot["status"] == "failed":
            break
        sleep(.005)
    else:
        pytest.fail("capture failure did not terminate")
    try:
        yield jobs, snapshot, state, captures
    finally:
        jobs.close()


def test_real_job_capture_failure_proves_zero_input_before_grounding(pre_capture):
    jobs, snapshot, state, captures = pre_capture
    result = snapshot["result"]
    assert result["action_executed"] is False
    assert snapshot["action_executed"] is False
    assert snapshot["dispatch_attempts"] == [] and snapshot["dispatch_in_progress"] is False
    assert result["steps"][0]["status"] == "not_dispatched"
    local = result["steps"][0]["receipt"]
    assert local["contract_version"] == "pre_grounding_capture_failure.v1"
    assert local["error"] == {"code": "capture_window_occluded", "type": "CaptureVisibilityError"}
    assert local["capture"] is None and "response" not in local
    assert captures == [True] and "route" not in state.events
    assert not list(jobs.store.session_root.glob("grounding/*.json"))
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    receipt = {"status": "returned", "command": command, "result": result}
    assert original_input_status(receipt, command, succeeded=False,
        action_executed=False, target_identity=TARGET) == "failed"


@pytest.mark.parametrize("damage", ["proof", "request", "identity", "geometry", "capture", "response", "unclosed", "extra_dispatch"])
def test_damaged_capture_boundary_cannot_settle_from_summary_false(pre_capture, damage):
    _, snapshot, _, _ = pre_capture
    result = deepcopy(snapshot["result"])
    assert result["action_executed"] is False
    local = result["steps"][0]["receipt"]
    if damage == "proof": local["pre_dispatch_failure"]["input_dispatch_started"] = True
    elif damage == "request": local["request"]["goal"] = "another target"
    elif damage == "identity": local["target_identity"]["process_create_time"] += 1
    elif damage == "geometry": local["target_window_geometry"]["rect"][0] += 1
    elif damage == "capture": local["capture"] = {"image_path": "foreign.png"}
    elif damage == "response": local["response"] = {"success": True}
    elif damage == "unclosed": local["local_input_scope_closed"] = False
    else: result["steps"].append({"name": "type", "status": "dispatching", "action_executed": None})
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    receipt = {"status": "returned", "command": command, "result": result}
    assert original_input_status(receipt, command, succeeded=False,
        action_executed=False, target_identity=TARGET) == "unknown"


@pytest.mark.parametrize("async_terminal", [False, True])
def test_capture_failure_cancel_unlocks_new_plan_without_replay(pre_capture, tmp_path, monkeypatch, async_terminal):
    from app.core.json_snapshot import write_json_snapshot
    jobs, snapshot, state, captures = pre_capture
    result = snapshot["result"]
    assert result["action_executed"] is False
    (tmp_path / "queue").mkdir()
    s, pending, path, calls = queued(tmp_path / "queue", monkeypatch, result)
    command = deepcopy(pending["suggested_command"])
    payload = {"status": "returned", "command": command, "result": deepcopy(result)}
    if async_terminal:
        command_id = pending["execution_request_id"]
        payload["result"] = {"contract_version": "agent_command.v1", "command_id": command_id,
            "status": "running", "action_executed": False, "automatic_retry_allowed": False}
        terminal = deepcopy(snapshot)
        terminal["command_id"] = command_id
        write_json_snapshot(s.session / "agent-commands" / (command_id + ".json"), terminal)
    write_json_snapshot(path, payload)
    original = path.read_bytes()
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-pre-capture")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["pending"] is None
    assert final["history"][0]["original_input_status"] == "failed"
    assert final["history"][0]["action_executed"] is False
    source = s.runtime.backend._source(final)["plan"]
    new = s.runtime.control({"action": "start", "plan": source}, "after-pre-capture")
    assert new["run_id"] != s.run_id
    assert path.read_bytes() == original and calls == [] and captures == [True]
    assert "route" not in state.events


@pytest.mark.parametrize("where", ["capture", "route"])
def test_same_visibility_exception_outside_proxy_capture_is_unknown(timed_scene, where):
    from app.execution.input_sequence import run_input_sequence
    co, state, *_ = timed_scene
    state.error_at = where
    state.failure = CaptureVisibilityError("capture_window_occluded")
    result = run_input_sequence(co, {"handle": 321, "process_id": 12}, REQUEST)
    assert result["action_executed"] is None
    assert result["steps"][0]["status"] == "result_unknown"
    assert "receipt" not in result["steps"][0]
    assert state.events.count("route") == (where == "route")
