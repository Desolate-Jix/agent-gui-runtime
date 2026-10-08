"""判断建议必须沿真实工作流回执与结算链消费。"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from tests.test_workflow_trial import services, response, WORKFLOW


CONDITION = "The results panel visibly shows the new query."


class DecisionDouble:
    enabled = True

    def __init__(self, verdict="success", adopted=True):
        self.verdict, self.adopted = verdict, adopted
        self.calls, self.saved = [], {}
        self.on_evaluate = None

    def evaluate(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.on_evaluate:
            self.on_evaluate()
        result = dict(kwargs, status="completed", verdict=self.verdict, adopted=self.adopted,
                      authorizes_action=False, automatic_retry_allowed=False,
                      evidence_hashes=[item["sha256"] for item in kwargs["frames"]])
        self.saved[kwargs["request_id"]] = deepcopy(result)
        return result

    def validate_result(self, result, **binding):
        return self.saved.get(result.get("request_id")) == result and all(result.get(key) == value for key, value in binding.items())


def scene(services, monkeypatch, *, service=None, condition=CONDITION, image=None, success_conditions=None):
    programs, trials, saved, session = services
    library = programs.library
    value = deepcopy(saved["definition"])
    value["steps"] = value["steps"][:1]
    rule = {"kind": "agent_judgment"}
    if condition is not None:
        rule["decision_condition"] = condition
    if image is not None:
        library._artifact_root = image[0]
        rule["image_check"] = image[1]
    value["steps"][0].update(outputs=[], success_conditions=success_conditions or [], verification=rule,
                           branches={"success": None, "failure": None, "uncertain": None})
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "decision-save")
    reviewed = deepcopy(saved["definition"])
    reviewed["steps"][0]["review_status"] = "reviewed"
    saved = programs.save(WORKFLOW, saved["content_sha256"], reviewed, "decision-review")
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "new"}, "decision-start")
    ticket = trials.prepare(run["run_id"], "decision-prepare")
    path = response(session, ticket)
    original = json.loads(path.read_text(encoding="utf-8"))
    original["result"].update(target_identity={"target_window_handle": 1, "process_id": 2, "process_create_time": 3.0},
                               capture={"capture_id": "before"})
    path.write_text(json.dumps(original), encoding="utf-8")
    current = session / "current.png"
    if image is None:
        Image.new("RGB", (80, 60), "white").save(current)
    else:
        current.write_bytes(image[2])
    frame = {"capture_id": "after", "image_path": str(current), "sha256": sha256(current.read_bytes()).hexdigest(),
             "window_identity": {"handle": 1, "process_id": 2, "process_create_time": 3.0},
             "image_size": {"width": 80, "height": 60}, "window_rect": [0, 0, 80, 60]}
    captures = []
    def capture(*args, **kwargs):
        captures.append(True)
        return deepcopy(frame), {}
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    @contextmanager
    def workspace(root):
        yield library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    co = SimpleNamespace(_memory_library_root=library._workspace_root, _owner=SimpleNamespace(call=lambda f: f()))
    if service is not None:
        co._decision_service = service
    from app.learning_memory.runtime_verification import verify_trial_step
    def verify(request_id="decision-verify"):
        return verify_trial_step(co, session_dir=session, request_id=request_id,
            request={"action": "verify", "run_id": run["run_id"], "execution_request_id": ticket["execution_request_id"]})
    return SimpleNamespace(programs=programs, trials=trials, run=run, ticket=ticket, session=session,
                           frame=frame, captures=captures, verify=verify, coordinator=co, saved=saved, receipt_path=path)


@pytest.mark.parametrize("condition", ["", "   ", 1, "x" * 4001])
def test_decision_condition_is_explicit_and_validated(condition):
    from app.learning_memory.workflow_program import _step_rules
    with pytest.raises(ValueError, match="decision_condition"):
        _step_rules({"action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment", "decision_condition": condition}}, {}, {}, {})


@pytest.mark.parametrize("mutation", ["outputs", "read_spec", "read_text"])
def test_predicate_cannot_extract_dynamic_outputs(mutation):
    from app.learning_memory.workflow_program import _step_rules
    step = {"action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment", "decision_condition": CONDITION}}
    if mutation == "read_text":
        step["action"]["kind"] = "read_text"
    else:
        step[mutation] = [{"name": "value", "type": "text"}] if mutation == "outputs" else {}
    with pytest.raises(ValueError, match="decision"):
        _step_rules(step, {}, {}, {})


@pytest.mark.parametrize("setting", ["absent", "off", "missing_condition"])
def test_disabled_or_unreviewed_semantic_route_has_no_capture_or_api(services, monkeypatch, setting):
    service = None if setting == "absent" else DecisionDouble()
    if setting == "off":
        service.enabled = False
    s = scene(services, monkeypatch, service=service, condition=None if setting == "missing_condition" else CONDITION)
    result = s.verify()
    assert result["status"] == "verification_required"
    assert s.captures == []
    assert service is None or service.calls == []
    assert s.trials.status(s.run["run_id"])["pending"]["execution_request_id"] == s.ticket["execution_request_id"]


@pytest.mark.parametrize("verdict,adopted,status", [("success", True, "completed"), ("failure", True, "failed"),
    ("success", False, "verification_required"), ("uncertain", False, "verification_required")])
def test_real_trial_settlement_or_shadow_wait_persists_once(services, monkeypatch, verdict, adopted, status):
    service = DecisionDouble(verdict, adopted)
    s = scene(services, monkeypatch, service=service)
    result = s.verify()
    assert result["status"] == status
    assert len(s.captures) == len(service.calls) == 1
    call = service.calls[0]
    assert call["mode"] == "learning" and call["phase"] == "after_action"
    assert call["condition"] == CONDITION and call["run_id"] == s.run["run_id"]
    assert call["step_id"] == "search" and call["execution_request_id"] == s.ticket["execution_request_id"]
    assert call["frames"][0]["role"] == "after"
    state = s.trials.status(s.run["run_id"])
    assert state["outputs"] == {}
    if adopted:
        assert state["history"][0]["judged_by"] == "decision"
        assert state["history"][0]["receipt_sha256"] == sha256(s.receipt_path.read_bytes()).hexdigest()
    else:
        assert state["history"] == [] and state["pending"]["execution_request_id"] == s.ticket["execution_request_id"]
        assert result["decision_advice"]["verdict"] == verdict
    assert s.verify() == result
    assert s.verify("another-verify") == result
    assert len(s.captures) == len(service.calls) == 1


@pytest.mark.parametrize("change", ["cross_window", "stale", "tampered"])
def test_bad_capture_never_routes_to_decisions(services, monkeypatch, change):
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    if change == "cross_window":
        s.frame["window_identity"]["handle"] = 999
    elif change == "stale":
        s.frame["capture_id"] = "before"
    else:
        s.frame["sha256"] = "a" * 64
    with pytest.raises(ValueError):
        s.verify()
    assert service.calls == [] and s.trials.status(s.run["run_id"])["history"] == []


def test_cancel_during_decision_settles_original_receipt_without_adopting_success(services, monkeypatch):
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    service.on_evaluate = lambda: s.trials.cancel(s.run["run_id"], "cancel-during-decision")
    result = s.verify()
    assert result["status"] == "cancelled" and result["outputs"] == {}
    assert result["history"][0]["judged_by"] == "runtime"
    assert len(service.calls) == 1
    assert s.verify() == result and s.verify("cancel-repeat-new-id") == result


def test_condition_change_creates_new_program_and_requires_fresh_review(services, monkeypatch):
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    definition = deepcopy(s.saved["definition"])
    definition["steps"][0]["verification"]["decision_condition"] = "A different visible state."
    newer = s.programs.save(WORKFLOW, s.saved["content_sha256"], definition, "change-condition")
    assert newer["definition"]["steps"][0]["review_status"] == "pending"
    assert s.programs.load(WORKFLOW, s.saved["program_id"])["definition"]["steps"][0]["verification"]["decision_condition"] == CONDITION
    assert s.verify()["status"] == "completed"
    assert service.calls[0]["condition"] == CONDITION


@pytest.mark.parametrize("matched", [True, False])
def test_local_image_positive_skips_decision_and_valid_miss_uses_final_frame(services, tmp_path, monkeypatch, matched):
    from tests.test_image_verification import sample
    from tests.test_image_wait_early_exit import Clock
    check, raw, _, _ = sample(tmp_path)
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service, image=(tmp_path, check, raw))
    if not matched:
        Image.new("RGB", (80, 60), "black").save(s.frame["image_path"])
        s.frame["sha256"] = sha256(open(s.frame["image_path"], "rb").read()).hexdigest()
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    result = s.verify()
    assert result["status"] == "completed"
    assert len(service.calls) == (0 if matched else 1)
    assert len(s.captures) == (1 if matched else 20)
    assert result["history"][0]["judged_by"] == ("rule" if matched else "decision")
    if not matched:
        assert service.calls[0]["frames"][0]["capture_id"] == s.frame["capture_id"]
    assert s.verify() == result


@pytest.mark.parametrize("bad", ["reference", "capture", "ambiguous", "window", "stale"])
def test_invalid_image_evidence_cannot_be_routed_around(services, tmp_path, monkeypatch, bad):
    from tests.test_image_verification import sample
    check, raw, pixels, _ = sample(tmp_path)
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service, image=(tmp_path, check, raw))
    if bad == "reference":
        (tmp_path / "desktop-review/evidence-objects" / (check["reference_sha256"] + ".png")).write_bytes(b"bad")
    elif bad == "capture":
        s.frame["sha256"] = "a" * 64
    elif bad == "ambiguous":
        pixels[35:55, 45:65] = pixels[10:30, 10:30]
        Image.fromarray(pixels).save(s.frame["image_path"], format="PNG")
        s.frame["sha256"] = sha256(open(s.frame["image_path"], "rb").read()).hexdigest()
    elif bad == "window":
        s.frame["window_identity"]["handle"] = 99
    else:
        s.frame["capture_id"] = "before"
    if bad == "stale":
        with pytest.raises(ValueError, match="stale"):
            s.verify()
    else:
        assert s.verify()["status"] == "verification_required"
    assert service.calls == []
    assert s.trials.status(s.run["run_id"])["history"] == []


@pytest.mark.parametrize("mutation", ["image", "receipt"])
def test_evidence_changed_while_service_waits_cannot_settle(services, monkeypatch, mutation):
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    def changed():
        if mutation == "image":
            Image.new("RGB", (80, 60), "black").save(s.frame["image_path"])
        else:
            s.receipt_path.write_bytes(s.receipt_path.read_bytes() + b"\n")
    service.on_evaluate = changed
    with pytest.raises(ValueError):
        s.verify()
    assert len(service.calls) == 1 and s.trials.status(s.run["run_id"])["history"] == []


def test_pending_step_settled_by_another_reviewer_while_waiting_is_not_overwritten(services, monkeypatch):
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    service.on_evaluate = lambda: s.trials.review(s.run["run_id"], "another-review",
        s.ticket["execution_request_id"], "failure", {}, {})
    with pytest.raises(ValueError, match="pending_ticket_mismatch"):
        s.verify()
    state = s.trials.status(s.run["run_id"])
    assert state["status"] == "failed" and len(state["history"]) == 1
    assert state["history"][0]["judged_by"] == "agent"


@pytest.mark.parametrize("mutation", ["decision", "envelope"])
def test_saved_advice_and_observation_are_revalidated_without_second_call(services, monkeypatch, mutation):
    service = DecisionDouble(adopted=False)
    s = scene(services, monkeypatch, service=service)
    assert s.verify()["status"] == "verification_required"
    if mutation == "decision":
        path = s.session / "workflow-decisions/decision-verify.result.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["result"]["adopted"] = True
    else:
        path = s.session / "workflow-observations/decision-verify.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        for field in ("receipt", "observation", "frame"):
            value[field]["window_identity"]["handle"] = 99
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        s.verify("reopen-verification")
    assert len(service.calls) == len(s.captures) == 1
    assert s.trials.status(s.run["run_id"])["history"] == []


def test_reopened_service_reuses_durable_wait_and_original_request(services, monkeypatch):
    service = DecisionDouble(adopted=False)
    s = scene(services, monkeypatch, service=service)
    original = s.verify()
    reopened = DecisionDouble(adopted=False)
    reopened.saved = deepcopy(service.saved)
    s.coordinator._decision_service = reopened
    assert s.verify("reopened-new-id") == original
    assert reopened.calls == [] and len(s.captures) == 1


@pytest.mark.parametrize("mode,p,error,expected", [("auto", 0.99, 0.01, "completed"),
    ("auto", 0.01, 0.01, "failed"), ("shadow", 0.99, 0.01, "verification_required"),
    ("auto", 0.5, 0.01, "verification_required")])
def test_production_service_provider_and_real_trial_chain(services, monkeypatch, mode, p, error, expected):
    import httpx
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    s = scene(services, monkeypatch)
    monkeypatch.setenv("LEARNING_DECISION_SYNTHETIC_KEY", "synthetic-learning-key")
    calls = []
    def provider_reply(request):
        calls.append(request)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": "condition_met", "probability": p},
            {"type": "predicate", "name": "visible_error", "probability": error}],
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}})
    client = httpx.Client(transport=httpx.MockTransport(provider_reply))
    profile = DecisionProfile(mode=mode, api_key_env="LEARNING_DECISION_SYNTHETIC_KEY", auto_conditions=[CONDITION])
    service = DecisionService(s.session, profile=profile,
        provider=OpenAIDecisionsProvider(api_key_env="LEARNING_DECISION_SYNTHETIC_KEY", client=client))
    s.coordinator._decision_service = service
    try:
        result = s.verify()
        assert result["status"] == expected
        assert len(calls) == len(s.captures) == 1
        body = json.loads(calls[0].content)
        assert [item["name"] for item in body["questions"]] == ["condition_met", "visible_error"]
        assert s.verify() == result
        service.close()
        monkeypatch.delenv("LEARNING_DECISION_SYNTHETIC_KEY")
        reopened = DecisionService(s.session, profile=profile,
            provider=OpenAIDecisionsProvider(api_key_env="LEARNING_DECISION_SYNTHETIC_KEY", client=client))
        s.coordinator._decision_service = reopened
        assert s.verify("production-reopened") == result
        assert len(calls) == len(s.captures) == 1
        if expected != "verification_required":
            assert result["history"][0]["judged_by"] == "decision" and result["outputs"] == {}
        else:
            assert result["decision_advice"]["usage"]["total_tokens"] == 15
            assert s.trials.status(s.run["run_id"])["history"] == []
        reopened.close()
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("failure", ["timeout", "refusal", "unknown"])
def test_production_service_failure_stays_waiting_and_replays_without_dispatch(services, monkeypatch, failure):
    import httpx
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    s = scene(services, monkeypatch)
    monkeypatch.setenv("LEARNING_DECISION_SYNTHETIC_KEY", "synthetic-learning-key")
    calls = []
    def provider_reply(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if failure == "unknown":
            raise KeyboardInterrupt()
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "refusal", "name": "condition_met"},
            {"type": "predicate", "name": "visible_error", "probability": 0.01}],
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}})
    client = httpx.Client(transport=httpx.MockTransport(provider_reply))
    profile = DecisionProfile(mode="auto", api_key_env="LEARNING_DECISION_SYNTHETIC_KEY", auto_conditions=[CONDITION])
    service = DecisionService(s.session, profile=profile,
        provider=OpenAIDecisionsProvider(api_key_env="LEARNING_DECISION_SYNTHETIC_KEY", client=client))
    s.coordinator._decision_service = service
    try:
        if failure == "unknown":
            with pytest.raises(KeyboardInterrupt):
                s.verify()
        else:
            first = s.verify()
            assert first["status"] == "verification_required"
        service.close()
        reopened = DecisionService(s.session, profile=profile,
            provider=OpenAIDecisionsProvider(api_key_env="LEARNING_DECISION_SYNTHETIC_KEY", client=client))
        s.coordinator._decision_service = reopened
        result = s.verify("failure-reopened")
        assert result["status"] == "verification_required"
        assert result["decision_advice"]["status"] == {"timeout": "timeout", "refusal": "refused", "unknown": "unknown"}[failure]
        assert result["decision_advice"]["verdict"] == "uncertain"
        assert len(calls) == len(s.captures) == 1
        assert s.verify("failure-repeat") == result
        assert s.trials.status(s.run["run_id"])["history"] == []
        reopened.close()
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("field,value", [("run_id", "other"), ("step_id", "other"),
    ("authorizes_action", True), ("automatic_retry_allowed", True), ("status", "refused")])
def test_even_authenticated_invalid_result_cannot_settle(services, monkeypatch, field, value):
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    evaluate = service.evaluate
    def invalid(**kwargs):
        result = evaluate(**kwargs)
        result[field] = value
        service.saved[kwargs["request_id"]] = deepcopy(result)
        return result
    service.evaluate = invalid
    with pytest.raises(ValueError, match="untrusted"):
        s.verify()
    assert s.trials.status(s.run["run_id"])["history"] == []


def test_missing_credential_fast_return_has_no_semantic_capture_or_judgment_storage(services, monkeypatch):
    from app.judgment import DecisionProfile, DecisionService
    s = scene(services, monkeypatch)
    monkeypatch.delenv("LEARNING_DECISION_NEVER_SET_KEY", raising=False)
    service = DecisionService(s.session, profile=DecisionProfile(api_key_env="LEARNING_DECISION_NEVER_SET_KEY"))
    s.coordinator._decision_service = service
    try:
        result = s.verify()
        assert result["status"] == "verification_required" and result["decision_status"] == "not_connected"
        assert s.captures == []
        assert not (s.session / "workflow-observations").exists()
        assert not (s.session / "workflow-decisions").exists()
        assert not (s.session / "judgments").exists()
    finally:
        service.close()


@pytest.mark.parametrize("verdict,expected", [("success", "verification_required"), ("failure", "failed")])
def test_explicit_predicate_does_not_satisfy_separate_agent_assertion(services, monkeypatch, verdict, expected):
    service = DecisionDouble(verdict=verdict)
    s = scene(services, monkeypatch, service=service, success_conditions=[
        {"left": {"source": "observation", "name": "separate_review"}, "operator": "agent_assertion"}])
    result = s.verify()
    assert result["status"] == expected
    assert s.trials.status(s.run["run_id"])["outputs"] == {}
    if verdict == "success":
        assert s.trials.status(s.run["run_id"])["history"] == []


def test_cancel_event_before_observation_is_zero_capture_and_api(services, monkeypatch):
    from threading import Event
    service = DecisionDouble()
    s = scene(services, monkeypatch, service=service)
    s.coordinator._cancel_wait = Event()
    s.coordinator._cancel_wait.set()
    assert s.verify()["reason"] == "workflow_decision_cancelled"
    assert s.captures == service.calls == []


def test_plain_request_index_tampering_cannot_create_another_provider_dispatch(services, monkeypatch):
    from tests.test_decision_service import setup_service
    s = scene(services, monkeypatch)
    service, calls, client = setup_service(s.session, monkeypatch, mode="shadow", conditions=[CONDITION])
    s.coordinator._decision_service = service
    try:
        first = s.verify()
        assert first["status"] == "verification_required"
        path = s.session / "workflow-decisions" / (s.ticket["execution_request_id"] + ".request.json")
        link = json.loads(path.read_text(encoding="utf-8"))
        link["request_id"] = "tampered-new-verification"
        path.write_text(json.dumps(link), encoding="utf-8")
        s.frame["capture_id"] = "different-fresh-frame"
        replay = s.verify("another-command")
        assert replay["status"] == "verification_required" and replay["reason"] == "workflow_decision_result_untrusted"
        assert len(calls) == 1
        assert s.trials.status(s.run["run_id"])["history"] == []
    finally:
        service.close()
        client.close()
