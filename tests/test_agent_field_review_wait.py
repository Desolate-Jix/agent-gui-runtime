"""原 compound 输入只派发一次；Main 审核与继续分离，全部模型传输为离线。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter_ns, sleep
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from app.core.input_sequence_partial import _compound_input_fact, _digest, _request
from app.execution.visual_field_proof import _raise_field_review, VisualFieldReviewRequired, VISUAL_TEXT_VALUE_CONDITION
from app.execution.action_review import CANDIDATE_CONDITION, SCENE_CONDITION, FRESHNESS_CONDITION
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.vision.agent_command_jobs import AgentCommandError, AgentCommandJobs
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_luna_choice_review_provider import decision_body, response_body


IDENTITY = {"handle": 10, "process_id": 20, "process_create_time": 123.0}
SPEC = {"field_goal": "The ordinary editor", "text": "confirmed text", "clear_existing": True, "submit_search": False}


def wait_for(jobs, status):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        value = jobs.get("field-job")
        if value["status"] == status:
            return value
        if value["status"] in {"failed", "cancelled", "completed"}:
            pytest.fail(f"unexpected terminal status {value['status']}: {value.get('error')}")
        sleep(.005)
    pytest.fail(f"did not reach {status}: {value}")


def review_for(packet, verdict="success"):
    return {"action": "review", "run_id": packet["run_id"], "step_id": packet["step_id"],
        "execution_request_id": packet["execution_request_id"], "verdict": verdict,
        "reason": "The original image shows the required exact text.",
        "evidence_sha256": packet["after"]["sha256"], "review_packet_sha256": packet["packet_sha256"],
        "evidence_set_sha256": packet["evidence_set_sha256"], "assessment_round": 0}


@pytest.fixture
def field_wait_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("FIELD_REVIEW_TEST_KEY", "offline-synthetic-key")
    calls, inputs, approvals = [], [], []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=decision_body() if "decisions" in request.url.path
                              else response_body("condition_not_met"))
    client = httpx.Client(transport=httpx.MockTransport(handle))
    service = DecisionService(tmp_path, profile=DecisionProfile.model_validate({
        "contract_version": "decision_profile.v2", "mode": "auto", "decision_format": "choice",
        "ordinary_review": "on_reject", "api_key_env": "FIELD_REVIEW_TEST_KEY", "request_cap": 20,
        "auto_conditions": [VISUAL_TEXT_VALUE_CONDITION, CANDIDATE_CONDITION, SCENE_CONDITION, FRESHNESS_CONDITION]}),
        provider=OpenAIDecisionsProvider(api_key_env="FIELD_REVIEW_TEST_KEY", client=client))
    frame_path = tmp_path / "after.png"
    Image.new("RGB", (180, 90), "white").save(frame_path)
    frame = {"role": "after", "capture_id": "after-one", "image_path": str(frame_path),
        "sha256": sha256(frame_path.read_bytes()).hexdigest(), "window_identity": IDENTITY}
    verification = {"kind": "agent_judgment", "decision_condition": "The exact text is visible."}
    plan = {"schema_version": "task_plan.v3", "title": "Field review", "goal": "Fill the editor", "inputs": {},
        "steps": [{"step_id": "edit", "action": {"kind": "input_sequence", **SPEC}, "verification": verification}],
        "completion": {"step_id": "edit", "verification": verification}}
    action_review = {"schema": "action_review_context.v1", "plan": plan, "run_id": "trial-field",
        "step_id": "edit", "attempt_id": "attempt-1", "budget_ms": 60000}
    dispatch = {"schema": "typing_dispatch.v1", "focus_dispatch": "not_started", "selection_dispatch": "completed",
        "text_dispatch": "completed", "submit_dispatch": "not_started", "input_started": True,
        "action_executed": True, "artifact_is_authorization": False,
        "events": [{"phase": phase, "status": state, "elapsed_ms": float(index)}
            for index, (phase, state) in enumerate([("selection", "started"), ("selection", "completed"),
                                                 ("text", "started"), ("text", "completed")])]}
    click = {"clicked": True, "window_handle": 10, "window_point": {"x": 40, "y": 30}}
    typed = {"typed": True, "window_handle": 10, "text_length": len(SPEC["text"]), "clear_existing": True,
        "click_before_typing": False, "submit": False, "typing_dispatch": dispatch}
    fact = {"schema": "visual_compound_input.v1", "text_sha256": sha256(SPEC["text"].encode()).hexdigest(),
        "text_length": len(SPEC["text"]), "clear_existing": True, "submit": False,
        "window_identity": IDENTITY, "window_rect": [0, 0, 180, 90], "point": {"x": 40, "y": 30},
        "execution_request_id": "field-job", "click_result_sha256": _digest(click),
        "typing_dispatch": dispatch, "type_result": typed}
    receipt = {"contract_version": "local_direct_step_v1", "step_id": "local-input-1", "phase": "returned",
        "operation": "execute_recognition_plan", "local_input_scope_closed": True, "finished_at": "2026-10-15T00:00:00Z",
        "action_executed": True, "target_identity": {"contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity", "status": "observed", "target_window_handle": 10,
            "process_id": 20, "process_create_time": 123.0, "executable_path": "C:/offline.exe"},
        "target_window_geometry": {"coordinate_space": "screen_pixels", "rect_format": "ltrb", "rect": [0, 0, 180, 90]},
        "request": {"goal": SPEC["field_goal"]}, "response": {"success": True, "data": {
            "execution_path": {"action_executed": True}, "click_result": click, "visual_compound_input": fact}},
        "observation": {"status": "captured", "capture": frame}}
    progress = {"contract_version": "input_sequence_v1", "sequence_id": "sequence-one", "status": "running",
        "phase": "check_input", "target": {"handle": 10, "process_id": 20},
        "steps": [{"name": "focus_type", "operation": "execute_recognition_plan", "status": "returned",
                   "action_executed": True, "receipt": receipt}], "completed_steps": ["focus_type"],
        "action_executed": True, "automatic_retry_allowed": False, "observation": receipt["observation"],
        "text_length": len(SPEC["text"]), "text_sha256": fact["text_sha256"], "submit_search": False}
    assert _compound_input_fact(progress, _request(SPEC), IDENTITY)["completed"]
    field = {"field_goal": SPEC["field_goal"], "expected_text": SPEC["text"], "window_identity": IDENTITY,
        "bbox": {"x": 10, "y": 10, "w": 140, "h": 40}, "click_point": {"x": 40, "y": 30},
        "window_rect": [0, 0, 180, 90], "field_kind": "text"}
    request = {"request_id": "field-decision-one", "execution_request_id": "field-job", "step_id": "local-input-1",
        "mode": "execution", "phase": "after_action", "condition": VISUAL_TEXT_VALUE_CONDITION, "frames": [frame],
        "action": {"operation": "visual_field_check", "field_phase": "value", "focus_stage": None,
            "field": field, "expected_text": SPEC["text"], "actual_text": None, "value_reading": None, "focus_receipt_sha256": _digest(receipt),
            "input_receipt_sha256": _digest(receipt), "value_verification": "visual"},
        "review_context": {"goal": plan["goal"], "step_goal": SPEC["field_goal"], "remaining_plan": [],
            "allowed_states": [], "source_id": "trial-field", "source_sha256": _digest(plan)}}
    assessment = service.evaluate(**request)
    assert assessment["status"] == "completed" and assessment["adopted"] is False, {k: assessment.get(k) for k in ("status", "reason", "error_type", "reason_codes")}
    assert assessment["ordinary_review"]["review_result"]["choice"] == "condition_not_met"
    context = {"service": service, "execution_request_id": "field-job", "action_review": action_review,
        "native_field_evidence": False, "deadline_ns": perf_counter_ns() + 60_000_000_000, "cancelled": lambda: False}
    with pytest.raises(VisualFieldReviewRequired) as caught:
        _raise_field_review(service, request, assessment, context, "visual_field_requires_review")
    error = caught.value
    progress["input_check"] = {"status": "unavailable", "phase": "check_input", "reason": str(error)}
    progress["main_handoff"] = {**error.to_reference(), "stage": "after_type", "original_input": {
        "completed_steps": ["focus_type"], "interrupted_at": "check_input", "action_executed": True,
        "input_check": deepcopy(progress["input_check"]), "typing_dispatch": deepcopy(dispatch)}}
    coordinator = SimpleNamespace(_decision_service=service, _owner=SimpleNamespace(call=lambda callback: callback()))
    store = GroundingHandoffStore(tmp_path, owner_id="owner-field")
    jobs = AgentCommandJobs(coordinator, store, lambda: frame, RecognitionSourceConfig(source="agent_current"))
    jobs.field_review_plan_validator = lambda command_id, binding: True
    state = SimpleNamespace(jobs=jobs, service=service, calls=calls, inputs=inputs, approvals=approvals,
        context=context, progress=progress, error=error, frame=frame, request=request, assessment=assessment,
        stage="after_type", after_continue=Event(), damage=None, before_finish=None)
    def sequence(proxy, target, command_request, *, persist, field_review_handler=None, **options):
        if state.damage:
            state.damage(state)
        inputs.append("compound_input")
        job = proxy._job
        index = jobs._begin_dispatch(job, "execute_recognition_plan")
        jobs._record_receipt(job, progress["steps"][0]["receipt"], "execute_recognition_plan", index)
        persist(deepcopy(progress))
        approval = field_review_handler(state.error, stage=state.stage, progress=deepcopy(progress), context=context)
        assert approval.validate() is True
        approvals.append(approval)
        state.after_continue.set()
        if state.before_finish is not None:
            assert state.before_finish.wait(timeout=2)
        finished = {**deepcopy(progress), "status": "completed", "phase": "returned",
            "field_review_resolutions": [{"handoff": deepcopy(progress["main_handoff"]),
                                          "main_review": approval.to_reference()}]}
        finished.pop("main_handoff")
        return finished
    monkeypatch.setattr("app.vision.agent_command_jobs.run_input_sequence", sequence)
    state.start = lambda: jobs.start("field-job", {"kind": "input_sequence", "request": SPEC,
        "action_review": action_review}, {"handle": 10, "process_id": 20},
        {"image_transport": "supported", "current_vision": "supported"})
    yield state
    jobs.close(timeout=1)
    service.close()
    client.close()


@pytest.fixture
def setup(field_wait_scene):
    return field_wait_scene


def test_same_job_waits_review_only_records_continue_resumes_without_input_replay(setup):
    s = setup
    s.start()
    paused = wait_for(s.jobs, "awaiting_field_review")
    packet = s.jobs.get_field_review("field-job")["packet"]
    assert packet == paused["pending_field_review"] and packet["schema"] == "field_review_packet.v1"
    assert packet["request"] == s.request and packet["assessment"] == s.assessment
    assert packet["after"]["sha256"] == s.frame["sha256"] and packet["assessment_round"] == 0
    assert paused["action_executed"] is True and paused["dispatch_attempts"][0]["status"] == "returned"
    assert not s.after_continue.is_set() and s.inputs == ["compound_input"]
    answer = review_for(packet)
    reviewed = s.jobs.review_field("field-job", "main-review-1", answer)
    assert reviewed["review"] == answer
    assert s.jobs.review_field("field-job", "main-review-1", answer) == reviewed
    assert s.jobs.get("field-job")["status"] == "awaiting_field_review"
    assert not s.after_continue.is_set() and len(s.calls) == 2
    s.jobs._jobs["field-job"].action_review_deadline_ns = perf_counter_ns() - 1
    continued = s.jobs.continue_field("field-job", "main-continue-1")
    deadline = s.jobs._jobs["field-job"].action_review_deadline_ns
    assert perf_counter_ns() < deadline <= perf_counter_ns() + 60_000_000_000
    assert continued["status"] in {"running", "completed"}
    finished = wait_for(s.jobs, "completed")
    assert s.jobs.get_field_review("field-job") is None and finished["pending_field_review"] is None
    assert s.jobs.continue_field("field-job", "main-continue-1")["status"] == "completed"
    assert s.jobs._jobs["field-job"].action_review_deadline_ns == deadline
    assert s.inputs == ["compound_input"] and len(s.calls) == 2 and s.after_continue.is_set()


@pytest.mark.parametrize("field", ["run_id", "step_id", "execution_request_id", "evidence_sha256",
    "review_packet_sha256", "evidence_set_sha256", "assessment_round"])
def test_review_requires_every_original_binding(setup, field):
    s = setup
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    answer = review_for(s.jobs.get_field_review("field-job")["packet"])
    answer[field] = 1 if field == "assessment_round" else "wrong-binding"
    with pytest.raises((AgentCommandError, ValueError)):
        s.jobs.review_field("field-job", "bad-review", answer)
    assert s.jobs.get_field_review("field-job")["review"] is None and not s.after_continue.is_set()


def test_continue_needs_success_review_and_conflicting_review_is_rejected(setup):
    s = setup
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    packet = s.jobs.get_field_review("field-job")["packet"]
    with pytest.raises(AgentCommandError):
        s.jobs.continue_field("field-job", "too-early")
    answer = review_for(packet)
    s.jobs.review_field("field-job", "review-one", answer)
    for request_id in ("review-one", "review-two"):
        with pytest.raises(AgentCommandError):
            s.jobs.review_field("field-job", request_id, {**answer, "verdict": "failure"})
    assert not s.after_continue.is_set() and s.inputs == ["compound_input"]


def test_failure_review_terminates_original_job_without_more_input(setup):
    s = setup
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    answer = review_for(s.jobs.get_field_review("field-job")["packet"], "failure")
    s.jobs.review_field("field-job", "reject-original", answer)
    failed = wait_for(s.jobs, "failed")
    assert failed["action_executed"] is True and failed["pending_field_review"] is None
    assert not s.after_continue.is_set() and s.inputs == ["compound_input"]


@pytest.mark.parametrize("method", ["cancel", "close"])
def test_cancel_and_close_notify_waiter_immediately(setup, method):
    s = setup
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    start = monotonic()
    if method == "cancel":
        s.jobs.cancel("field-job")
    else:
        assert s.jobs.close(timeout=1)
    wait_for(s.jobs, "cancelled")
    assert monotonic() - start < 1 and s.inputs == ["compound_input"] and not s.after_continue.is_set()


@pytest.mark.parametrize("artifact", ["after", "progress"])
def test_tampered_original_artifact_cannot_release_input(setup, artifact):
    s = setup
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    packet = s.jobs.get_field_review("field-job")["packet"]
    answer = review_for(packet)
    s.jobs.review_field("field-job", "review-ok", answer)
    path = Path(packet["after"]["image_path"]) if artifact == "after" else Path(s.jobs.store.session_root) / packet["progress_snapshot"]["path"]
    path.write_bytes(b"tampered")
    with pytest.raises((AgentCommandError, ValueError)):
        s.jobs.continue_field("field-job", "continue-tampered")
    assert not s.after_continue.is_set() and s.inputs == ["compound_input"]


@pytest.mark.parametrize("damage", ["unknown", "started", "wrong_stage", "authentication", "timeout", "wrong_run", "cancelled"])
def test_only_authenticated_settled_compound_after_type_can_wait(setup, damage):
    s = setup
    def corrupt(state):
        if damage == "unknown":
            state.progress["steps"][0]["receipt"]["phase"] = "result_unknown"
            state.progress["steps"][0]["status"] = "result_unknown"
        elif damage == "started":
            state.progress["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["typing_dispatch"]["text_dispatch"] = "started"
        elif damage == "wrong_stage":
            state.stage = "before_enter_freshness"
        elif damage == "authentication":
            state.service.validate_result = lambda *a, **kw: False
        elif damage == "timeout":
            state.error = ValueError("visual_field_deadline_expired")
        elif damage == "wrong_run":
            state.context["action_review"] = {**state.context["action_review"], "run_id": "other-run"}
        else:
            state.context["cancelled"] = lambda: True
    s.damage = corrupt
    s.start()
    failed = wait_for(s.jobs, "failed")
    assert failed.get("pending_field_review") is None and s.jobs.get_field_review("field-job") is None
    assert not s.after_continue.is_set() and s.inputs == ["compound_input"]


def test_read_is_a_copy_and_reopened_manager_does_not_resume_durable_wait(setup):
    s = setup
    assert s.jobs.get_field_review("unrelated-job") is None
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    view = s.jobs.get_field_review("field-job")
    view["packet"]["after"]["sha256"] = "forged"
    assert s.jobs.get_field_review("field-job")["packet"]["after"]["sha256"] == s.frame["sha256"]
    reopened = AgentCommandJobs(s.jobs.coordinator, s.jobs.store, lambda: s.frame, s.jobs.configuration)
    try:
        assert reopened.get_field_review("field-job") is None
        with pytest.raises(AgentCommandError):
            reopened.review_field("field-job", "restart-review", review_for(s.jobs.get_field_review("field-job")["packet"]))
    finally:
        reopened.close()


@pytest.mark.parametrize("validator", [None, False])
def test_standalone_declared_run_cannot_park_without_live_plan_binding(setup, validator):
    s = setup
    s.jobs.field_review_plan_validator = None if validator is None else lambda *args: False
    s.start()
    failed = wait_for(s.jobs, "failed")
    assert failed["error"]["code"] == "visual_field_requires_review"
    assert s.jobs.get_field_review("field-job") is None and failed["pending_field_review"] is None
    assert s.inputs == ["compound_input"] and len(s.calls) == 2


def test_live_plan_binding_is_rechecked_before_continue(setup):
    s = setup
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    packet = s.jobs.get_field_review("field-job")["packet"]
    s.jobs.review_field("field-job", "review-original", review_for(packet))
    s.jobs.field_review_plan_validator = lambda *args: False
    with pytest.raises(AgentCommandError, match="no_longer_active"):
        s.jobs.continue_field("field-job", "continue-different-plan")
    assert not s.after_continue.is_set() and s.inputs == ["compound_input"]


def test_issued_approval_checks_original_image_again_on_every_use(setup):
    s = setup
    s.before_finish = Event()
    s.start()
    wait_for(s.jobs, "awaiting_field_review")
    packet = s.jobs.get_field_review("field-job")["packet"]
    s.jobs.review_field("field-job", "review-original", review_for(packet))
    s.jobs.continue_field("field-job", "continue-original")
    assert s.after_continue.wait(timeout=1)
    assert s.approvals[0].validate() is True
    Path(s.frame["image_path"]).write_bytes(b"changed-after-continue")
    with pytest.raises((ValueError, AgentCommandError)):
        s.approvals[0].validate()
    s.before_finish.set()
    wait_for(s.jobs, "failed")
    assert s.inputs == ["compound_input"] and len(s.calls) == 2
