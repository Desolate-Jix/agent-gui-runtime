"""原生超时的显式语义接续；原输入、证明和后图均使用离线原件。"""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.conditional_observation import observe_until_condition
from app.execution.task_plan_contract import validate_task_plan
from tests.test_task_plan_adaptive_review import CONDITION, OfflineAssessment, review_request
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import TARGET, complete_original, scene


def native_plan(*, count=2, action="click", opted=True):
    value = plan(count=count)
    value["schema_version"] = "task_plan.v2"
    if opted:
        value["steps"][0]["verification"].update(decision_condition=CONDITION,
            allowed_states=["Requested detail with no modal choice"])
    if action == "input_sequence":
        value["steps"][0]["action"] = {"kind": action, "field_goal": "Search input",
            "text": "fixture", "clear_existing": True, "submit_search": True}
    return value


def timeout_original(s, *, original=None, baseline_status="absent", transient_match=False):
    original = original or complete_original(s)
    class Clock:
        seconds = 0.0

        def is_set(self):
            return False

        def wait(self, seconds):
            self.seconds += seconds
            return False

    clock = Clock()
    reads = []
    def probe():
        reads.append(True)
        status = ("matched" if len(reads) in (2, 3) else "absent") if transient_match else baseline_status
        value = {"status": status, "source": "uia_exact_name",
            "target_window_handle": TARGET["handle"], "process_id": TARGET["process_id"]}
        if status == "matched":
            value.update(runtime_id=[42, 7], bbox=[2, 3, 10, 12])
        return value

    def capture():
        if transient_match:
            clock.seconds += .001
        return deepcopy(original.capture)

    _, proof = observe_until_condition(probe, capture, probe(),
        timeout_ms=2000, cancel=clock, clock=lambda: clock.seconds)
    proof["expected"] = deepcopy(original.pending["suggested_command"]["observation_condition"])
    observation = original.result["observation"]
    observation.update(source="post_action", authorizes_action=False, readiness="timed_out",
        render_grace_ms=2000, automatic_retry_allowed=False, condition=proof)
    observation["capture"].update(frame_id="after_settled", observation_stage="after_condition_wait",
        render_grace_ms=2000, render_completion_verified=False)
    if original.pending["suggested_command"]["kind"] == "input_sequence":
        original.result["steps"][-1].update(operation="press_key", status="returned")
        original.result["steps"][-1]["receipt"]["observation"] = deepcopy(observation)
    persist_original(s, original)
    return original


def persist_original(s, original):
    write_json_snapshot(s.session / "responses" / (original.command_id + ".json"), original.receipt)


@pytest.mark.parametrize("action", ["click", "input_sequence"])
@pytest.mark.parametrize("baseline_status", ["absent", "matched"])
def test_trusted_mismatch_uses_original_frame_and_advances_once(tmp_path, monkeypatch, action, baseline_status):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(action=action), decision=service)
    original = timeout_original(s, baseline_status=baseline_status)
    path = tmp_path / "responses" / (original.command_id + ".json")
    raw = path.read_bytes()
    advanced = s.runtime.tick(force=True)
    assert advanced["history"][0]["judged_by"] == "decision"
    assert advanced["history"][0]["execution_request_id"] == original.command_id
    assert advanced["pending"]["step_id"] == "step-1"
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 2
    assert service.calls[0]["condition"] == CONDITION
    assert service.calls[0]["frames"][0]["sha256"] == original.capture["sha256"]
    assert service.calls[0]["review_context"]["allowed_states"] == ["Requested detail with no modal choice"]
    assert path.read_bytes() == raw
    assert read_json_snapshot(path)["result"]["observation"]["condition"]["after_capture_rechecked"] is False


def test_early_match_capture_then_disappearance_can_finish_as_trusted_timeout(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(count=1), decision=service)
    original = timeout_original(s, transient_match=True)
    proof = original.result["observation"]["condition"]
    assert proof["status"] == "timed_out" and proof["after_capture_rechecked"] is False
    assert proof["capture_elapsed_ms"] == 2 and proof["elapsed_ms"] == 2001
    assert [sample["status"] for sample in proof["samples"][:3]] == ["matched", "matched", "absent"]
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed" and len(service.calls) == 1


@pytest.mark.parametrize("action", ["click", "input_sequence"])
def test_complete_native_proof_remains_local_without_decision(tmp_path, monkeypatch, action):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(count=1, action=action), decision=service)
    complete_original(s)
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed" and terminal["history"][0]["judged_by"] == "native_condition"
    assert service.calls == [] and len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("policy", ["global_auto", "global_shadow", "step"])
def test_always_main_pauses_native_success_and_mismatch_without_decision(tmp_path, monkeypatch, complete, policy):
    source, service = native_plan(count=1), OfflineAssessment(disposition="continue")
    if policy == "step":
        source["steps"][0]["verification"]["review_policy"] = "always_main"
    else:
        service.status = lambda: {"contract_version": "decision_profile.v2", "profile_sha256": "e" * 64,
            "adoption_mode": "shadow" if policy == "global_shadow" else "auto", "review_policy": "always_main"}
    s = scene(tmp_path, monkeypatch, source=source, decision=service)
    original = complete_original(s) if complete else timeout_original(s)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert waiting["review_packet"]["reason"] == "decision_always_main"
    assert waiting["pending"]["execution_request_id"] == original.command_id and service.calls == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("field", ["decision_condition", "allowed_states", "review_policy", "wait_policy"])
def test_v1_cannot_opt_in_to_native_semantic_continuation(field):
    value = native_plan()
    value["schema_version"] = "task_plan.v1"
    options = {"decision_condition": CONDITION, "allowed_states": [], "review_policy": "always_main",
        "wait_policy": {"loading_condition": "Loading", "completion_excludes_loading": True}}
    value["steps"][0]["verification"] = {**plan()["steps"][0]["verification"], field: options[field]}
    with pytest.raises(ValueError, match="verification_fields"):
        validate_task_plan(value)


@pytest.mark.parametrize("option", [{"allowed_states": []}, {"review_policy": "always_main"},
    {"wait_policy": {"loading_condition": "Loading", "completion_excludes_loading": True}}])
def test_native_controls_require_explicit_decision_condition(option):
    value = native_plan(opted=False)
    value["steps"][0]["verification"].update(option)
    with pytest.raises(ValueError, match="decision_condition_required"):
        validate_task_plan(value)


@pytest.mark.parametrize("option", [{"decision_condition": " "}, {"decision_condition": False},
    {"allowed_states": "normal"}, {"allowed_states": [""]}, {"review_policy": "adaptive"},
    {"wait_policy": {}}, {"wait_policy": {"loading_condition": "Loading", "completion_excludes_loading": 1}},
    {"wait_policy": {"loading_condition": " ", "completion_excludes_loading": True}}, {"before_action": True}])
def test_native_options_reuse_strict_decision_contract(option):
    value = native_plan()
    value["steps"][0]["verification"].update(option)
    with pytest.raises(ValueError):
        validate_task_plan(value)


@pytest.mark.parametrize("version", ["task_plan.v1", "task_plan.v2"])
def test_unselected_native_timeout_stays_manual_without_decision(tmp_path, monkeypatch, version):
    source = native_plan(opted=False)
    source["schema_version"] = version
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=source, decision=service)
    original = timeout_original(s)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["pending"]["execution_request_id"] == original.command_id
    assert waiting["wait_reason"] == "verification_required"
    assert service.calls == [] and len(list(tmp_path.glob("commands/*.json"))) == 1


_DAMAGE = [
    ("source", "other"), ("authorizes_action", True), ("readiness", "unknown"),
    ("render_grace_ms", True), ("automatic_retry_allowed", True),
    ("capture.frame_id", "before"), ("capture.observation_stage", "unknown"),
    ("capture.render_grace_ms", 0), ("capture.render_completion_verified", True),
    ("condition", []), ("condition", ["unknown"]), ("condition.status", "error"), ("condition.status", "condition_met"),
    ("condition.source", "other"), ("condition.expected", {"text": "Other", "control_type": "Text"}),
    ("condition.after_sha256", "a" * 64), ("condition.after_capture_rechecked", True),
    ("condition.timeout_ms", 0), ("condition.timeout_ms", True), ("condition.timeout_ms", 1000),
    ("condition.elapsed_ms", float("nan")), ("condition.elapsed_ms", 10),
    ("condition.elapsed_ms", 10 ** 1000), ("condition.capture_elapsed_ms", -1),
    ("condition.capture_elapsed_ms", float("inf")), ("condition.capture_elapsed_ms", 3000),
    ("condition.deadline_scope", "unknown"), ("condition.deadline_exceeded", None),
    ("condition.task_effect_verified", True), ("condition.render_completion_verified", True),
    ("condition.automatic_retry_allowed", True), ("condition.baseline", []),
    ("condition.baseline.status", "unknown"), ("condition.baseline.source", "other"),
    ("condition.baseline.target_window_handle", True), ("condition.baseline.process_id", 23),
    ("condition.baseline.extra", "unknown"), ("condition.samples", []), ("condition.samples", None),
    ("condition.samples.1", []), ("condition.samples.1.status", "ambiguous"),
    ("condition.samples.1.status", "unavailable"), ("condition.samples.1.status", "error"),
    ("condition.samples.1.status", "unknown"), ("condition.samples.1.source", "other"),
    ("condition.samples.1.target_window_handle", 12), ("condition.samples.1.process_id", "22"),
    ("condition.samples.1.elapsed_ms", True), ("condition.samples.1.elapsed_ms", -1),
    ("condition.samples.1.elapsed_ms", float("nan")), ("condition.samples.1.elapsed_ms", 2100),
    ("condition.samples.2.elapsed_ms", 0), ("condition.samples.1.extra", "unknown"),
    ("capture.sha256", "a" * 64), ("capture.capture_id", "other"),
    ("capture.image_path", "bad\0path"), ("capture.window_identity.process_create_time", 34),
]


def damage(original, field, value, *, search=False):
    observation = (original.result["steps"][-1]["receipt"]["observation"] if search
        else original.result["observation"])
    observation["capture"] = deepcopy(observation["capture"])
    path = field.split(".")
    current = observation
    for key in path[:-1]:
        current = current[int(key)] if isinstance(current, list) else current[key]
    key = int(path[-1]) if isinstance(current, list) else path[-1]
    current[key] = deepcopy(value)


@pytest.mark.parametrize("field,value", _DAMAGE)
def test_damaged_timeout_proof_never_dispatches_decision(tmp_path, monkeypatch, field, value):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(), decision=service)
    original = timeout_original(s)
    damage(original, field, value)
    persist_original(s, original)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert "error" not in waiting["wait"]
    assert service.calls == [] and len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("field,value", [("runtime_id", []), ("runtime_id", [True]),
    ("runtime_id", "42"), ("bbox", [0, 0, 0, 1]), ("bbox", [-1, 0, 2, 2]),
    ("bbox", [70, 0, 20, 2]), ("bbox", [0, 0, 2]), ("bbox", [False, 0, 2, 2])])
@pytest.mark.parametrize("where", ["baseline", "samples.1"])
def test_malformed_matched_record_cannot_bypass_native_timeout(tmp_path, monkeypatch, field, value, where):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(), decision=service)
    original = timeout_original(s, baseline_status="matched")
    damage(original, "condition." + where + "." + field, value)
    persist_original(s, original)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert service.calls == []


@pytest.mark.parametrize("defect", ["name", "operation", "action", "identity", "proof", "capture", "missing", "malformed"])
def test_input_sequence_requires_bound_final_search_evidence(tmp_path, monkeypatch, defect):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(action="input_sequence"), decision=service)
    original = timeout_original(s)
    final = original.result["steps"][-1]
    if defect == "name":
        final["name"] = "type"
    elif defect == "operation":
        final["operation"] = "type_text"
    elif defect == "action":
        final["action_executed"] = None
    elif defect == "identity":
        final["receipt"]["target_identity"] = {**final["receipt"]["target_identity"], "process_create_time": 34}
    elif defect == "proof":
        damage(original, "condition.samples.1.status", "unavailable", search=True)
    elif defect == "capture":
        damage(original, "capture.sha256", "a" * 64, search=True)
    elif defect == "missing":
        original.result["steps"] = []
    else:
        original.result["steps"] = [["unknown"]]
    persist_original(s, original)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert "error" not in waiting["wait"] and service.calls == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_backend_independently_rechecks_native_mismatch_before_adoption(tmp_path, monkeypatch):
    from app.execution import task_plan_verification
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(), decision=service)
    original = timeout_original(s)
    damage(original, "condition.samples.1.status", "unavailable")
    persist_original(s, original)
    monkeypatch.setattr(task_plan_verification, "native_mismatch_eligible", lambda *args: True)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["pending"]["execution_request_id"] == original.command_id
    assert waiting["wait"]["error"]["message"] == "task_plan_verification_native_semantic_proof_invalid"
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("disabled", [None, False])
def test_off_service_never_enters_new_native_semantic_evidence_work(tmp_path, monkeypatch, disabled):
    from app.execution import task_plan_verification
    service = None if disabled is None else OfflineAssessment(disposition="continue")
    if service is not None:
        service.enabled = False
    s = scene(tmp_path, monkeypatch, source=native_plan(), decision=service)
    timeout_original(s)
    def forbidden(*args):
        pytest.fail("disabled service must not enter semantic mismatch validation")
    monkeypatch.setattr(task_plan_verification, "native_mismatch_eligible", forbidden)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert service is None or service.calls == []


def test_native_semantic_review_wait_reuses_original_review_and_continue(tmp_path, monkeypatch):
    service = OfflineAssessment()
    s = scene(tmp_path, monkeypatch, source=native_plan(), decision=service)
    original = timeout_original(s)
    path = tmp_path / "responses" / (original.command_id + ".json")
    raw = path.read_bytes()
    waiting = s.runtime.tick(force=True)
    assert waiting["review_packet"]["suggested_verdict"] == "success" and waiting["history"] == []
    for _ in range(3):
        assert s.runtime.tick(force=True) is None
        assert s.runtime.control({"action": "status", "run_id": s.run_id}, "same-native-wait")["wait"] == waiting["wait"]
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1
    reviewed = s.runtime.control(review_request(s, waiting, original), "native-main-review")
    assert reviewed["status"] == "ready" and reviewed["wait"] == waiting["wait"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    s.runtime.control({"action": "continue", "run_id": s.run_id,
        "wait_id": waiting["wait"]["wait_id"]}, "native-main-continue")
    s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 2 and path.read_bytes() == raw


@pytest.mark.parametrize("stage", ["assessment", "backend_authentication"])
def test_native_semantic_late_cancel_preserves_original_terminal_fact(tmp_path, monkeypatch, stage):
    from tests.test_task_plan_queued_cancel import queue_cancel
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(count=1), decision=service)
    original = timeout_original(s)
    if stage == "assessment":
        service.during = lambda: queue_cancel(s)
    else:
        validate, calls = service.validate_result, []
        def cancel_during_authentication(value, **binding):
            calls.append(binding)
            if len(calls) == 2:
                queue_cancel(s)
            return validate(value, **binding)
        monkeypatch.setattr(service, "validate_result", cancel_during_authentication)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["pending"]["execution_request_id"] == original.command_id
    assert waiting["wait"]["error"]["message"] == "task_plan_cancel_pending:queued-plan-cancel"
    command = read_json_snapshot(tmp_path / "commands" / "queued-plan-cancel.json")
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses" / "queued-plan-cancel.json", {
        "status": "returned", "command": command, "result": cancelled})
    terminal = s.runtime.tick(force=True)
    assert terminal["status"] == terminal["runner_state"] == "cancelled"
    assert terminal["history"][0]["verdict"] == "cancelled"
    assert terminal["history"][0]["original_input_status"] == "completed"
    assert terminal["history"][0]["action_executed"] is True and len(service.calls) == 1
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt


@pytest.mark.parametrize("status", ["unknown", "partial"])
def test_unproven_original_input_never_uses_native_semantics(tmp_path, monkeypatch, status):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=native_plan(), decision=service)
    timeout_original(s, original=complete_original(s, status=status))
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert service.calls == [] and len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("final", ["continue", "review_required", "budget_expired"])
def test_native_semantic_wait_policy_reuses_bounded_original_observation(tmp_path, monkeypatch, final):
    from tests.test_task_plan_observation import ObservingAssessment, observation_scene
    source = native_plan(count=1)
    source["steps"][0]["verification"]["wait_policy"] = {
        "loading_condition": "A loading indicator is visible", "completion_excludes_loading": True}
    service = ObservingAssessment(final="review_required" if final == "review_required" else "continue")
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, source=source, service=service)
    timeout_original(s, original=original)
    path = tmp_path / "responses" / (original.command_id + ".json")
    raw = path.read_bytes()
    first = s.runtime.tick(force=True)
    assert first["observation_pending"] is True and first["history"] == [] and len(service.calls) == 1
    clock.seconds = 12.1 if final == "budget_expired" else 1.6
    last = s.runtime.tick(force=True)
    if final == "continue":
        assert last["runner_state"] == "completed" and last["history"][0]["judged_by"] == "decision"
    else:
        assert last["history"] == [] and last["wait_reason"] == "verification_required"
        if final == "budget_expired":
            assert "budget" in last["review_packet"]["reason"]
        else:
            assert last["review_packet"]["assessment"]["disposition"] == "review_required"
        reviewed = s.runtime.control(review_request(s, last, original), "native-observation-main-review")
        assert reviewed["status"] == "completed"
    assert len(service.calls) == (1 if final == "budget_expired" else 2)
    assert len(captures) == (0 if final == "budget_expired" else 1)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1 and path.read_bytes() == raw


def test_disabled_global_always_main_keeps_native_local_success(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    service.enabled = False
    service.status = lambda: {"contract_version": "decision_profile.v2", "profile_sha256": "e" * 64,
        "adoption_mode": "off", "review_policy": "always_main"}
    s = scene(tmp_path, monkeypatch, source=native_plan(count=1), decision=service)
    complete_original(s)
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed" and terminal["history"][0]["judged_by"] == "native_condition"
    assert service.calls == []


@pytest.mark.parametrize("scenario", ["auto", "v1_profile", "off", "shadow", "not_allowlisted", "budget_exhausted"])
def test_native_semantics_preserves_real_offline_profile_allowlist_and_budget(tmp_path, monkeypatch, scenario):
    import httpx
    from app.execution.decision_check import decision_frame
    from app.execution.task_plan_review import review_context
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    from tests.test_openai_decisions import reply
    monkeypatch.setenv("DECISION_NATIVE_TEST_KEY", "synthetic-offline-only")
    requests = []
    def offline(request):
        requests.append(request)
        response = reply()
        response["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": .01})
        return httpx.Response(200, json=response)
    profile = DecisionProfile(contract_version="decision_profile.v1" if scenario == "v1_profile" else "decision_profile.v2",
        mode=scenario if scenario in {"off", "shadow"} else "auto", api_key_env="DECISION_NATIVE_TEST_KEY",
        auto_conditions=[] if scenario == "not_allowlisted" else [CONDITION],
        request_cap=1 if scenario == "budget_exhausted" else 20)
    with httpx.Client(transport=httpx.MockTransport(offline)) as connection:
        service = DecisionService(tmp_path, profile=profile,
            provider=OpenAIDecisionsProvider(api_key_env="DECISION_NATIVE_TEST_KEY", client=connection))
        source = native_plan(count=1)
        s = scene(tmp_path, monkeypatch, source=source, decision=service)
        original = timeout_original(s)
        raw = (tmp_path / "responses" / (original.command_id + ".json")).read_bytes()
        if scenario == "budget_exhausted":
            state = s.runtime.backend.status(s.run_id)
            spent = service.evaluate(request_id="offline-prior-budget-use", execution_request_id=original.command_id,
                condition=CONDITION, frames=[decision_frame(original.capture, TARGET, role="after")],
                review_context=review_context(source, source["steps"][0], source_id=state["plan_id"],
                    source_sha256=state["plan_sha256"]))
            assert spent["adopted"] is True and len(requests) == 1
        previous = len(requests)
        terminal = s.runtime.tick(force=True)
        if scenario == "auto":
            assert terminal["runner_state"] == "completed" and terminal["history"][0]["judged_by"] == "decision"
        else:
            assert terminal["history"] == [] and terminal["wait_reason"] == "verification_required"
        assert len(requests) - previous == (1 if scenario in {"auto", "shadow"} else 0)
        assert service.status()["used"] == (1 if scenario in {"auto", "shadow", "budget_exhausted"} else 0)
        assert (tmp_path / "responses" / (original.command_id + ".json")).read_bytes() == raw
        assert len(list(tmp_path.glob("commands/*.json"))) == 1
