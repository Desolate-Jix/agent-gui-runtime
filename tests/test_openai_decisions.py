"""真实传输适配器的离线协议回归；不读取用户凭据。"""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest


def reply(probability=0.97, danger=0.01):
    return {"model": "gpt-6-luna", "answers": [
        {"type": "predicate", "name": "condition_met", "probability": probability},
        {"type": "predicate", "name": "visible_error", "probability": danger}],
        "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}}}


def payload():
    return {"condition": "详情已打开", "phase": "after_action", "frames": [
        {"role": "after", "capture_id": "c1", "data_url": "data:image/png;base64,aGVsbG8="}],
        "request_sha256": "a" * 64, "action": None}


def test_provider_batches_shared_images_and_preserves_real_usage_and_timings(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    captured = []
    def handle(request):
        captured.append(request)
        return httpx.Response(200, json=reply(), headers={"openai-processing-ms": "564", "x-request-id": "req-123"})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client, timeout_seconds=3)
    result = provider.judge(payload())
    body = json.loads(captured[0].content)
    assert str(captured[0].url) == "https://api.openai.com/v1/decisions"
    assert captured[0].method == "POST" and len(captured) == 1
    assert captured[0].headers["Accept-Encoding"] == "identity"
    assert body["model"] == "gpt-6-luna"
    assert [item["name"] for item in body["questions"]] == ["condition_met", "visible_error"]
    assert len([part for part in body["input"][0]["content"] if part["type"] == "input_image"]) == 1
    assert "详情已打开" in body["questions"][0]["instructions"]
    assert result["predicates"]["condition_met"] == {"type": "predicate", "probability": 0.97}
    assert result["usage"]["total_tokens"] == 12 and result["server_processing_ms"] == 564
    assert result["http_elapsed_ms"] >= 0 and result["provider_request_id"] == "req-123"
    assert captured[0].extensions["timeout"]["read"] == 3
    provider.close()
    assert not client.is_closed
    client.close()


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(model="other"),
    lambda r: r["answers"][0].update(probability=True),
    lambda r: r["answers"][0].update(probability="0.99"),
    lambda r: r["answers"][0].update(probability=float("nan")),
    lambda r: r["answers"][0].update(probability=1.1),
    lambda r: r["answers"][0].update(name="unrequested"),
    lambda r: r["answers"].append(r["answers"][0]),
    lambda r: r["answers"][0].update(click_point=[1, 2]),
    lambda r: r["usage"].update(input_tokens=True),
    lambda r: r["usage"].update(total_tokens=1),
])
def test_provider_rejects_malformed_contract_without_retry(monkeypatch, mutation):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    body = reply()
    mutation(body)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"))
    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(ValueError):
        OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(payload())
    assert len(calls) == 1
    client.close()


def test_refusal_remains_distinct_without_inventing_probability(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    body = reply()
    body["answers"][0] = {"type": "refusal", "name": "condition_met"}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(payload())
    assert result["predicates"]["condition_met"] == {"type": "refusal", "probability": None}


def test_server_diagnostics_cannot_echo_the_credential(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply(),
        headers={"x-request-id": "synthetic-secret", "openai-processing-ms": "synthetic-secret"}))) as client:
        result = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(payload())
    assert result["provider_request_id"] is None and result["server_processing_ms"] is None
    assert "synthetic-secret" not in json.dumps(result)


def test_owned_client_is_created_lazily_reused_and_closed(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    created, requests = [], []
    original_client = httpx.Client
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=reply())
    def create_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = original_client(**kwargs)
        created.append(client)
        return client
    def transport():
        return httpx.MockTransport(handle)
    monkeypatch.setattr(module.httpx, "Client", create_client)
    monkeypatch.setattr(module, "DeadlineHTTPTransport", transport)
    provider = module.OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY")
    assert not created
    assert provider.judge(payload())["usage"]["input_tokens"] == 12
    assert provider.judge(payload())["usage"]["input_tokens"] == 12
    assert len(created) == 1 and len(requests) == 2
    provider.close()
    assert created[0].is_closed


def test_queued_request_times_out_without_second_dispatch(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    entered, release = Event(), Event()
    requests = []
    def handle(request):
        requests.append(request)
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json=reply())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client, timeout_seconds=0.02)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(provider.judge, payload())
            assert entered.wait(1)
            try:
                with pytest.raises(TimeoutError):
                    provider.judge(payload())
            finally:
                release.set()
            assert pending.result(timeout=1)["usage"]["input_tokens"] == 12
    assert len(requests) == 1


@pytest.mark.parametrize("kind", ["timeout", "redirect", "http_error", "json_error"])
def test_transport_failures_are_bounded_no_retry_and_do_not_expose_secret(monkeypatch, kind):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    calls = []
    def handle(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic-secret", request=request)
        if kind == "redirect":
            return httpx.Response(307, headers={"location": "https://evil.invalid"})
        if kind == "json_error":
            return httpx.Response(200, text="synthetic-secret")
        return httpx.Response(401, text="synthetic-secret")
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client)
        with pytest.raises((TimeoutError, OSError, ValueError)) as error:
            provider.judge(payload())
    assert len(calls) == 1 and "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("phase,danger", [("before_action", "unsafe_effect"), ("after_action", "visible_error")])
def test_v2_batches_review_with_bound_context_and_does_not_request_progress(monkeypatch, phase, danger):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    body = reply()
    body["answers"][1]["name"] = danger
    body["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": 0.96})
    captured = []
    def handle(request):
        captured.append(request)
        return httpx.Response(200, json=body)
    data = {**payload(), "schema_version": "decision_request.v2", "phase": phase,
            "enabled_predicates": ["condition_met", danger, "needs_agent_review"],
            "review_context": {"goal": "Inspect record", "step_goal": "Open record",
                               "remaining_plan": ["Read details"], "allowed_states": ["Details page"]}}
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(data)
    sent = json.loads(captured[0].content)
    assert [question["name"] for question in sent["questions"]] == ["condition_met", danger, "needs_agent_review"]
    condition_question = sent["questions"][0]["instructions"]
    if phase == "before_action":
        assert "current action can proceed now" in condition_question
        assert "future completion" not in condition_question
    else:
        assert "temporal evidence" in condition_question
    context_text = [part["text"] for part in sent["input"][0]["content"] if part["type"] == "input_text"]
    if phase == "before_action":
        assert any("Read details" in text and "Details page" in text for text in context_text)
    else:
        assert not any("Read details" in text or "Details page" in text for text in context_text)
    assert result["predicates"]["needs_agent_review"]["probability"] == 0.96 and len(captured) == 1


@pytest.mark.parametrize("scope", ["candidate", "scene", "field_readiness", "freshness"])
def test_before_questions_assess_current_action_without_requiring_later_results(monkeypatch, scope):
    from app.execution.action_review import CANDIDATE_CONDITION, SCENE_CONDITION, FRESHNESS_CONDITION
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    conditions = {"candidate": CANDIDATE_CONDITION, "scene": SCENE_CONDITION, "freshness": FRESHNESS_CONDITION,
        "field_readiness": "The specified ordinary text field is visibly enabled and editable for the permitted input."}
    action = {"operation": "execute_recognition_plan", "review_scope": scope,
        "goal": "Browser address bar", "permitted_action": {"kind": "input_sequence",
            "field_goal": "Browser address bar", "text": "https://www.google.com", "clear_existing": True,
            "submit_search": True}, "native_popup_fact": {"parent_enabled": True, "rect": [2154, 76, 2498, 242]}}
    if scope == "candidate":
        action["candidate"] = {"candidate_id": "address-bar", "bbox": {"x": 62, "y": 36, "w": 1890, "h": 27},
            "click_point": {"x": 1007, "y": 49}, "capture_id": "c1"}
    context = {"goal": "Open Google and search", "step_goal": "Browser address bar",
        "remaining_plan": ["Google main search input field"], "allowed_states": []}
    data = {**payload(), "condition": conditions[scope], "phase": "before_action", "action": action,
        "frames": [{"role": "before", "capture_id": "c1", "data_url": "data:image/png;base64,aGVsbG8="}],
        "schema_version": "decision_request.v2", "enabled_predicates": ["condition_met", "unsafe_effect", "needs_agent_review"],
        "review_context": context}
    if scope == "freshness":
        data["frames"].append({"role": "observation", "capture_id": "c2", "data_url": "data:image/png;base64,bmV3"})
        action["freshness_context"] = {"schema": "action_freshness.v1", "changed_region": {"x": 70, "y": 40, "w": 30, "h": 10}}
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        body = reply()
        body["answers"][1]["name"] = "unsafe_effect"
        body["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": .01})
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(data)
    questions = {q["name"]: q["instructions"] for q in captured[0]["questions"]}
    condition = questions["condition_met"]
    assert conditions[scope] in condition
    assert "current action can proceed now" in condition
    assert "latest supplied pre-action frame" in condition
    assert "do not require its effects or later plan results to be already visible" in condition
    assert "condition and permitted action remain binding" in condition and "refuse" in condition
    assert "future completion" not in condition and "Refuse if the condition needs temporal evidence" not in condition
    review = questions["needs_agent_review"]
    assert "change outside the frozen allowed states" in review
    assert "before the specified original current action can safely proceed" in review
    assert "current permitted action and its declared substeps are planned work, not extra intervention" in review
    assert "popup alone is not an obstacle" in review
    assert "before the supplied remaining plan can run" not in review
    assert questions["unsafe_effect"] == (
        "Would the proposed action have a visibly unsafe, destructive, final submit, send, confirm or payment effect? "
        "Evaluate only the active target flow; do not treat unrelated global navigation as its effect.")
    texts = [p["text"] for p in captured[0]["input"][0]["content"] if p["type"] == "input_text"]
    assert json.loads(next(t.split(": ", 1)[1] for t in texts if t.startswith("Proposed action context"))) == action
    assert json.loads(next(t.split(": ", 1)[1] for t in texts if t.startswith("Frozen scoped task"))) == context
    assert len(captured) == 1


@pytest.mark.parametrize("field_phase", ["focus", "value"])
def test_after_visual_field_questions_keep_state_and_review_only_current_result(monkeypatch, field_phase):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    captured = []
    condition = "The ordinary field visibly has keyboard focus." if field_phase == "focus" else "The field contains the exact expected text."
    data = {**payload(), "condition": condition, "schema_version": "decision_request.v2",
        "enabled_predicates": ["condition_met", "visible_error", "needs_agent_review"],
        "action": {"operation": "visual_field_check", "field_phase": field_phase},
        "review_context": {"goal": "Fill field", "step_goal": "Fill field", "remaining_plan": [], "allowed_states": []}}
    def handle(request):
        captured.append(json.loads(request.content))
        body = reply()
        body["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": .01})
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(data)
    questions = {q["name"]: q["instructions"] for q in captured[0]["questions"]}
    assert questions["condition_met"] == (
        "Is this explicit observable condition met in the after frame? " + condition + " Treat screen change alone as insufficient."
        " Static frames establish visible states, not elapsed time, ongoing playback or future completion. "
        "Frame roles alone are not temporal evidence. Refuse if the condition needs temporal evidence that is not supplied.")
    assert "current declared condition" in questions["needs_agent_review"]
    assert "remaining plan" not in questions["needs_agent_review"]
    assert "current permitted action" not in questions["needs_agent_review"]
    assert questions["visible_error"] == (
        "Is a visible error in the active target flow preventing the expected condition? "
        "Ignore unrelated global navigation or other windows.")


@pytest.mark.parametrize("names", [["condition_met", "visible_error", "still_progressing"],
    ["condition_met", "visible_error", "needs_agent_review", "needs_agent_review"], ["condition_met"]])
def test_v2_rejects_undeclared_predicate_contract_before_transport(monkeypatch, names):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    captured = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: captured.append(request))) as client:
        with pytest.raises(ValueError):
            OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge({
                **payload(), "schema_version": "decision_request.v2", "enabled_predicates": names})
    assert captured == []


def observation_payload():
    value = payload()
    value.update(schema_version="decision_request.v2",
        enabled_predicates=["condition_met", "visible_error", "needs_agent_review", "still_progressing"],
        review_context={"goal": "Open record", "step_goal": "Details visible", "remaining_plan": [], "allowed_states": [],
            "wait_policy": {"loading_condition": "Record loading indicator visible", "completion_excludes_loading": True}},
        assessment_context={"assessment_round": 1, "original_receipt_sha256": "b" * 64,
            "evidence_set_sha256": "c" * 64, "elapsed_ms": 500, "timeout_seconds": 1})
    value["frames"].append({"role": "observation", "capture_id": "c2", "data_url": "data:image/png;base64,bmV3"})
    return value


def test_progress_questions_use_latest_observation_and_explicit_loading_declaration(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    captured = []
    body = reply(0.01)
    body["answers"].extend([{"type": "predicate", "name": "needs_agent_review", "probability": 0.01},
                            {"type": "predicate", "name": "still_progressing", "probability": 0.97}])
    def handle(request):
        captured.append(request)
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(observation_payload())
    sent = json.loads(captured[0].content)
    assert [q["name"] for q in sent["questions"]] == ["condition_met", "visible_error", "needs_agent_review", "still_progressing"]
    assert all("observation" in q["instructions"] for q in sent["questions"])
    assert "Record loading indicator visible" in sent["questions"][-1]["instructions"]
    assert "future completion" in sent["questions"][-1]["instructions"]
    assert result["predicates"]["still_progressing"]["probability"] == 0.97 and len(captured) == 1


@pytest.mark.parametrize("profile_timeout,queue_seconds,dispatch,admission,http_timeout", [
    (3, 0.4, True, 1, 0.6), (0.8, 0.4, True, 0.8, 0.4), (3, 1.1, False, 1, None)])
def test_assessment_http_timeout_deducts_slot_wait_and_never_dispatches_expired_budget(
        monkeypatch, profile_timeout, queue_seconds, dispatch, admission, http_timeout):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    clock, admitted, requests = [0], [], []
    class Slot:
        def acquire(self, *, timeout):
            admitted.append(timeout)
            clock[0] += int(queue_seconds * 1_000_000_000)
            return True
        def release(self):
            pass
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    def handle(request):
        requests.append(request)
        body = reply()
        body["answers"].extend([{"type": "predicate", "name": "needs_agent_review", "probability": 0.01},
                                {"type": "predicate", "name": "still_progressing", "probability": 0.01}])
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = module.OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client, timeout_seconds=profile_timeout)
        provider._lock = Slot()
        if dispatch:
            provider.judge(observation_payload())
            assert requests[0].extensions["timeout"]["read"] == pytest.approx(http_timeout)
        else:
            with pytest.raises(TimeoutError):
                provider.judge(observation_payload())
    assert admitted == [admission] and len(requests) == int(dispatch)
