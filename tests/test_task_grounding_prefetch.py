"""下一步只读定位与原步骤认证并行；仅替换 HTTP 和桌面边界。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, Thread, current_thread
from time import monotonic, sleep
from types import SimpleNamespace

import httpx
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.action_review import CANDIDATE_CONDITION
from app.judgment import DecisionService, OpenAIDecisionsProvider
from app.judgment.profile import DecisionProfile
from app.vision.agent_command_jobs import AgentCommandJobs
from app.core.vision_admission_contract import AgentCommandError
from app.vision.external_grounding_api import ChatCompletionsGrounder
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_external_grounding_api import profile, reply
from tests.test_task_plan_adaptive_review import CONDITION, adaptive_plan
from tests.test_openai_decisions import reply as decision_reply
from tests.test_task_plan_runner import complete_original, scene


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "synthetic-offline-only")
    monkeypatch.setenv("PREFETCH_DECISION_KEY", "synthetic-offline-only")
    behavior = {"error": None, "decision_error": None, "during": None}
    def decide(request):
        if behavior["during"]:
            behavior["during"]()
        if behavior["decision_error"] == "provider":
            return httpx.Response(503, json={"error": "offline-unavailable"})
        if behavior["decision_error"] == "protocol":
            return httpx.Response(200, json={"answers": "invalid"})
        body = decision_reply(.5 if behavior["decision_error"] == "uncertain" else .99)
        body["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": .01})
        return httpx.Response(200, json=body)
    decision_client = httpx.Client(transport=httpx.MockTransport(decide))
    service = DecisionService(tmp_path, profile=DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        api_key_env="PREFETCH_DECISION_KEY", auto_conditions=[CANDIDATE_CONDITION, CONDITION]),
        provider=OpenAIDecisionsProvider(api_key_env="PREFETCH_DECISION_KEY", client=decision_client))
    plan = adaptive_plan()
    plan.update(schema_version="task_plan.v3", goal="Open both fresh panels")
    plan["completion"] = {"step_id": "step-1", "verification": deepcopy(plan["steps"][1]["verification"])}
    s = scene(tmp_path, monkeypatch, source=plan, decision=service)
    original = complete_original(s, native=False)
    original.capture.update(image_size={"width": 80, "height": 60}, window_rect=[0, 0, 80, 60])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    started, release = Event(), Event()
    release.set()
    http_calls, inputs = [], []
    def handle(request):
        http_calls.append(request)
        started.set()
        assert release.wait(3), "offline HTTP boundary was not released"
        if behavior["error"] == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if behavior["error"] == "protocol":
            return httpx.Response(200, json={"choices": []})
        context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        result = {"schema_version": "grounding.v1", "request_id": context["request_id"],
            "capture_id": context["capture_id"], "status": "found", "coordinate_space": "capture_image_pixels",
            "image_size": context["image_size"], "selected_candidate_id": "next",
            "candidates": [{"id": "next", "label": "Next panel", "evidence_source": "api_visual",
                "bbox": {"x": 10, "y": 10, "width": 30, "height": 20}, "click_point": {"x": 20, "y": 20}}]}
        return httpx.Response(200, json=reply(result))
    grounder = ChatCompletionsGrounder(profile(timeout_seconds=2), transport=httpx.MockTransport(handle))
    store = GroundingHandoffStore(tmp_path, owner_id="owner-1")
    def execute(**kwargs):
        assert s.runtime.backend.status(s.run_id)["history"][0]["verdict"] == "success"
        target = kwargs["grounding_target"]
        identity = {"target_window_handle": 11, "process_id": 22, "process_create_time": 33.0}
        target.plan(image_path=original.capture["image_path"], goal=kwargs["request"]["goal"], identity=identity)
        target.before_dispatch({"x": 20, "y": 20}, identity)
        inputs.append(kwargs)
        return {"phase": "returned", "response": {"success": True,
            "data": {"result": {"execution_path": {"action_executed": True}}}}, "action_executed": True}
    s.co._owner = SimpleNamespace(call=lambda callback: callback())
    s.co.execute_local_step = execute
    jobs = AgentCommandJobs(s.co, store, lambda: deepcopy(original.capture),
        RecognitionSourceConfig(source="external_api", api_profile="offline.json"), api_grounder=grounder)
    s.runtime.agent_jobs = jobs
    yield SimpleNamespace(s=s, jobs=jobs, store=store, grounder=grounder, original=original, started=started,
        release=release, http_calls=http_calls, inputs=inputs, behavior=behavior, service=service)
    release.set()
    assert jobs.close(timeout=3)
    grounder.close()
    service.close()
    decision_client.close()


def measurement(p):
    paths = list(p.s.session.glob("task-grounding-prefetch/*.json"))
    assert len(paths) == 1
    return read_json_snapshot(paths[0])


def terminal(p, command_id):
    end = monotonic() + 3
    while monotonic() < end:
        result = p.jobs.get(command_id)
        if result["status"] in {"completed", "failed", "cancelled"}:
            p.jobs._jobs[command_id].thread.join(1)
            return result
        sleep(.005)
    pytest.fail("offline command did not finish")


def start_next(p):
    pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
    p.jobs.start(pending["execution_request_id"], pending["suggested_command"], deepcopy(p.s.target), {})
    return terminal(p, pending["execution_request_id"])


def test_ground_starts_while_assessment_blocks_and_only_success_releases_one_consume(pipeline):
    p = pipeline
    assert hasattr(p.jobs, "task_grounding_prefetch"), "host has no readonly next-step grounding slot"
    decision_entered, decision_release = Event(), Event()
    def during():
        decision_entered.set()
        assert decision_release.wait(3)
    p.behavior["during"] = during
    results = []
    thread = Thread(target=lambda: results.append(p.s.runtime.tick(force=True)))
    thread.start()
    try:
        assert decision_entered.wait(2) and p.started.wait(2)
        assert p.s.runtime.backend.status(p.s.run_id)["history"] == [] and p.inputs == []
        request_id = measurement(p)["grounding_request_id"]
        assert "execution_id" not in p.store.get(request_id)
    finally:
        decision_release.set()
        thread.join(3)
    assert not thread.is_alive() and results[0]["pending"]["step_id"] == "step-1"
    final = start_next(p)
    assert final["status"] == "completed" and len(p.inputs) == len(p.http_calls) == 1
    assert p.store.get(request_id)["phase"] == "completed"
    record = measurement(p)
    assert record["phase"] == "consumed" and record["api_attempts"] == 1
    assert record["provider"]["usage"]["total_tokens"] == 50
    assert len(final["recognition_calls"]) == 1
    assert final["grounding_prefetch"]["status"] == "consumed"


@pytest.mark.parametrize("failure", ["provider", "protocol", "uncertain"])
def test_nonpass_discards_prefetch_without_input_or_retry(pipeline, failure):
    p = pipeline
    p.behavior["decision_error"] = failure
    waiting = p.s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["review_required"] is True
    assert p.jobs.task_grounding_prefetch.close(timeout=2)
    assert measurement(p)["phase"] == "discarded"
    assert p.inputs == [] and len(p.http_calls) <= 1
    for _ in range(2):
        p.s.runtime.tick(force=True)
    assert measurement(p)["api_attempts"] <= 1


@pytest.mark.parametrize("failure", ["timeout", "protocol"])
def test_prefetch_http_failure_is_not_hidden_by_synchronous_retry(pipeline, failure):
    p = pipeline
    p.behavior["error"] = failure
    p.s.runtime.tick(force=True)
    result = start_next(p)
    assert result["status"] == "failed" and p.inputs == [] and len(p.http_calls) == 1
    assert "prefetch" in str(result.get("error"))
    assert measurement(p)["api_attempts"] == 1


def test_cancel_late_response_never_resolves_or_claims(pipeline):
    p = pipeline
    p.release.clear()
    p.s.runtime.tick(force=True)
    assert p.started.wait(2)
    p.s.runtime.control({"action": "cancel", "run_id": p.s.run_id}, "cancel-next")
    p.release.set()
    assert p.jobs.task_grounding_prefetch.close(timeout=2)
    record = measurement(p)
    assert record["phase"] == "discarded" and record["api_attempts"] == 1
    assert "execution_id" not in p.store.get(record["grounding_request_id"])
    assert p.inputs == [] and record["provider"]["usage"]["total_tokens"] == 50


def test_repeat_verification_and_double_consume_cannot_repeat_paid_grounding(pipeline):
    p = pipeline
    p.s.runtime.tick(force=True)
    result = start_next(p)
    job = next(iter(p.jobs._jobs.values()))
    assert p.jobs.task_grounding_prefetch.consume(job, "Open panel 1") is None
    assert result["status"] == "completed" and len(p.http_calls) == 1


def test_wrong_goal_discards_and_identity_change_is_not_reused(pipeline):
    p = pipeline
    p.s.runtime.tick(force=True)
    pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
    job = SimpleNamespace(command=deepcopy(pending["suggested_command"]), command_id=pending["execution_request_id"],
        target=deepcopy(p.s.target), cancelled=False, prefetch_checked=False)
    with pytest.raises(AgentCommandError, match="prefetch.*goal_changed"):
        p.jobs.task_grounding_prefetch.consume(job, "Wrong goal")
    assert measurement(p)["discard_reason"] == "goal_changed"
    assert p.inputs == []


def test_new_host_does_not_recover_old_prefetch(pipeline):
    p = pipeline
    p.s.runtime.tick(force=True)
    assert p.jobs.task_grounding_prefetch.close(timeout=2)
    reopened = AgentCommandJobs(p.s.co, p.store, lambda: deepcopy(p.original.capture), p.jobs.configuration,
        api_grounder=p.grounder)
    try:
        pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
        job = SimpleNamespace(command=deepcopy(pending["suggested_command"]), command_id=pending["execution_request_id"],
            target=deepcopy(p.s.target), cancelled=False, prefetch_checked=False)
        assert reopened.task_grounding_prefetch.consume(job, "Open panel 1") is None
        assert p.inputs == []
    finally:
        assert reopened.close(timeout=2)


@pytest.mark.parametrize("mutation,reason", [("identity", "window_changed"), ("source", "source_capture_changed"),
    ("owner", "plan_changed"), ("configuration", "configuration_changed")])
def test_consumption_revalidates_source_window_owner_and_configuration(pipeline, mutation, reason):
    p = pipeline
    p.s.runtime.tick(force=True)
    prefetch = p.jobs.task_grounding_prefetch
    assert prefetch._active["done"].wait(2)
    pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
    job = SimpleNamespace(command=deepcopy(pending["suggested_command"]), command_id=pending["execution_request_id"],
        target=deepcopy(p.s.target), cancelled=False, prefetch_checked=False)
    if mutation == "identity":
        p.s.target["process_create_time"] += 1
    elif mutation == "source":
        Path(p.original.capture["image_path"]).write_bytes(b"changed-original")
    elif mutation == "owner":
        p.s.runtime.backend.owner_id = "different-owner"
    else:
        p.jobs.configuration = RecognitionSourceConfig(source="external_api", api_profile="different.json")
    with pytest.raises(AgentCommandError, match="prefetch.*" + reason):
        prefetch.consume(job, "Open panel 1")
    assert measurement(p)["discard_reason"] == reason and len(p.http_calls) == 1 and p.inputs == []


def test_same_verification_tick_key_never_starts_a_second_http_request(pipeline):
    p = pipeline
    prefetch = p.jobs.task_grounding_prefetch
    state = p.s.runtime.backend.status(p.s.run_id)
    step = p.s.runtime.backend.pinned_step(p.s.run_id, "step-0")
    for _ in range(3):
        prefetch.begin(p.s.runtime.backend, state, step, p.original.capture, lambda: deepcopy(p.s.target))
    p.s.runtime.tick(force=True)
    assert start_next(p)["status"] == "completed"
    assert len(p.http_calls) == measurement(p)["api_attempts"] == 1


def test_next_command_waits_for_inflight_prefetch_without_claiming_or_reissuing(pipeline):
    p = pipeline
    p.release.clear()
    p.s.runtime.tick(force=True)
    assert p.started.wait(2)
    pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
    request_id = measurement(p)["grounding_request_id"]
    p.jobs.start(pending["execution_request_id"], pending["suggested_command"], deepcopy(p.s.target), {})
    assert "execution_id" not in p.store.get(request_id) and p.inputs == []
    p.release.set()
    assert terminal(p, pending["execution_request_id"])["status"] == "completed"
    assert len(p.http_calls) == len(p.inputs) == 1


def test_close_reports_unfinished_http_then_reaps_late_response_without_input(pipeline):
    p = pipeline
    p.release.clear()
    p.s.runtime.tick(force=True)
    assert p.started.wait(2)
    assert p.jobs.close(timeout=.01) is False
    p.release.set()
    assert p.jobs.close(timeout=2) is True
    record = measurement(p)
    assert record["phase"] == "discarded" and record["discard_reason"] == "host_closing"
    assert record["provider"]["usage"]["total_tokens"] == 50 and p.inputs == []
    assert "execution_id" not in p.store.get(record["grounding_request_id"])


def test_input_step_can_only_consume_prefetch_at_its_first_focus(pipeline):
    p = pipeline
    source = read_json_snapshot(p.s.runtime.backend._source_path(p.s.runtime.backend.status(p.s.run_id)["plan_id"]))
    # 另建全新计划，旧计划与回执保持原样。
    p.s.runtime.control({"action": "cancel", "run_id": p.s.run_id}, "cancel-for-input-plan")
    p.s.runtime.tick(force=True)
    value = deepcopy(source["plan"])
    value["steps"][1]["action"] = {"kind": "input_sequence", "field_goal": "Search field",
        "text": "fresh text", "clear_existing": True, "submit_search": True}
    started = p.s.runtime.control({"action": "start", "plan": value}, "start-input-suffix")
    p.s.run_id = started["run_id"]
    original = complete_original(p.s, native=False)
    p.s.runtime.tick(force=True)
    prefetch = p.jobs.task_grounding_prefetch
    assert prefetch._active["done"].wait(2)
    pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
    from app.vision.agent_command_jobs import _Job
    from app.vision.recognition_source import ClientVisionCapabilities
    job = _Job(p.jobs, pending["execution_request_id"], pending["suggested_command"], deepcopy(p.s.target),
        ClientVisionCapabilities())
    p.jobs._snapshots[job.command_id] = {"command_id": job.command_id, "status": "running", "recognition_calls": []}
    ready = prefetch.consume(job, "Search field")
    assert ready["phase"] == "grounding_ready" and "execution_id" not in ready
    assert prefetch.consume(job, "Search field") is None
    assert prefetch.consume(job, "Enter") is None
    assert len(p.http_calls) == 1 and p.inputs == []
    assert original.capture["sha256"] == ready["capture"]["sha256"]


def test_grace_final_success_cannot_release_grounding_from_the_early_frame(pipeline, monkeypatch):
    from app.execution import task_plan_observation as observation
    p = pipeline
    clock = SimpleNamespace(seconds=1.4)
    monkeypatch.setattr(observation, "now_ns", lambda: int(clock.seconds * 1_000_000_000))
    result = p.original.receipt["result"]
    result["contract_version"] = "local_direct_step_v1"
    result["response"]["data"]["result"]["click_result"] = {}
    result["observation"]["capture"]["observation_stage"] = "after_transition_observation"
    result["observation"].update(source="post_action", authorizes_action=False, render_grace_ms=2000,
        adaptive_wait={"schema": "adaptive_observation.v1", "budget_ms": 2000, "elapsed_ms": 400.0,
            "early": True, "reason": "changed_then_stable", "readiness": "unassessed",
            "effect_verified": False, "authorizes_action": False, "automatic_retry_allowed": False,
            "clock_id": observation.CLOCK_ID, "started_ns": 1_000_000_000, "deadline_ns": 3_000_000_000,
            "samples": [{"image_path": p.original.capture["image_path"], "sha256": p.original.capture["sha256"]}]})
    write_json_snapshot(p.s.session / "responses" / (p.original.command_id + ".json"), p.original.receipt)
    p.behavior["decision_error"] = "uncertain"
    def capture(coordinator, **kwargs):
        from PIL import Image
        assert kwargs["cancelled"]() is False
        path = p.s.session / "captures" / "grace-final-fresh.png"
        Image.new("RGB", (80, 60), "blue").save(path)
        p.behavior["decision_error"] = None
        return {"frame": {"capture_id": "grace-final-fresh", "image_path": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(), "window_identity": deepcopy(p.s.target),
            "role": "observation"}, "capture_elapsed_ms": 1}
    monkeypatch.setattr(observation, "capture_followup", capture)
    assert p.s.runtime.tick(force=True)["observation_pending"] is True
    clock.seconds = 3.0
    final = p.s.runtime.tick(force=True)
    assert final["history"][0]["verdict"] == "success" and final["pending"]["step_id"] == "step-1"
    prefetch = p.jobs.task_grounding_prefetch
    assert prefetch._active["done"].wait(2)
    assert measurement(p)["phase"] == "discarded" and measurement(p)["released"] is False
    assert len(p.http_calls) <= 1 and p.inputs == []


def test_discarded_http_failure_still_surfaces_instead_of_fresh_retry(pipeline):
    p = pipeline
    p.behavior["error"] = "timeout"
    p.release.clear()
    p.s.runtime.tick(force=True)
    assert p.started.wait(2)
    p.jobs.task_grounding_prefetch.discard("state_expired")
    p.release.set()
    assert p.jobs.task_grounding_prefetch._active["done"].wait(2)
    result = start_next(p)
    assert result["status"] == "failed" and "api_timeout" in str(result.get("error"))
    assert len(p.http_calls) == 1 and p.inputs == []


@pytest.mark.parametrize("scope", ["local", "delegate", "explicit_wait", "native", "wait_policy", "scene_precheck"])
def test_ineligible_routes_record_reason_and_never_invoke_a_prefetch(pipeline, scope):
    p = pipeline
    state = p.s.runtime.backend.status(p.s.run_id)
    step = p.s.runtime.backend.pinned_step(p.s.run_id, "step-0")
    if scope == "local":
        p.jobs.configuration = RecognitionSourceConfig(source="local")
    elif scope == "delegate":
        p.jobs.configuration = RecognitionSourceConfig(source="agent_delegate", delegate_profile="offline")
    elif scope == "explicit_wait":
        state["pending"]["suggested_command"]["observation_wait_ms"] = 2000
    elif scope == "native":
        step["verification"] = {"kind": "native_condition", "condition": {"text": "Panel", "control_type": "Text"}}
    elif scope == "scene_precheck":
        p.service.profile = p.service.profile.model_copy(update={"scene_precheck": "parallel"})
    else:
        step["verification"]["wait_policy"] = {"loading_condition": "Loading", "completion_excludes_loading": True}
    assert p.jobs.task_grounding_prefetch.begin(p.s.runtime.backend, state, step, p.original.capture,
        lambda: deepcopy(p.s.target)) is None
    assert p.http_calls == [] and p.inputs == [] and measurement(p)["phase"] == "ineligible"


def test_queued_cancel_during_assessment_discards_prefetch_before_original_settlement(pipeline):
    from tests.test_task_plan_queued_cancel import queue_cancel
    p = pipeline
    queued = []
    def during():
        assert p.started.wait(2)
        queued.append(queue_cancel(p.s))
    p.behavior["during"] = during
    waiting = p.s.runtime.tick(force=True)
    assert waiting["history"] == [] and len(queued) == 1
    assert p.jobs.task_grounding_prefetch._active["done"].wait(2)
    assert measurement(p)["phase"] == "discarded" and p.inputs == []


@pytest.mark.parametrize("discard", ["state_expired", "cancel_control", "failed_control"])
def test_waiting_consumer_surfaces_error_after_concurrent_discard_without_reissuing(pipeline, discard):
    p = pipeline
    p.release.clear()
    p.behavior["error"] = "timeout"
    p.s.runtime.tick(force=True)
    assert p.started.wait(2)
    prefetch = p.jobs.task_grounding_prefetch
    waiting = Event()
    class ObservedCompletion(Event):
        def wait(self, timeout=None):
            if current_thread().name.startswith("agent-command-"):
                waiting.set()
            return super().wait(timeout)
    # 仅增加同步观测，等待和通知仍用真实 Event。
    prefetch._active["done"] = ObservedCompletion()
    pending = p.s.runtime.backend.status(p.s.run_id)["pending"]
    p.jobs.start(pending["execution_request_id"], pending["suggested_command"], deepcopy(p.s.target), {})
    assert waiting.wait(2)
    if discard == "cancel_control":
        p.s.runtime.control({"action": "cancel", "run_id": p.s.run_id}, "cancel-waiting-consumer")
    elif discard == "failed_control":
        with pytest.raises(ValueError):
            p.s.runtime.control({"action": "review", "run_id": p.s.run_id,
                "execution_request_id": pending["execution_request_id"], "step_id": "step-1",
                "verdict": "success", "reason": "not reviewable yet", "evidence_sha256": "a" * 64},
                "invalid-review-during-prefetch")
    else:
        prefetch.discard("state_expired")
    p.release.set()
    final = terminal(p, pending["execution_request_id"])
    assert len(p.http_calls) == 1 and p.inputs == []
    assert "task_grounding_prefetch_failed:api_timeout" in str(final.get("error"))
    record = measurement(p)
    assert record["phase"] == "discarded" and record["api_attempts"] == 1
    assert record["error_code"] == "api_timeout"


def test_begin_cannot_start_a_worker_after_close_already_reported_joined(pipeline):
    p = pipeline
    prefetch = p.jobs.task_grounding_prefetch
    state = p.s.runtime.backend.status(p.s.run_id)
    step = p.s.runtime.backend.pinned_step(p.s.run_id, "step-0")
    entered, release = Event(), Event()
    results = []
    def read_identity():
        entered.set()
        assert release.wait(2)
        return deepcopy(p.s.target)
    thread = Thread(target=lambda: results.append(prefetch.begin(p.s.runtime.backend, state, step,
        p.original.capture, read_identity)))
    thread.start()
    try:
        assert entered.wait(2)
        assert prefetch.close(timeout=.1) is True
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and results == [None]
    assert p.http_calls == [] and p.inputs == [] and not list(p.s.session.glob("grounding/*.json"))
