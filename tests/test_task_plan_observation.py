"""有限观察跨原运行器 tick；离线时钟、采集和 HTTP 不访问桌面。"""
from copy import deepcopy
from hashlib import sha256
import importlib
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_contract import validate_task_plan
from tests.test_task_plan_adaptive_review import OfflineAssessment, adaptive_plan, review_request
from tests.test_task_plan_runner import complete_original, scene


def observing_plan(count=2):
    value = adaptive_plan(count=count)
    value["steps"][0]["verification"]["wait_policy"] = {
        "loading_condition": "A loading indicator is visible", "completion_excludes_loading": True}
    return value


class Clock:
    seconds = 0.0

    def now_ns(self):
        return int(self.seconds * 1_000_000_000)


class ObservingAssessment(OfflineAssessment):
    def __init__(self, *, final="continue", slow=0.0, clock=None):
        super().__init__()
        self.final, self.slow, self.clock = final, slow, clock

    def evaluate(self, **binding):
        value = super().evaluate(**binding)
        if self.clock:
            self.clock.seconds += self.slow
        value.update(disposition="observe" if len(self.calls) == 1 else self.final,
            verdict="uncertain" if len(self.calls) == 1 or self.final != "continue" else "success",
            adopted=len(self.calls) > 1 and self.final == "continue",
            assessment_context=deepcopy(binding.get("assessment_context")))
        return value


def observation_scene(tmp_path, monkeypatch, *, service=None, capture_slow=0.0, unchanged=False, source=None):
    service = service or ObservingAssessment()
    s = scene(tmp_path, monkeypatch, source=source or observing_plan(), decision=service)
    original = complete_original(s, native=False)
    original.receipt["result"]["observation"]["capture"].update(
        image_size={"width": 80, "height": 60}, window_rect=[0, 0, 80, 60])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    module = importlib.import_module("app.execution.task_plan_observation")
    clock = Clock()
    monkeypatch.setattr(module, "now_ns", clock.now_ns)
    calls = []
    def capture(coordinator, **kwargs):
        calls.append(deepcopy({key: value for key, value in kwargs.items() if key != "cancelled"}))
        if kwargs["cancelled"]():
            raise ValueError("task_plan_observation_cancelled")
        clock.seconds += capture_slow
        path = tmp_path / "captures" / (kwargs["observation_id"] + ".png")
        Image.new("RGB", (80, 60), "white" if unchanged else (10 * len(calls), 0, 0)).save(path)
        frame = {"capture_id": kwargs["observation_id"], "image_path": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(), "role": "observation",
            "window_identity": deepcopy(s.target)}
        return {"observation_id": kwargs["observation_id"], "frame": frame,
            "capture_elapsed_ms": capture_slow * 1000}
    monkeypatch.setattr(module, "capture_followup", capture)
    service.clock = clock
    return s, original, clock, calls


def test_v2_wait_policy_is_frozen_in_review_context_and_v1_rejects():
    from app.execution.task_plan_review import review_context
    value = observing_plan()
    assert validate_task_plan(value) == value
    context = review_context(value, value["steps"][0], source_id="source", source_sha256="a" * 64)
    assert context["wait_policy"] == value["steps"][0]["verification"]["wait_policy"]
    value["schema_version"] = "task_plan.v1"
    with pytest.raises(ValueError):
        validate_task_plan(value)


@pytest.mark.parametrize("bad", [False, {}, {"loading_condition": " ", "completion_excludes_loading": True},
    {"loading_condition": "Loading", "completion_excludes_loading": 1}])
def test_wait_policy_strictly_rejects_malformed(bad):
    value = observing_plan()
    value["steps"][0]["verification"]["wait_policy"] = bad
    with pytest.raises(ValueError):
        validate_task_plan(value)


def test_two_observations_cross_ticks_reuse_ticket_and_only_final_evidence_gets_second_api(tmp_path, monkeypatch):
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch)
    first = s.runtime.tick(force=True)
    assert first["observation_pending"] is True and "review_packet" not in first
    assert first["pending"]["execution_request_id"] == original.command_id and first["history"] == []
    assert len(s.co._decision_service.calls) == 1 and captures == []
    for _ in range(2):
        assert s.runtime.tick(force=True)["observation_pending"] is True
        s.runtime.control({"action": "status", "run_id": s.run_id}, "readonly-observation-status")
    clock.seconds = .6
    assert s.runtime.tick(force=True)["observation_pending"] is True
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 1
    clock.seconds = 1.6
    advanced = s.runtime.tick(force=True)
    assert len(captures) == 2 and len(s.co._decision_service.calls) == 2
    assert advanced["history"][0]["execution_request_id"] == original.command_id
    assert advanced["pending"]["step_id"] == "step-1"
    calls = s.co._decision_service.calls
    assert calls[0]["assessment_context"]["assessment_round"] == 0
    assert calls[1]["assessment_context"]["assessment_round"] == 2
    assert [f["role"] for f in calls[1]["frames"]] == ["after", "observation"]
    assert calls[1]["frames"][0]["sha256"] == original.capture["sha256"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


def test_unchanged_new_pixels_handoff_without_second_api_and_bound_review_continue(tmp_path, monkeypatch):
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, unchanged=True)
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    result = s.runtime.tick(force=True)
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 1
    packet = result["review_packet"]
    assert packet["schema"] == "review_packet.v2" and packet["assessment_round"] == 2
    assert result.get("observation_pending") is not True and result["review_required"] is True
    request = review_request(s, result, original)
    reviewed = s.runtime.control(request, "observed-main-review")
    assert reviewed["status"] == "ready" and len(list(tmp_path.glob("commands/*.json"))) == 1
    resumed = s.runtime.control({"action": "continue", "run_id": s.run_id,
        "wait_id": result["wait"]["wait_id"]}, "observed-main-continue")
    assert resumed["pending"] is None
    resumed = s.runtime.tick(force=True)
    assert resumed["pending"]["step_id"] == "step-1" and len(list(tmp_path.glob("commands/*.json"))) == 2


@pytest.mark.parametrize("late", ["first_api", "before_capture", "capture", "second_api"])
def test_twelve_second_budget_includes_initial_api_and_rejects_all_late_adoption(tmp_path, monkeypatch, late):
    service = ObservingAssessment(slow=12.1 if late == "first_api" else 0)
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, service=service,
        capture_slow=12 if late == "capture" else 0)
    result = s.runtime.tick(force=True)
    if late != "first_api":
        clock.seconds = 12.1 if late == "before_capture" else .6 if late == "capture" else 1.6
        if late == "second_api":
            service.slow = 12
        result = s.runtime.tick(force=True)
    assert result.get("observation_pending") is not True and result["review_required"] is True
    assert "budget" in result["review_packet"]["reason"]
    assert result["pending"]["execution_request_id"] == original.command_id and result["history"] == []
    assert len(service.calls) == (2 if late == "second_api" else 1)
    assert len(captures) == (1 if late in {"capture", "second_api"} else 0)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    clock.seconds += 100
    reviewed = s.runtime.control(review_request(s, result, original), "late-bound-main-review")
    assert reviewed["status"] == "ready" and len(list(tmp_path.glob("commands/*.json"))) == 1


def test_first_late_tick_uses_slot_two_once_and_slow_capture_skips_later_slot(tmp_path, monkeypatch):
    s, _, clock, captures = observation_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    result = s.runtime.tick(force=True)
    assert len(captures) == 1 and s.co._decision_service.calls[-1]["assessment_context"]["assessment_round"] == 2
    assert len(result["history"]) == 1
    other = tmp_path / "slow-capture"
    other.mkdir()
    s, _, clock, captures = observation_scene(other, monkeypatch, capture_slow=1.2)
    s.runtime.tick(force=True)
    clock.seconds = .6
    result = s.runtime.tick(force=True)
    assert len(captures) == 1 and s.co._decision_service.calls[-1]["assessment_context"]["assessment_round"] == 1
    assert len(result["history"]) == 1


@pytest.mark.parametrize("kind", ["capture", "assessment", "clock"])
def test_unknown_claim_or_foreign_clock_handoff_never_repeats_capture_or_api(tmp_path, monkeypatch, kind):
    from app.execution import task_plan_observation as module
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch)
    if kind == "assessment":
        evaluate = s.co._decision_service.evaluate
        def interrupted(**binding):
            evaluate(**binding)
            raise KeyboardInterrupt("synthetic interrupted provider claim")
        monkeypatch.setattr(s.co._decision_service, "evaluate", interrupted)
        with pytest.raises(KeyboardInterrupt):
            s.runtime.tick(force=True)
        monkeypatch.setattr(s.co._decision_service, "evaluate", evaluate)
    else:
        s.runtime.tick(force=True)
        if kind == "capture":
            module.ObservationLedger(s.runtime.backend, original.command_id).append("capture_claimed", {
                "round": 1, "claimed_ns": clock.now_ns()})
        else:
            monkeypatch.setattr(module, "CLOCK_ID", "another-host-clock")
    clock.seconds = .6
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and kind in result["review_packet"]["reason"]
    assert len(s.co._decision_service.calls) == 1 and captures == []
    assert result["pending"]["execution_request_id"] == original.command_id
    assert s.runtime.tick(force=True) is None


def test_window_birth_drift_zero_new_capture_and_queued_cancel_still_settles_original(tmp_path, monkeypatch):
    from tests.test_task_plan_queued_cancel import queue_cancel
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    s.target["process_create_time"] += 1
    clock.seconds = .6
    result = s.runtime.tick(force=True)
    assert result["review_packet"]["reason"] == "task_plan_observation_window_changed" and captures == []
    assert len(s.co._decision_service.calls) == 1
    s.target["process_create_time"] -= 1
    command = queue_cancel(s)
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "cancelled" and len(terminal["history"]) == 1
    assert terminal["history"][0]["execution_request_id"] == original.command_id
    assert terminal["history"][0]["action_executed"] is True and len(captures) == 0


def test_queued_cancel_during_observation_does_not_capture_or_replay_input(tmp_path, monkeypatch):
    from tests.test_task_plan_queued_cancel import queue_cancel
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    command = queue_cancel(s)
    clock.seconds = .6
    waiting = s.runtime.tick(force=True)
    assert waiting["pending"]["execution_request_id"] == original.command_id and captures == []
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    assert s.runtime.tick(force=True)["runner_state"] == "cancelled"
    assert len(s.co._decision_service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2


def test_real_capture_helper_receives_dynamic_budget_and_maintained_screenshot_boundary(tmp_path, monkeypatch):
    from app.execution import task_plan_observation as module, task_plan_observation_capture as helper
    from app.learning_memory import memory_observation
    s, original, clock, _ = observation_scene(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "capture_followup", helper.capture_followup)
    s.co._owner = SimpleNamespace(call=lambda callback: callback())
    s.co._windows = lambda: SimpleNamespace(get_bound_window=lambda: SimpleNamespace(
        handle=s.target["handle"], process_id=s.target["process_id"],
        rect=SimpleNamespace(left=0, top=0, right=80, bottom=60)))
    s.co._runtime_output_root = tmp_path / "runtime"
    calls = []
    class Reader:
        def __init__(self, **kwargs):
            pass
        def read_identity(self, handle):
            return {"status": "observed", "target_window_handle": handle,
                "process_id": s.target["process_id"], "process_create_time": s.target["process_create_time"],
                "executable_path": "C:\\Fixture\\fixture.exe"}
    class Screenshot:
        def __init__(self, **kwargs):
            self.directory = kwargs["capture_dir"]
        def capture_window(self, **kwargs):
            assert kwargs == {"focus_window": False, "purpose": "memory-current-observation"}
            calls.append("read_capture")
            self.directory.mkdir(parents=True)
            path = self.directory / "fresh.png"
            Image.new("RGB", (80, 60), "red").save(path)
            return {"image_path": str(path), "roi": None}
    class ForbiddenTree:
        def __init__(self, **kwargs):
            raise AssertionError("followup must not read a UIA tree")
    monkeypatch.setattr(memory_observation, "WindowsNativeIdentityReader", Reader)
    monkeypatch.setattr(memory_observation, "ScreenshotService", Screenshot)
    monkeypatch.setattr(memory_observation, "WindowsUIAProvider", ForbiddenTree)
    monkeypatch.setattr(memory_observation, "_window_class", lambda handle: "Fixture")
    monkeypatch.setattr(helper, "monotonic", lambda: clock.seconds)
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    result = s.runtime.tick(force=True)
    assert calls == ["read_capture"] and len(result["history"]) == 1
    assert original.after.read_bytes() == Path(s.co._decision_service.calls[0]["frames"][0]["image_path"]).read_bytes()


def test_reused_followup_identity_cannot_be_adopted(tmp_path, monkeypatch):
    from app.execution import task_plan_observation as module
    s, _, clock, captures = observation_scene(tmp_path, monkeypatch)
    capture = module.capture_followup
    previous = []
    def reused(*args, **kwargs):
        if previous:
            return deepcopy(previous[0])
        value = capture(*args, **kwargs)
        previous.append(value)
        return value
    monkeypatch.setattr(module, "capture_followup", reused)
    s.runtime.tick(force=True)
    clock.seconds = .6
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    result = s.runtime.tick(force=True)
    assert result["review_packet"]["reason"] == "task_plan_observation_capture_reused"
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 1


def test_real_runtime_client_observation_pending_only_polls_and_review_callback_occurs_once(tmp_path, monkeypatch):
    import asyncio
    from tests.test_task_plan_client import client
    service = ObservingAssessment(final="review_required")
    s, _, clock, captures = observation_scene(tmp_path, monkeypatch, service=service)
    s.runtime.tick(force=True)
    class Session:
        async def call_tool(self, name, args):
            assert name == "instant_run"
            value = {"request_id": args["request_id"], "status": "returned",
                "result": s.runtime.control(args["command"]["request"], args["request_id"])}
            return SimpleNamespace(structuredContent=value, is_error=False)
    opened, events = client(tmp_path, Session()), []
    async def status(request_id):
        return await opened.run_plan(request_id, {"kind": "task_plan", "request": {
            "action": "status", "run_id": s.run_id}}, event_callback=events.append, total_timeout=0)
    assert asyncio.run(status("observation-status-one"))["client_state"] == "observation_pending"
    assert events == []
    clock.seconds = 1.6
    s.runtime.tick(force=True)
    assert asyncio.run(status("observation-review-status"))["client_state"] == "review_required"
    asyncio.run(status("observation-review-repeat"))
    assert len(events) == 1 and len(captures) == 1 and len(service.calls) == 2


@pytest.mark.parametrize("final", ["continue", "review_required"])
def test_real_v2_service_provider_runner_client_binds_final_pixels_and_never_replays(
        tmp_path, monkeypatch, final):
    import asyncio
    import httpx
    import json
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    from tests.test_openai_decisions import reply
    from tests.test_task_plan_adaptive_review import CONDITION
    from tests.test_task_plan_client import client
    monkeypatch.setenv("DECISION_OBSERVATION_TEST_KEY", "synthetic-offline-only")
    requests = []
    def handle(request):
        requests.append(request)
        initial = len(requests) == 1
        body = reply(.01 if initial else .97)
        body["answers"].extend([
            {"type": "predicate", "name": "needs_agent_review", "probability": .97 if not initial and final == "review_required" else .01},
            {"type": "predicate", "name": "still_progressing", "probability": .97 if initial else .01}])
        return httpx.Response(200, json=body)
    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        api_key_env="DECISION_OBSERVATION_TEST_KEY", auto_conditions=[CONDITION])
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        service = DecisionService(tmp_path, profile=profile, provider=OpenAIDecisionsProvider(
            api_key_env="DECISION_OBSERVATION_TEST_KEY", client=transport))
        s, original, clock, captures = observation_scene(tmp_path, monkeypatch, service=service,
            source=observing_plan(count=1))
        s.runtime.tick(force=True)
        class Session:
            async def call_tool(self, name, args):
                assert name == "instant_run"
                return SimpleNamespace(structuredContent={"request_id": args["request_id"], "status": "returned",
                    "result": s.runtime.control(args["command"]["request"], args["request_id"])}, is_error=False)
        opened, events = client(tmp_path, Session()), []
        async def control(request_id, request):
            return await opened.run_plan(request_id, {"kind": "task_plan", "request": request},
                event_callback=events.append, total_timeout=0)
        status = {"action": "status", "run_id": s.run_id}
        assert asyncio.run(control("real-observation-pending", status))["client_state"] == "observation_pending"
        assert len(requests) == 1 and events == []
        clock.seconds = .6
        s.runtime.tick(force=True)
        assert asyncio.run(control("real-observation-pending-again", status))["client_state"] == "observation_pending"
        assert len(requests) == 1 and events == []
        clock.seconds = 1.6
        result = s.runtime.tick(force=True)
        projected = asyncio.run(control("real-final-observation-status", status))
        if final == "review_required":
            assert projected["client_state"] == "review_required" and len(events) == 1
            asyncio.run(control("real-final-observation-repeat", status))
            assert len(events) == 1
            clock.seconds = 100
            reviewed = asyncio.run(control("real-bound-final-review", review_request(s, result, original)))
            assert reviewed["client_state"] == "continue_required"
            resumed = asyncio.run(control("real-bound-final-continue", {"action": "continue", "run_id": s.run_id,
                "wait_id": result["wait"]["wait_id"]}))
            assert resumed["client_state"] == "terminal"
        else:
            assert projected["client_state"] == "terminal" and events == []
        assert len(requests) == len(captures) == 2
        payloads = [json.loads(request.content) for request in requests]
        assert len([part for part in payloads[0]["input"][0]["content"] if part["type"] == "input_image"]) == 1
        assert len([part for part in payloads[1]["input"][0]["content"] if part["type"] == "input_image"]) == 2
        state = s.runtime.backend.status(s.run_id)
        assert state["status"] == "completed" and len(state["history"]) == 1
        assert state["history"][0]["execution_request_id"] == original.command_id
        assert state["history"][0]["action_executed"] is True
        assert len(list(tmp_path.glob("commands/*.json"))) == 1
        assert original.after.read_bytes() == Path(original.capture["image_path"]).read_bytes()
        assert service.status()["used"] == 2


@pytest.mark.parametrize("late_stage", ["authentication", "source"])
def test_authentication_at_final_backend_admission_cannot_adopt_after_deadline(tmp_path, monkeypatch, late_stage):
    service = ObservingAssessment()
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, service=service)
    validate = service.validate_result
    calls = []
    def slow_final(value, **binding):
        calls.append(binding)
        if late_stage == "authentication" and len(calls) == 3:
            clock.seconds = 12.1
        return validate(value, **binding)
    monkeypatch.setattr(service, "validate_result", slow_final)
    if late_stage == "source":
        import inspect
        source, reads = s.runtime.backend._source, []
        def slow_source(state):
            value = source(state)
            if any(frame.function == "validate_decision_adoption" for frame in inspect.stack()):
                reads.append(state)
                if len(reads) == 4:
                    clock.seconds = 12.1
            return value
        monkeypatch.setattr(s.runtime.backend, "_source", slow_source)
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and "budget" in result["review_packet"]["reason"]
    assert result["pending"]["execution_request_id"] == original.command_id and result["history"] == []
    assert len(captures) == 1 and len(service.calls) == 2
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    reviewed = s.runtime.control(review_request(s, result, original), "late-final-auth-main-review")
    assert reviewed["status"] == "ready"


@pytest.mark.parametrize("binding", ["assessment_round", "evidence_set_sha256", "review_packet_sha256"])
def test_latest_observation_review_rejects_old_or_unbound_context(tmp_path, monkeypatch, binding):
    s, original, clock, _ = observation_scene(tmp_path, monkeypatch, service=ObservingAssessment(final="review_required"))
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    result = s.runtime.tick(force=True)
    request = review_request(s, result, original)
    request[binding] = 0 if binding == "assessment_round" else "a" * 64
    with pytest.raises(ValueError):
        s.runtime.control(request, "stale-observation-main-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_old_receipt_without_trusted_geometry_handoffs_without_guessing(tmp_path, monkeypatch):
    from app.execution import task_plan_observation as module, task_plan_observation_capture as helper
    s, _, clock, _ = observation_scene(tmp_path, monkeypatch)
    path = next(tmp_path.glob("responses/*.json"))
    receipt = read_json_snapshot(path)
    receipt["result"]["observation"]["capture"].pop("image_size")
    receipt["result"]["observation"]["capture"].pop("window_rect")
    receipt["observation"].pop("image_size")
    receipt["observation"].pop("window_rect")
    write_json_snapshot(path, receipt)
    monkeypatch.setattr(module, "capture_followup", helper.capture_followup)
    s.co._owner = SimpleNamespace(call=lambda callback: callback())
    s.runtime.tick(force=True)
    clock.seconds = .6
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and result["review_packet"]["reason"] == "task_plan_observation_frame_invalid"
    assert len(s.co._decision_service.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("changed", ["closing", "source", "owner", "profile"])
def test_observation_binding_changes_stop_before_new_capture_or_assessment(tmp_path, monkeypatch, changed):
    s, _, clock, captures = observation_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    if changed == "closing":
        write_json_snapshot(tmp_path / "closing.json", {"status": "closing"})
    elif changed == "source":
        state = s.runtime.backend.status(s.run_id)
        path = s.runtime.backend._source_path(state["plan_id"])
        source = read_json_snapshot(path)
        source["plan"]["title"] = "Different source"
        write_json_snapshot(path, source)
    elif changed == "owner":
        s.runtime.backend.owner_id = "different-owner"
    else:
        monkeypatch.setattr(s.co._decision_service, "status", lambda: {
            "contract_version": "decision_profile.v2", "profile_sha256": "f" * 64,
            "adoption_mode": "auto", "review_policy": "adaptive"})
    clock.seconds = .6
    if changed in {"source", "owner"}:
        with pytest.raises(ValueError, match="source_binding_mismatch" if changed == "source" else "owner_mismatch"):
            s.runtime.tick(force=True)
    elif changed == "closing":
        assert s.runtime.tick(force=True) is None
        assert s.runtime.backend.status(s.run_id)["history"] == []
    else:
        result = s.runtime.tick(force=True)
        assert result["history"] == [] and result["wait_reason"] == "verification_required"
    assert captures == [] and len(s.co._decision_service.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("stage", ["capture", "capture_wrapper", "second_assessment", "backend_authentication"])
def test_queued_cancel_at_each_late_observation_boundary_preserves_original_fact(tmp_path, monkeypatch, stage):
    from app.execution import task_plan_observation as module
    from tests.test_task_plan_queued_cancel import queue_cancel
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch)
    queued = []
    s.runtime.tick(force=True)
    if stage.startswith("capture"):
        capture = module.capture_followup
        def during_capture(*args, **kwargs):
            result = capture(*args, **kwargs)
            queued.append(queue_cancel(s))
            if stage == "capture_wrapper":
                from app.execution.task_plan_observation_capture import FollowupObservationError
                raise FollowupObservationError("cancellation_check_failed")
            return result
        monkeypatch.setattr(module, "capture_followup", during_capture)
    elif stage == "second_assessment":
        s.co._decision_service.during = lambda: queued.append(queue_cancel(s))
    else:
        validate = s.co._decision_service.validate_result
        count = []
        def during_authentication(value, **binding):
            count.append(binding)
            if len(count) == 2:
                queued.append(queue_cancel(s))
            return validate(value, **binding)
        monkeypatch.setattr(s.co._decision_service, "validate_result", during_authentication)
    clock.seconds = 1.6
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["pending"]["execution_request_id"] == original.command_id
    assert len(queued) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2
    cancelled = s.runtime.control(queued[0]["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": queued[0], "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["status"] == terminal["runner_state"] == "cancelled"
    assert len(terminal["history"]) == 1 and terminal["history"][0]["execution_request_id"] == original.command_id
    assert terminal["history"][0]["original_input_status"] == "completed"
    assert terminal["history"][0]["action_executed"] is True
    assert len(captures) == 1 and len(s.co._decision_service.calls) == (1 if stage.startswith("capture") else 2)
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_original_after_damage_ends_automatic_observation_without_reviewable_success(
        tmp_path, monkeypatch, damage):
    import asyncio
    from tests.test_task_plan_client import client
    from app.execution.task_plan_observation import ObservationLedger
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    if damage == "changed":
        original.after.write_bytes(b"synthetic damaged original image")
    else:
        original.after.unlink()
    clock.seconds = .6
    result = s.runtime.tick(force=True)
    assert result["observation_pending"] is False and s.runtime._enabled_run is None
    assert "review_packet" not in result and "error" in result["wait"]
    assert result["history"] == [] and result["pending"]["execution_request_id"] == original.command_id
    assert ObservationLedger(s.runtime.backend, original.command_id).finished()["reason"] == "task_plan_observation_validation_failed"
    class Session:
        async def call_tool(self, name, args):
            assert name == "instant_run"
            return SimpleNamespace(structuredContent={"request_id": args["request_id"], "status": "returned",
                "result": s.runtime.control(args["command"]["request"], args["request_id"])}, is_error=False)
    opened, events = client(tmp_path, Session()), []
    async def status(request_id):
        return await opened.run_plan(request_id, {"kind": "task_plan", "request": {
            "action": "status", "run_id": s.run_id}}, event_callback=events.append, total_timeout=0)
    assert asyncio.run(status("bad-original-status"))["client_state"] == "verification_required"
    asyncio.run(status("bad-original-status-repeat"))
    assert len(events) == 1 and captures == [] and len(s.co._decision_service.calls) == 1
    assert s.runtime.tick(force=True) is None and len(list(tmp_path.glob("commands/*.json"))) == 1
