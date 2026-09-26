"""Agent 命令暂停与恢复的单宿主契约测试。"""

from hashlib import sha256
from threading import Event
from time import monotonic, sleep

from PIL import Image
import pytest

from app.vision.agent_command_jobs import AgentCommandError, AgentCommandJobs
from app.vision.grounding_handoff import GroundingHandoffError, GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig


class _Owner:
    def call(self, callback):
        return callback()


class _Coordinator:
    def __init__(self):
        self._owner = _Owner()
        self.calls = []

    def execute_local_step(self, **kwargs):
        self.calls.append(kwargs)
        return {"phase": "returned", "response": {"success": True,
            "data": {"result": {"execution_path": {"action_executed": True}}}},
            "observation": {"status": "captured", "capture": {"sha256": "after"}},
            "action_executed": True}


@pytest.fixture
def env(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "white").save(frame)
    capture = {"image_path": str(frame), "sha256": sha256(frame.read_bytes()).hexdigest(),
        "window_identity": {"handle": 100, "process_id": 200, "process_create_time": 1.5}}
    store = GroundingHandoffStore(tmp_path, owner_id="connection-1")
    coordinator = _Coordinator()
    jobs = AgentCommandJobs(coordinator, store, lambda: capture,
        RecognitionSourceConfig(source="agent_current"))
    yield jobs, coordinator, store
    jobs.close()


def _wait(jobs, command_id, status):
    end = monotonic() + 3
    while monotonic() < end:
        state = jobs.get(command_id)
        if state["status"] == status:
            return state
        sleep(.01)
    pytest.fail(f"{command_id} did not reach {status}: {state}")


def _found(pending):
    return {"schema_version": "grounding.v1", "request_id": pending["request_id"],
        "capture_id": pending["capture"]["capture_id"], "status": "found",
        "coordinate_space": "capture_image_pixels", "image_size": {"width": 100, "height": 80},
        "candidates": [{"id": "one", "label": "Search",
            "bbox": {"x": 10, "y": 20, "width": 50, "height": 20},
            "click_point": {"x": 35, "y": 30}, "evidence_source": "agent_visual"}],
        "selected_candidate_id": "one"}


def _start(jobs, command_id="job-1"):
    return jobs.start(command_id, {"kind": "step", "operation": "execute_recognition_plan",
        "request": {"goal": "Search"}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})


def test_step_waits_for_explicit_resume_and_no_status_replay(env):
    jobs, coordinator, store = env
    assert _start(jobs)["status"] == "running"
    state = _wait(jobs, "job-1", "awaiting_grounding")
    pending = state["pending_grounding"]
    assert pending["output_schema"]["properties"]["schema_version"]
    assert state["observation"]["capture"]["capture_id"] == pending["capture"]["capture_id"]
    assert jobs.get("job-1") == state
    assert coordinator.calls == []
    store.resolve(pending["request_id"], _found(pending))
    resumed = jobs.resume("job-1", pending["request_id"], "exec-1")
    assert resumed["status"] == "running"
    assert resumed["observation"] == {"status": "unavailable", "reason": "action_in_progress"}
    assert _wait(jobs, "job-1", "completed")["result"]["response"]["success"] is True
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0]["grounding_target"].goal == "Search"
    assert store.get(pending["request_id"])["phase"] == "completed"
    with pytest.raises(AgentCommandError, match="not_awaiting"):
        jobs.resume("job-1", pending["request_id"], "exec-2")


def test_duplicate_second_active_and_cancel(env):
    jobs, coordinator, store = env
    _start(jobs)
    state = _wait(jobs, "job-1", "awaiting_grounding")
    with pytest.raises(AgentCommandError, match="command_active"):
        _start(jobs, "job-2")
    with pytest.raises(AgentCommandError, match="already_exists"):
        _start(jobs)
    with pytest.raises(AgentCommandError, match="mismatch"):
        jobs.resume("job-1", "wrong", "exec-1")
    assert jobs.cancel("job-1")["cancel_requested"] is True
    assert _wait(jobs, "job-1", "cancelled")["automatic_retry_allowed"] is False
    assert store.get(state["pending_grounding"]["request_id"])["phase"] == "cancelled"
    assert coordinator.calls == []


def test_source_eligibility_and_existing_disk_id(env):
    jobs, _, store = env
    with pytest.raises(AgentCommandError, match="capability_unknown"):
        jobs.start("bad", {"kind": "step", "operation": "execute_recognition_plan",
            "request": {"goal": "Search"}}, {"handle": 100, "process_id": 200}, {})
    assert not (store.session_root / "agent-commands" / "bad.json").exists()
    _start(jobs)
    _wait(jobs, "job-1", "awaiting_grounding")
    jobs.cancel("job-1")
    jobs.close()
    reopened = AgentCommandJobs(_Coordinator(), store, lambda: {},
        RecognitionSourceConfig(source="agent_current"))
    with pytest.raises(AgentCommandError, match="already_exists"):
        _start(reopened)


def test_expired_pending_never_resumes(env):
    jobs, _, store = env
    now = [1000.0]
    store._clock = lambda: now[0]
    store._ttl = 1
    _start(jobs)
    state = _wait(jobs, "job-1", "awaiting_grounding")
    now[0] = 1002.0
    _wait(jobs, "job-1", "failed")
    with pytest.raises(AgentCommandError, match="not_awaiting"):
        jobs.resume("job-1", state["pending_grounding"]["request_id"], "exec-1")


def test_two_recognitions_and_intervening_input_once(env, monkeypatch):
    jobs, coordinator, store = env
    import app.vision.agent_command_jobs as module
    def sequence(proxy, target, request, *, persist, **kwargs):
        for goal in ("First", "Second"):
            proxy.execute_local_step(target_window_handle=100, target_process_id=200,
                operation="execute_recognition_plan", request={"goal": goal},
                focus_target=object())
            persist({"status": "running", "phase": goal, "action_executed": True})
            if goal == "First":
                proxy.execute_local_step(target_window_handle=100, target_process_id=200,
                    operation="type_text", request={"text": "once"})
        return {"status": "completed", "action_executed": True}
    monkeypatch.setattr(module, "run_input_sequence", sequence)
    jobs.start("job-1", {"kind": "input_sequence", "request": {"field_goal": "First",
        "text": "once", "submit_search": False}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    first = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.resolve(first["request_id"], _found(first))
    jobs.resume("job-1", first["request_id"], "exec-1")
    end = monotonic() + 3
    while monotonic() < end:
        state = jobs.get("job-1")
        if state["status"] == "awaiting_grounding" and state["pending_grounding"]["request_id"] != first["request_id"]:
            break
        sleep(.01)
    else:
        pytest.fail("second recognition did not suspend")
    second = state["pending_grounding"]
    assert second["capture"]["capture_id"] != first["capture"]["capture_id"]
    store.resolve(second["request_id"], _found(second))
    jobs.resume("job-1", second["request_id"], "exec-2")
    _wait(jobs, "job-1", "completed")
    assert [c["operation"] for c in coordinator.calls] == [
        "execute_recognition_plan", "type_text", "execute_recognition_plan"]
    assert coordinator.calls[0]["focus_target"] is not None
    assert [c["request"].get("text") for c in coordinator.calls if c["operation"] == "type_text"] == ["once"]


def test_returned_interrupted_result_is_failed_without_replay(env, monkeypatch):
    jobs, coordinator, _ = env
    import app.vision.agent_command_jobs as module
    def interrupted(proxy, target, request, *, persist, **kwargs):
        proxy.execute_local_step(target_window_handle=100, target_process_id=200,
            operation="type_text", request={"text": "once"})
        partial = {"status": "interrupted", "action_executed": True,
            "completed_steps": ["type"], "observation": {"status": "unavailable"}}
        persist(partial)
        return partial
    monkeypatch.setattr(module, "run_input_sequence", interrupted)
    jobs.start("job-1", {"kind": "input_sequence", "request": {"field_goal": "First",
        "text": "once", "submit_search": False}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    state = _wait(jobs, "job-1", "failed")
    assert state["result"]["completed_steps"] == ["type"]
    assert state["action_executed"] is True
    assert len(coordinator.calls) == 1


def test_execution_exception_is_persisted_as_unknown(env):
    jobs, coordinator, store = env
    def fail(**kwargs):
        raise RuntimeError("dispatch_unknown")
    coordinator.execute_local_step = fail
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.resolve(pending["request_id"], _found(pending))
    jobs.resume("job-1", pending["request_id"], "exec-1")
    assert _wait(jobs, "job-1", "failed")["automatic_retry_allowed"] is False
    execution = store.get(pending["request_id"])
    assert execution["phase"] == "completed"
    assert execution["execution_result"]["phase"] == "result_unknown"
    assert execution["input_attempted"] is True


def test_close_cancels_waiting_worker(env):
    jobs, _, _ = env
    _start(jobs)
    _wait(jobs, "job-1", "awaiting_grounding")
    assert jobs.close(timeout=1) is True
    assert jobs.active is False
    assert jobs.get("job-1")["status"] == "cancelled"


def test_close_reports_running_worker_not_cleaned_up(env):
    jobs, coordinator, store = env
    entered, release = Event(), Event()
    original = coordinator.execute_local_step
    def blocking(**kwargs):
        entered.set()
        release.wait(2)
        return original(**kwargs)
    coordinator.execute_local_step = blocking
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.resolve(pending["request_id"], _found(pending))
    jobs.resume("job-1", pending["request_id"], "exec-1")
    assert entered.wait(1)
    assert jobs.get("job-1")["dispatch_in_progress"] is True
    assert jobs.close(timeout=0) is False
    assert jobs.active is True
    assert jobs.get("job-1")["cancel_requested"] is True
    release.set()
    assert jobs.close(timeout=2) is True
    assert jobs.get("job-1")["status"] == "cancelled"


def test_nonrecognition_receipt_and_exception_preserve_cumulative_evidence(env, monkeypatch):
    jobs, coordinator, _ = env
    import app.vision.agent_command_jobs as module
    def sequence(proxy, target, request, *, persist, **kwargs):
        proxy.execute_local_step(target_window_handle=100, target_process_id=200,
            operation="type_text", request={"text": "once"})
        assert jobs.get("job-1")["action_executed"] is True
        assert jobs.get("job-1")["observation"]["capture"]["sha256"] == "after"
        persist({"status": "running", "action_executed": False,
            "observation": {"status": "captured", "capture": {"sha256": "after"}}})
        assert jobs.get("job-1")["action_executed"] is True
        proxy.execute_local_step(target_window_handle=100, target_process_id=200,
            operation="press_key", request={"key": "Tab"})
    monkeypatch.setattr(module, "run_input_sequence", sequence)
    original = coordinator.execute_local_step
    def dispatch(**kwargs):
        if kwargs["operation"] == "press_key":
            raise RuntimeError("dispatch_unknown")
        return original(**kwargs)
    coordinator.execute_local_step = dispatch
    jobs.start("job-1", {"kind": "input_sequence", "request": {"field_goal": "First",
        "text": "once", "submit_search": False}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    state = _wait(jobs, "job-1", "failed")
    assert state["action_executed"] is True
    assert state["observation"]["status"] == "unavailable"


def test_cancel_during_input_keeps_later_progress(env, monkeypatch):
    jobs, coordinator, _ = env
    import app.vision.agent_command_jobs as module
    entered, release = Event(), Event()
    def sequence(proxy, target, request, *, persist, **kwargs):
        entered.set()
        release.wait(2)
        persist({"status": "interrupted", "action_executed": True,
            "observation": {"status": "captured", "capture": {"sha256": "late"}}})
        return {"status": "interrupted", "action_executed": True,
            "observation": {"status": "captured", "capture": {"sha256": "late"}}}
    monkeypatch.setattr(module, "run_input_sequence", sequence)
    jobs.start("job-1", {"kind": "input_sequence", "request": {"field_goal": "First",
        "text": "once", "submit_search": False}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    assert entered.wait(1)
    jobs.cancel("job-1")
    release.set()
    state = _wait(jobs, "job-1", "cancelled")
    assert state["progress"]["observation"]["capture"]["sha256"] == "late"
    assert state["action_executed"] is True


def test_step_preserves_observation_options(env):
    jobs, coordinator, store = env
    jobs.start("job-1", {"kind": "step", "operation": "execute_recognition_plan",
        "request": {"goal": "Search"},
        "observation_condition": {"kind": "uia_text", "text": "Done"}},
        {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.resolve(pending["request_id"], _found(pending))
    jobs.resume("job-1", pending["request_id"], "exec-1")
    _wait(jobs, "job-1", "completed")
    assert coordinator.calls[0]["observation_wait_ms"] is None
    assert coordinator.calls[0]["observation_condition"] == {"kind": "uia_text", "text": "Done"}


def test_external_grounding_cancel_stops_wait(env):
    jobs, coordinator, store = env
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.cancel(pending["request_id"])
    state = _wait(jobs, "job-1", "failed")
    assert state["error"]["code"] == "request_cancelled"
    assert coordinator.calls == []


@pytest.mark.parametrize("grounding_status", ["absent", "ambiguous", "unsupported", "error"])
def test_nonready_grounding_result_ends_command_without_input(env, grounding_status):
    jobs, coordinator, store = env
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    result = _found(pending)
    result["status"] = grounding_status
    result["selected_candidate_id"] = None
    if grounding_status == "ambiguous":
        result["candidates"].append({**result["candidates"][0], "id": "two"})
    else:
        result["candidates"] = []
    store.resolve(pending["request_id"], result)
    state = _wait(jobs, "job-1", "failed")
    assert state["error"]["code"] == "request_" + grounding_status
    assert coordinator.calls == []


def test_cancel_after_claim_before_worker_wakeup_finishes_without_input(env):
    jobs, coordinator, store = env
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.resolve(pending["request_id"], _found(pending))
    # 锁住调度点，确保先占用、再取消，worker 尚未收到恢复执行机会。
    with jobs._condition:
        jobs.resume("job-1", pending["request_id"], "exec-1")
        jobs.cancel("job-1")
    _wait(jobs, "job-1", "cancelled")
    execution = store.get(pending["request_id"])
    assert execution["phase"] == "completed"
    assert execution["input_attempted"] is False
    assert coordinator.calls == []


def test_resume_running_never_exposes_pending_before_image_as_after(env):
    jobs, coordinator, store = env
    entered, release = Event(), Event()
    original = coordinator.execute_local_step
    def blocking(**kwargs):
        entered.set()
        release.wait(2)
        return original(**kwargs)
    coordinator.execute_local_step = blocking
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    assert jobs.get("job-1")["observation"]["capture"]["capture_id"] == pending["capture"]["capture_id"]
    store.resolve(pending["request_id"], _found(pending))
    jobs.resume("job-1", pending["request_id"], "exec-1")
    assert entered.wait(1)
    running = jobs.get("job-1")
    assert running["status"] == "running"
    assert running["observation"] == {"status": "unavailable", "reason": "action_in_progress"}
    release.set()
    done = _wait(jobs, "job-1", "completed")
    assert done["observation"]["capture"]["sha256"] == "after"
    assert done["action_executed"] is True


def test_second_nonrecognition_dispatch_clears_previous_after_image(env, monkeypatch):
    jobs, coordinator, _ = env
    import app.vision.agent_command_jobs as module
    entered, release = Event(), Event()
    original = coordinator.execute_local_step
    def blocking(**kwargs):
        if kwargs["operation"] == "press_key":
            entered.set()
            release.wait(2)
        return original(**kwargs)
    coordinator.execute_local_step = blocking
    def sequence(proxy, target, request, *, persist, **kwargs):
        proxy.execute_local_step(target_window_handle=100, target_process_id=200,
            operation="type_text", request={"text": "once"})
        proxy.execute_local_step(target_window_handle=100, target_process_id=200,
            operation="press_key", request={"key": "Tab"})
        return {"status": "completed", "action_executed": True,
            "observation": {"status": "captured", "capture": {"sha256": "after"}}}
    monkeypatch.setattr(module, "run_input_sequence", sequence)
    jobs.start("job-1", {"kind": "input_sequence", "request": {"field_goal": "First",
        "text": "once", "submit_search": False}}, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    assert entered.wait(1)
    assert jobs.get("job-1")["observation"] == {
        "status": "unavailable", "reason": "action_in_progress"}
    release.set()
    assert _wait(jobs, "job-1", "completed")["observation"]["status"] == "captured"


def test_cancel_while_grounding_target_constructs_prevents_native_dispatch(env, monkeypatch):
    jobs, coordinator, store = env
    import app.vision.agent_command_jobs as module
    entered, release = Event(), Event()
    original = module.AgentGroundingTarget
    def paused_constructor(claimed):
        entered.set()
        release.wait(2)
        return original(claimed)
    monkeypatch.setattr(module, "AgentGroundingTarget", paused_constructor)
    _start(jobs)
    pending = _wait(jobs, "job-1", "awaiting_grounding")["pending_grounding"]
    store.resolve(pending["request_id"], _found(pending))
    jobs.resume("job-1", pending["request_id"], "exec-1")
    assert entered.wait(1)
    assert jobs.get("job-1")["dispatch_in_progress"] is False
    assert jobs.cancel("job-1")["cancel_requested"] is True
    release.set()
    state = _wait(jobs, "job-1", "cancelled")
    assert state["dispatch_in_progress"] is False
    execution = store.get(pending["request_id"])
    assert execution["phase"] == "completed"
    assert execution["execution_result"]["phase"] == "cancelled_before_dispatch"
    assert execution["input_attempted"] is False
    assert coordinator.calls == []
