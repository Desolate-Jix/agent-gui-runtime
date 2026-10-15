"""命令定位与可选场景预检共用预算，判断供应商仅离线应答。"""
from copy import deepcopy
from hashlib import sha256
from threading import Event
from time import monotonic, perf_counter_ns, sleep

from PIL import Image
import pytest

from app.judgment.profile import DecisionProfile
from app.judgment.service import DecisionService
from app.vision.agent_command_jobs import AgentCommandJobs
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_local_step_timings import timed_scene
from app.execution.local_direct_step import _post_action as REAL_POST_ACTION


class Owner:
    def call(self, callback):
        return callback()


class Coordinator:
    def __init__(self, service):
        self._owner = Owner()
        self._decision_service = service
        self.calls = []

    def execute_local_step(self, **kwargs):
        self.calls.append(kwargs)
        return {"phase": "returned", "response": {"success": True,
            "data": {"result": {"execution_path": {"action_executed": True}}}}, "action_executed": True}


class Provider:
    ready = True

    def __init__(self):
        self.calls = []
        self.met = .99
        self.review = .01
        self.during = None

    def judge(self, request):
        self.calls.append(deepcopy(request))
        if self.during:
            self.during()
        return {"request_sha256": request["request_sha256"], "predicates": {
            name: {"type": "predicate", "probability": (
                self.met if name == "condition_met" else self.review if name == "needs_agent_review" else .01)}
            for name in request["enabled_predicates"]},
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            "http_elapsed_ms": 1.0, "server_processing_ms": None, "provider_request_id": "offline"}


class Grounder:
    def __init__(self):
        self.calls = []
        self.during = None
        self.started = Event()
        self.finished = Event()

    def ground(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        self.started.set()
        try:
            if self.during:
                self.during()
            capture = kwargs["capture"]
            return {"provider": {"http_elapsed_ms": 3, "attempt": {"status": "success"}}, "result": {
                "schema_version": "grounding.v1", "request_id": kwargs["request_id"],
                "capture_id": capture["capture_id"], "status": "found",
                "coordinate_space": "capture_image_pixels", "image_size": capture["image_size"],
                "candidates": [{"id": "one", "label": "Search",
                    "bbox": {"x": 10, "y": 20, "width": 50, "height": 20},
                    "click_point": {"x": 35, "y": 30}, "evidence_source": "api_visual"}],
                "selected_candidate_id": "one"}}
        finally:
            self.finished.set()


@pytest.fixture
def scene(tmp_path, monkeypatch):
    from app.execution.action_review import CANDIDATE_CONDITION, SCENE_CONDITION
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    provider = Provider()
    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        auto_conditions=[CANDIDATE_CONDITION, SCENE_CONDITION], request_cap=20)
    service = DecisionService(tmp_path, profile=profile, provider=provider)
    coordinator = Coordinator(service)
    grounder = Grounder()
    path = tmp_path / "before.png"
    Image.new("RGB", (100, 80), "white").save(path)
    capture = {"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
        "window_identity": {"handle": 100, "process_id": 200, "process_create_time": 1.5}}
    store = GroundingHandoffStore(tmp_path, owner_id="offline")
    jobs = AgentCommandJobs(coordinator, store, lambda: capture,
        RecognitionSourceConfig(source="external_api", api_profile="offline.json"), api_grounder=grounder)
    context = {"schema": "action_review_context.v1", "run_id": "run-1", "step_id": "open",
        "attempt_id": "attempt-1", "budget_ms": 2000, "plan": {
            "schema_version": "task_plan.v2", "title": "Read documentation", "inputs": {},
            "steps": [{"step_id": "open", "action": {"kind": "click", "goal": "Search"},
                "verification": {"kind": "agent_judgment"}}]}}
    yield jobs, coordinator, store, grounder, provider, context
    jobs.close(timeout=1)
    service.close()


def start(scene, *, context=True):
    jobs, _, _, _, _, review = scene
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Search"}}
    if context:
        command["action_review"] = review
    return jobs.start("job-1", command, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})


def done(jobs):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        value = jobs.get("job-1")
        if value["status"] in {"completed", "failed", "cancelled"}:
            return value
        sleep(.005)
    pytest.fail(f"command did not terminate: {value}")


def test_context_shares_original_deadline_with_grounding_and_action(scene):
    jobs, coordinator, _, grounder, provider, context = scene
    started = perf_counter_ns()
    start(scene)
    result = done(jobs)
    assert result["status"] == "completed", result
    call = coordinator.calls[0]
    assert call["action_review"] == context
    assert started < call["action_review_deadline_ns"] <= perf_counter_ns() + context["budget_ms"] * 1_000_000
    assert 0 < grounder.calls[0]["timeout_seconds"] <= 2
    assert provider.calls == []


def test_no_context_preserves_old_grounder_signature_and_no_scene_call(scene):
    jobs, coordinator, _, grounder, provider, _ = scene
    start(scene, context=False)
    assert done(jobs)["status"] == "completed"
    assert "timeout_seconds" not in grounder.calls[0]
    assert "action_review" not in coordinator.calls[0]
    assert provider.calls == []


@pytest.mark.parametrize("bad", [True, {}, {"schema": "action_review_context.v1"}])
def test_invalid_context_is_rejected_before_any_job_or_capture(scene, bad):
    jobs, coordinator, _, grounder, provider, _ = scene
    with pytest.raises(ValueError, match="action_review"):
        jobs.start("bad", {"kind": "step", "operation": "execute_recognition_plan",
            "request": {"goal": "Search"}, "action_review": bad},
            {"handle": 100, "process_id": 200}, {"image_transport": "supported", "current_vision": "supported"})
    assert not jobs.active and coordinator.calls == grounder.calls == provider.calls == []


def parallel(scene):
    service = scene[1]._decision_service
    service.profile = service.profile.model_copy(update={"scene_precheck": "parallel"})


def test_parallel_scene_uses_same_capture_and_does_not_authorize_candidate(scene):
    jobs, coordinator, _, grounder, provider, context = scene
    parallel(scene)
    # 两边都进入网络回调后才释放，串行实现会失败。
    arrived = Event()
    def wait_probe():
        assert arrived.wait(1)
    grounder.during = wait_probe
    provider.during = arrived.set
    start(scene)
    result = done(jobs)
    assert result["status"] == "completed", result
    assert len(provider.calls) == len(grounder.calls) == len(coordinator.calls) == 1
    assert provider.calls[0]["frames"][0]["capture_id"] == grounder.calls[0]["capture"]["capture_id"]
    assert provider.calls[0]["action"]["candidate"] is None
    assert provider.calls[0]["action"]["review_scope"] == "scene"
    assert coordinator.calls[0]["action_review"] == context
    assert result["scene_precheck"]["authorizes_action"] is False
    assert result["scene_precheck"]["requires_candidate_review"] is True


@pytest.mark.parametrize("met,review", [(0, .01), (.99, .99)])
def test_authenticated_scene_block_cancels_before_dispatch_without_waiting_for_luna(scene, met, review, monkeypatch):
    from app.execution import action_review
    jobs, coordinator, store, grounder, provider, _ = scene
    parallel(scene)
    provider.met, provider.review = met, review
    release = Event()
    grounder.during = lambda: release.wait(2)
    provider.during = lambda: grounder.started.wait(1)
    observed = []
    original = action_review.assess_scene
    def assess(*args, **kwargs):
        value = original(*args, **kwargs)
        observed.append({"authenticated": action_review.validate_scene_assessment(args[0], value,
            envelope=kwargs["envelope"]), "judgment": {key: value.get("judgment", {}).get(key) for key in
            ("status", "verdict", "probabilities", "reason", "judgment_result")}})
        return value
    monkeypatch.setattr(action_review, "assess_scene", assess)
    before = monotonic()
    try:
        start(scene)
        result = done(jobs)
        assert monotonic() - before < 1, observed
        assert result["status"] == "failed" and result["action_executed"] is False
        assert result["error"]["code"] == "scene_precheck_blocked"
        assert coordinator.calls == [] and result["dispatch_attempts"] == []
        assert result["scene_precheck"]["status"] == "blocked"
        assert result["scene_precheck"]["started_attempts"] == {"ground": 1, "probe": 1}
    finally:
        release.set()
        assert grounder.finished.wait(1)
    end = monotonic() + 1
    while not jobs.get("job-1").get("recognition_calls") and monotonic() < end:
        sleep(.005)
    assert len(jobs.get("job-1")["recognition_calls"]) == 1
    assert store.get(grounder.calls[0]["request_id"])["phase"] == "cancelled"
    assert coordinator.calls == []


@pytest.mark.parametrize("met,review", [(.5, .2), (.99, .2)])
def test_uncertain_or_review_is_not_an_early_block(scene, met, review):
    jobs, coordinator, _, _, provider, _ = scene
    parallel(scene)
    provider.met, provider.review = met, review
    start(scene)
    result = done(jobs)
    assert result["status"] == "completed", result
    assert result["scene_precheck"]["status"] == "joined"
    assert result["scene_precheck"]["scene"]["disposition"] == "unknown"
    assert len(coordinator.calls) == 1


def test_forged_scene_block_cannot_be_used(scene, monkeypatch):
    from app.execution import action_review
    jobs, coordinator, _, _, _, _ = scene
    parallel(scene)
    original = action_review.assess_scene
    def corrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        value["judgment"]["judgment_result"]["verdict"] = "failure"
        return value
    monkeypatch.setattr(action_review, "assess_scene", corrupt)
    start(scene)
    result = done(jobs)
    assert result["scene_precheck"]["scene"]["authenticated"] is False
    assert result["scene_precheck"]["scene"]["disposition"] == "unknown"
    assert len(coordinator.calls) == 1


def test_always_main_preflight_avoids_paid_grounding(scene):
    jobs, coordinator, _, grounder, provider, _ = scene
    parallel(scene)
    service = coordinator._decision_service
    service.profile = service.profile.model_copy(update={"review_policy": "always_main"})
    start(scene)
    result = done(jobs)
    assert result["status"] == "failed" and result["action_executed"] is False
    assert result["error"]["code"] == "decision_always_main"
    assert result["action_review_preflight"]["reason"] == "decision_always_main"
    assert provider.calls == grounder.calls == coordinator.calls == []


@pytest.mark.parametrize("problem,reason", [
    ("allowlist", "decision_condition_not_allowlisted"),
    ("readiness", "decision_service_unavailable"),
    ("cap", "decision_scope_request_cap"),
    ("disabled", "decision_service_disabled")])
def test_candidate_preflight_stops_before_capture_and_paid_grounding(scene, monkeypatch, problem, reason):
    jobs, coordinator, _, grounder, provider, _ = scene
    service = coordinator._decision_service
    if problem == "allowlist":
        service.profile = service.profile.model_copy(update={"auto_conditions": []})
    elif problem == "readiness":
        monkeypatch.setattr(service, "readiness", lambda: {"ready": False})
    elif problem == "cap":
        monkeypatch.setattr(service, "status", lambda: {"budget": {"remaining": 0}})
    else:
        service.enabled = False
    captures, original_capture = [], jobs.capture_current
    jobs.capture_current = lambda: captures.append(True) or original_capture()
    start(scene)
    result = done(jobs)
    assert result["status"] == "failed" and result["action_executed"] is False
    assert result["error"]["code"] == reason
    assert result["action_review_preflight"]["reason"] == reason
    assert result["dispatch_attempts"] == []
    assert captures == []
    assert grounder.calls == provider.calls == coordinator.calls == []


def test_late_ground_result_cannot_dispatch_under_shared_budget(scene):
    jobs, coordinator, _, grounder, _, context = scene
    context["budget_ms"] = 20
    grounder.during = lambda: sleep(.04)
    start(scene)
    result = done(jobs)
    assert result["status"] == "failed" and result["action_executed"] is False
    assert result["error"]["code"] == "action_review_deadline_expired"
    assert len(result["recognition_calls"]) == 1 and coordinator.calls == []


def test_cancelled_parallel_late_block_does_not_dispatch(scene):
    jobs, coordinator, _, grounder, provider, _ = scene
    parallel(scene)
    release, probing = Event(), Event()
    grounder.during = lambda: release.wait(2)
    def wait_probe():
        probing.set()
        assert release.wait(2)
    provider.during = wait_probe
    provider.review = .99
    try:
        start(scene)
        assert grounder.started.wait(1) and probing.wait(1)
        jobs.cancel("job-1")
        result = done(jobs)
        assert result["status"] == "cancelled" and result["action_executed"] is False
        assert result["scene_precheck"]["status"] == "cancelled"
        assert result["dispatch_attempts"] == [] and coordinator.calls == []
    finally:
        release.set()
        assert grounder.finished.wait(1)
    assert coordinator.calls == []


def test_context_expiry_cancels_delegated_grounding_without_dispatch(scene):
    jobs, coordinator, store, grounder, _, context = scene
    jobs.configuration = RecognitionSourceConfig(source="agent_current")
    jobs.api_grounder = None
    context["budget_ms"] = 50
    start(scene)
    result = done(jobs)
    assert result["status"] == "failed" and result["action_executed"] is False
    assert result["error"]["code"] == "action_review_deadline_expired"
    pending = jobs._jobs["job-1"].pending_id
    assert store.get(pending)["phase"] == "cancelled"
    assert coordinator.calls == grounder.calls == []


@pytest.mark.parametrize("mode", [None, "visual"])
def test_visual_input_sequence_options_keep_job_deadline(scene, monkeypatch, mode):
    import app.vision.agent_command_jobs as module
    jobs, coordinator, _, grounder, provider, context = scene
    context["plan"]["steps"][0]["action"] = {"kind": "input_sequence", "field_goal": "Search",
        "text": "Java", "clear_existing": True, "submit_search": False}
    received = []
    def sequence(proxy, target, request, **kwargs):
        received.append(kwargs)
        return {"status": "completed", "action_executed": False}
    monkeypatch.setattr(module, "run_input_sequence", sequence)
    jobs.start("job-1", {"kind": "input_sequence", **({"field_evidence_mode": mode} if mode else {}),
        "action_review": context, "request": {"field_goal": "Search", "text": "Java", "submit_search": False}},
        {"handle": 100, "process_id": 200}, {"image_transport": "supported", "current_vision": "supported"})
    assert done(jobs)["status"] == "completed"
    options = received[0]
    assert options["action_review"] == context
    deadline = jobs._jobs["job-1"].action_review_deadline_ns
    assert options["action_review_deadline_ns"] == options["visual_field_context"]["deadline_ns"] == deadline
    assert options["field_evidence_mode"] == "visual"
    assert options["visual_field_context"]["service"] is coordinator._decision_service
    assert options["visual_field_context"]["native_field_evidence"] is False
    assert options["visual_field_context"]["ocr_enabled"] is False
    assert "focus_observation_delay_ms" not in options["visual_field_context"]
    assert options["visual_field_context"]["cancelled"]() is False
    jobs._jobs["job-1"].cancelled = True
    assert options["visual_field_context"]["cancelled"]() is True
    assert grounder.calls == provider.calls == []


def test_real_sequence_local_step_only_receives_candidate_context_for_focus(scene, monkeypatch):
    from threading import RLock
    from app.execution.local_direct_step import LocalDirectStepMixin
    from app.execution import input_sequence
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
    jobs, previous, store, _, _, context = scene

    class ValidatingCoordinator(LocalDirectStepMixin):
        def __init__(self):
            self._owner = Owner()
            self._decision_service = previous._decision_service
            self._guard = RLock()
            self._automatic_safety_interception = self._attached = self._uses_production_factory = False
            self._runtime = self._learning_binding = self._model_service = None
            self._runtime_output_root = store.session_root
            self.calls = []

        def _begin(self, state):
            pass

        def _end(self):
            pass

        def _require_host_ready(self, **kwargs):
            pass

        def _execute_local_step_on_owner(self, handle, pid, operation, request, configuration=None, *,
                timing_context, control_target=None, keyboard_target=None, focus_target=None,
                grounding_target=None, memory_target=None, learning_context=None):
            self.calls.append({"operation": operation, "timing_context": deepcopy(timing_context)})
            frame = jobs.capture_current()
            data = {"execution_path": {"action_executed": True}, "pressed": True,
                "selected_click_point": {"x": 35, "y": 30},
                "selected_click_point_coordinate_space": "capture_image_pixels"}
            return {"phase": "returned", "capture": frame,
                "response": {"success": True, "data": data if operation == "press_key" else {"result": data}},
                "observation": {"status": "captured", "capture": frame}}

    coordinator = ValidatingCoordinator()
    jobs.coordinator = coordinator
    readings = iter(["", "Java"])
    def read(coordinator, target, point, capture, field_id, expected_identity, **kwargs):
        identity = TextFieldIdentity(field_id, 100, 200, 1.5, (1,), (0, 0, 100, 80), (10, 20, 50, 20))
        return TextFieldSnapshot(identity, capture["sha256"], "offline", 1, "uia_value", next(readings), None)
    monkeypatch.setattr(input_sequence, "_read_field", read)
    monkeypatch.setattr(input_sequence, "_focus_field_binding", lambda *args: {
        "control_type": "Edit", "runtime_id": [1], "bbox": {"x": 10, "y": 20, "w": 50, "h": 20}})
    context["plan"]["steps"][0]["action"] = {"kind": "input_sequence", "field_goal": "Search",
        "text": "Java", "clear_existing": True, "submit_search": True}
    jobs.start("job-1", {"kind": "input_sequence", "field_evidence_mode": "legacy", "action_review": context, "request": {
        "field_goal": "Search", "text": "Java", "clear_existing": True, "submit_search": True}},
        {"handle": 100, "process_id": 200}, {"image_transport": "supported", "current_vision": "supported"})
    result = done(jobs)
    assert result["status"] == "completed", result
    assert [row["operation"] for row in coordinator.calls] == ["execute_recognition_plan", "type_text", "press_key"]
    assert coordinator.calls[0]["timing_context"]["action_review"] == context
    assert coordinator.calls[0]["timing_context"]["action_review_deadline_ns"] == jobs._jobs["job-1"].action_review_deadline_ns
    assert all("action_review" not in row["timing_context"] for row in coordinator.calls[1:])


def test_default_public_visual_input_without_decision_has_zero_capture_grounding_or_input(scene, monkeypatch):
    from app.execution.public_input_defaults import adopt_public_input_command
    from app.execution import input_sequence
    jobs, coordinator, _, grounder, provider, _ = scene
    coordinator._decision_service = None
    captures = []
    jobs.capture_current = lambda: captures.append(True)
    def forbidden(*args, **kwargs):
        pytest.fail("default visual input must not read native field evidence")
    monkeypatch.setattr(input_sequence, "_read_field", forbidden)
    monkeypatch.setattr(input_sequence, "_focus_field_binding", forbidden)
    command = adopt_public_input_command("job-1", {"kind": "input_sequence", "request": {
        "field_goal": "Search", "text": "Java", "submit_search": True}})
    jobs.start("job-1", command, {"handle": 100, "process_id": 200},
        {"image_transport": "supported", "current_vision": "supported"})
    result = done(jobs)
    assert result["status"] == "failed" and result["action_executed"] is False
    assert result["error"]["code"] == "decision_service_disabled"
    assert captures == grounder.calls == provider.calls == coordinator.calls == []


def test_job_cancel_during_candidate_decision_has_zero_real_owner_action_clicks(scene, timed_scene, monkeypatch):
    from types import SimpleNamespace
    from app.api import action
    from app.execution import local_direct_step as direct
    from app.core.local_input_policy import _local_operator_input_scope
    jobs, previous, store, grounder, provider, _ = scene
    coordinator = timed_scene[0]
    coordinator._decision_service = previous._decision_service
    jobs.coordinator = coordinator
    frame = jobs.capture_current()
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 100, "process_id": 200, "process_create_time": 1.5,
        "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=100, process_id=200, title="Fixture", process_name="editor.exe",
        rect=SimpleNamespace(left=0, top=0, right=100, bottom=80))
    manager = SimpleNamespace(bind_window_by_handle=lambda handle: bound, get_bound_window=lambda: bound)
    coordinator._windows = lambda: manager
    monkeypatch.setattr(direct, "WindowsNativeIdentityReader", lambda **kwargs:
        SimpleNamespace(read_identity=lambda handle: deepcopy(identity)))
    monkeypatch.setattr(direct, "_local_operator_input_scope", _local_operator_input_scope)
    class Capture:
        def __init__(self, **kwargs):
            pass
        def capture_window(self, **kwargs):
            # 离线替身补齐真实截图绑定，确保到达 Decision 取消前沿。
            return {**deepcopy(frame), "window_size": {"width": 100, "height": 80}, "roi": None,
                "window_rect": [0, 0, 100, 80], "image_width": 100, "image_height": 80,
                "capture_visibility": {"contract_version": "bound_capture_visibility_v2", "allowed": True,
                    "coordinate_space": "window", "bound_window_handle": 100, "occluded_regions": [], "masked": False}}
    monkeypatch.setattr(direct, "ScreenshotService", Capture)
    monkeypatch.setattr(direct, "_capture_observation", lambda *args: deepcopy(frame))
    monkeypatch.setattr(direct, "_post_action", REAL_POST_ACTION)
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kwargs: Capture().capture_window())
    monkeypatch.setattr(action, "prepare_browser_content", lambda *args: None)
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda plan: None)
    monkeypatch.setattr(action, "write_trace", lambda **kwargs: str(store.session_root / "offline-trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kwargs: None)
    monkeypatch.setattr(action.verifier, "verify_action", lambda *args, **kwargs: {"verified": None})
    clicks = []
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kwargs:
        clicks.append((x, y)) or {"clicked": True, "point": {"x": x, "y": y}})
    provider.during = lambda: jobs.cancel("job-1")
    start(scene)
    result = done(jobs)
    assert len(provider.calls) == len(grounder.calls) == 1, (result.get("error"), (result.get("result") or {}).get("response"))
    assert result["status"] == "cancelled"
    assert coordinator._cancel_wait.is_set() is False and coordinator._shutdown is False
    assert clicks == [], result
    assert result["action_executed"] is False
