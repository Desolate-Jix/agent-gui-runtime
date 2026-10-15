"""普通 Luna 复核只做一次 Responses 分类；全部图片和传输均为离线合成。"""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from threading import Event

import httpx
from PIL import Image
import pytest

from app.judgment import OpenAIDecisionsProvider
from app.judgment.choice_contract import CHOICES
from app.judgment.openai_decisions import DecisionNotConnected


def payload():
    stream = BytesIO()
    Image.new("RGB", (640, 360), (31, 48, 67)).save(stream, format="PNG")
    return {"schema_version": "decision_request.v2", "decision_format": "choice", "enabled_predicates": [],
        "condition": "The requested record is visible.", "phase": "after_action", "action": None,
        "request_sha256": "b" * 64, "frames": [{"role": "after", "capture_id": "fresh-review",
            "data_url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")}]}


def response_body(choice="condition_met"):
    return {"id": "resp-synthetic", "object": "response", "model": "gpt-6-luna", "status": "completed",
        "error": None, "incomplete_details": None, "tools": [], "output": [{"type": "message",
            "id": "msg-synthetic", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": choice, "annotations": []}]}],
        "usage": {"input_tokens": 16, "output_tokens": 2, "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}


@pytest.mark.parametrize('phase', [None, 'final_answer', 'commentary', 'unknown', 1])
def test_actual_responses_message_phase_is_metadata_not_an_extra_answer(monkeypatch, phase):
    monkeypatch.setenv('REVIEW_TEST_KEY', 'synthetic-review-secret')
    body = response_body()
    body['output'][0]['phase'] = phase
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        provider = OpenAIDecisionsProvider(api_key_env='REVIEW_TEST_KEY', client=client)
        if phase in (None, 'final_answer'):
            assert provider.review(payload())['review_result']['choice'] == 'condition_met'
        else:
            with pytest.raises(ValueError, match='ordinary_review_message_invalid'):
                provider.review(payload())


def decision_body():
    return {"model": "gpt-6-luna", "answers": [{"type": "choice", "name": "current_step",
        "choice": "condition_not_met", "confidence": 0.7,
        "probabilities": [{"value": value, "probability": p} for value, p in zip(CHOICES, (0.2, 0.7, 0.1))]}],
        "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12}}


@pytest.mark.parametrize("choice", CHOICES)
def test_exact_ordinary_request_and_result_keep_binding_without_probabilities(monkeypatch, choice):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response_body(choice),
            headers={"x-request-id": "req-review-1", "openai-processing-ms": "123.5"})
    data = payload()
    original = deepcopy(data)
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        result = OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(data)
    assert data == original and len(calls) == 1
    request = calls[0]
    assert str(request.url) == "https://api.openai.com/v1/responses" and request.method == "POST"
    assert request.headers["Accept-Encoding"] == "identity"
    body = json.loads(request.content)
    assert set(body) == {"model", "input", "reasoning", "max_output_tokens", "store", "service_tier"}
    assert body["model"] == "gpt-6-luna" and body["reasoning"] == {"effort": "none"}
    assert body["max_output_tokens"] == 32 and body["store"] is False and body["service_tier"] == "default"
    assert result == {"request_sha256": "b" * 64, "review_result": {"type": "choice", "name": "current_step", "choice": choice},
        "usage": response_body()["usage"], "http_elapsed_ms": result["http_elapsed_ms"],
        "server_processing_ms": 123.5, "provider_request_id": "req-review-1"}
    assert result["http_elapsed_ms"] >= 0
    assert "confidence" not in json.dumps(result) and "probabilities" not in json.dumps(result)
    assert "answers" not in body and "questions" not in body and "tools" not in body


def candidate_payload():
    from app.judgment.candidate_annotation import candidate_annotation_metadata, render_candidate_annotation
    from app.judgment.visual_action_conditions import CANDIDATE_CONDITION
    data = payload()
    data.update(phase="before_action", condition=CANDIDATE_CONDITION)
    frame = data["frames"][0]
    frame["role"] = "before"
    original = base64.b64decode(frame["data_url"].split(",", 1)[1])
    candidate = {"candidate_id": "synthetic-target", "capture_id": frame["capture_id"],
        "bbox": {"x": 200, "y": 100, "w": 120, "h": 40}, "click_point": {"x": 230, "y": 120}}
    metadata = candidate_annotation_metadata({"capture_id": frame["capture_id"], "role": "before",
        "sha256": sha256(original).hexdigest()}, (640, 360), candidate)
    frame["candidate_annotation"] = {"metadata": metadata,
        "data_url": "data:image/png;base64," + base64.b64encode(render_candidate_annotation(original, metadata)).decode("ascii")}
    data["action"] = {"operation": "execute_recognition_plan", "review_scope": "candidate", "goal": "Visible record link",
        "candidate": candidate, "permitted_action": {"kind": "click"}}
    return data


def compact_field_payload():
    from app.judgment.executed_click_annotation import executed_click_metadata
    from tests.test_visual_value_decision import visual_value_payload
    data = visual_value_payload()
    data.update(condition="The target field displays exactly the specified expected text.",
        decision_format="choice", enabled_predicates=[])
    action = data["action"]
    field = action["field"]
    point = field["click_point"]
    rect = field["window_rect"]
    action.update(field_image_scope={"schema": "visual_field_roi.v1", "padding": 16},
        executed_click={"schema": "executed_click.v1", "receipt_sha256": action["focus_receipt_sha256"],
            "click_point": point, "screen_point": {"x": rect[0] + point["x"], "y": rect[1] + point["y"]},
            "window_identity": field["window_identity"], "window_rect": rect, "coordinate_space": "capture_image_pixels"})
    frame = data["frames"][0]
    original = base64.b64decode(frame["data_url"].split(",", 1)[1])
    frame["executed_click_annotation"] = {"metadata": executed_click_metadata({
        "capture_id": frame["capture_id"], "sha256": sha256(original).hexdigest(), "role": frame["role"],
        "window_identity": field["window_identity"]}, (180, 90), action)}
    return data


@pytest.mark.parametrize("case", ["result", "candidate", "text_value", "compact_field"])
def test_review_reuses_exact_prepared_images_and_final_question(monkeypatch, case):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    if case == "candidate":
        data = candidate_payload()
    elif case == "compact_field":
        data = compact_field_payload()
    elif case == "text_value":
        from tests.test_visual_value_decision import visual_value_payload
        data = visual_value_payload()
        data.update(condition="The target field displays exactly the specified expected text.",
            decision_format="choice", enabled_predicates=[])
    else:
        data = payload()
    original = deepcopy(data)
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=decision_body() if request.url.path == "/v1/decisions" else response_body())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client)
        assert provider.judge(data)["choice_result"]["choice"] == "condition_not_met"
        assert provider.review(data)["review_result"]["choice"] == "condition_met"
    assert data == original and len(calls) == 2
    decision, ordinary = calls
    decision_content = decision["input"][0]["content"]
    review_content = ordinary["input"][0]["content"]
    assert review_content[:-1] == decision_content
    question_text = review_content[-1]["text"]
    prefix = "Question and allowed choices (JSON): "
    assert question_text.startswith(prefix)
    encoded, instruction = question_text[len(prefix):].split("\n", 1)
    assert json.loads(encoded) == decision["questions"][0]
    assert "Output exactly one allowed choice value and nothing else" in instruction
    assert "confidence" not in json.dumps(review_content[:-1])
    assert "probabilities" not in json.dumps(review_content[:-1])
    if case == "compact_field":
        assert len(decision_content) == 1 and decision_content[0]["type"] == "input_image"
        assert decision_content[0]["image_url"] != data["frames"][0]["data_url"]


def test_refusal_is_distinct_and_never_invents_scores(monkeypatch):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    body = response_body()
    body["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot assess the supplied evidence."}]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(payload())
    assert result["review_result"] == {"type": "refusal", "name": "current_step", "choice": None}


@pytest.mark.parametrize("mutation,code", [
    (lambda b: b.update(status="incomplete"), "status_invalid"),
    (lambda b: b.update(incomplete_details={"reason": "max_output_tokens"}), "status_invalid"),
    (lambda b: b.update(error={"message": "synthetic-review-secret"}), "status_invalid"),
    (lambda b: b.update(model="other-model"), "model_invalid"),
    (lambda b: b.update(tools=[{"type": "web_search"}]), "tools_invalid"),
    (lambda b: b["output"].append({"type": "function_call"}), "output_invalid"),
    (lambda b: b["output"][0].update(type="function_call"), "message_invalid"),
    (lambda b: b["output"][0].update(role="user"), "message_invalid"),
    (lambda b: b["output"][0].update(status="in_progress"), "message_invalid"),
    (lambda b: b["output"][0].update(tool_calls=[{}]), "message_invalid"),
    (lambda b: b["output"][0]["content"].append({"type": "output_text", "text": "extra"}), "content_invalid"),
    (lambda b: b["output"][0]["content"][0].update(text="condition_met because it is visible"), "choice_invalid"),
    (lambda b: b["output"][0]["content"][0].update(text="condition_met\ncondition_not_met"), "choice_invalid"),
    (lambda b: b["output"][0]["content"][0].update(text="\"condition_met\""), "choice_invalid"),
    (lambda b: b["output"][0]["content"][0].update(text="unknown"), "choice_invalid"),
    (lambda b: b["output"][0]["content"][0].update(text=1), "choice_invalid"),
    (lambda b: b["output"][0]["content"][0].update(type="refusal", refusal="", text=None), "content_invalid"),
    (lambda b: b["usage"].update(total_tokens=1), "usage_invalid"),
    (lambda b: b["usage"].update(input_tokens=True), "usage_invalid"),
])
def test_strict_response_rejection_has_specific_safe_code_and_no_retry(monkeypatch, mutation, code):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    body = response_body()
    mutation(body)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="^ordinary_review_" + code + "$"):
            OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(payload())
    assert len(calls) == 1


@pytest.mark.parametrize("mutation,code", [
    (lambda p: p.pop("schema_version"), "choice_v2_required"),
    (lambda p: p.update(decision_format="predicate"), "choice_v2_required"),
    (lambda p: p.update(enabled_predicates=["condition_met"]), "requested_predicates_invalid"),
    (lambda p: p.update(request_timeout_seconds=0), "budget_invalid"),
    (lambda p: p["frames"][0].update(data_url="not-an-inline-image"), "inline_image_required"),
])
def test_bad_input_is_rejected_before_dispatch(monkeypatch, mutation, code):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    data = payload()
    mutation(data)
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("must not dispatch"))) as client:
        with pytest.raises(ValueError, match="^ordinary_review_" + code + "$"):
            OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(data)


def test_field_content_legacy_is_rejected_instead_of_dropping_second_question(monkeypatch):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    data = payload()
    data["action"] = {"operation": "visual_field_check", "field_phase": "focus", "focus_stage": "after_click",
        "field_content_check": {"schema": "visual_field_content.v1", "clear_existing": False}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("must not dispatch"))) as client:
        with pytest.raises(ValueError, match="^ordinary_review_field_content_unsupported$"):
            OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(data)


@pytest.mark.parametrize("kind,exception,code", [
    ("timeout", TimeoutError, "provider_timeout"), ("transport", OSError, "transport_error"),
    ("redirect", OSError, "http_status_307"), ("http_error", OSError, "http_status_401"),
    ("json_error", ValueError, "protocol_error"), ("oversized", ValueError, "response_too_large")])
def test_transport_is_single_attempt_and_redacts_secret(monkeypatch, kind, exception, code):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    calls = []
    def handle(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic-review-secret", request=request)
        if kind == "transport":
            raise httpx.ConnectError("synthetic-review-secret", request=request)
        if kind == "redirect":
            return httpx.Response(307, headers={"location": "https://synthetic.invalid"})
        if kind == "http_error":
            return httpx.Response(401, text="synthetic-review-secret")
        return httpx.Response(200, text="x" * (64 * 1024 + 1) if kind == "oversized" else "synthetic-review-secret")
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(exception, match="^ordinary_review_" + code + "$") as error:
            OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(payload())
    assert len(calls) == 1 and "synthetic-review-secret" not in str(error.value)


def test_diagnostics_redact_keys_and_reject_invalid_header_values(monkeypatch):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body(),
            headers={"x-request-id": "synthetic-review-secret", "openai-processing-ms": "nan"}))) as client:
        result = OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(payload())
    assert result["provider_request_id"] is None and result["server_processing_ms"] is None
    assert "synthetic-review-secret" not in json.dumps(result)


def test_missing_key_and_closed_provider_never_dispatch(monkeypatch):
    monkeypatch.delenv("REVIEW_TEST_KEY", raising=False)
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("must not dispatch"))) as client:
        provider = OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client)
        with pytest.raises(DecisionNotConnected, match="^ordinary_review_key_missing$"):
            provider.review(payload())
        monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
        provider.close()
        assert not client.is_closed
        with pytest.raises(OSError, match="^ordinary_review_provider_closed$"):
            provider.review(payload())


def test_owned_client_remains_lazy_shared_and_uses_deadline_transport(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    created, transports, calls = [], [], []
    original_client = httpx.Client
    def transport(**_kwargs):
        item = httpx.MockTransport(handle)
        transports.append(item)
        return item
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=decision_body() if request.url.path == "/v1/decisions" else response_body())
    def create_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert kwargs["transport"] is transports[0]
        client = original_client(**kwargs)
        created.append(client)
        return client
    monkeypatch.setattr(module, "DeadlineHTTPTransport", transport)
    monkeypatch.setattr(module.httpx, "Client", create_client)
    provider = module.OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY")
    assert not created and not transports
    assert provider.review(payload())["review_result"]["choice"] == "condition_met"
    assert provider.judge(payload())["choice_result"]["choice"] == "condition_not_met"
    assert len(created) == len(transports) == 1 and len(calls) == 2
    provider.close()
    assert created[0].is_closed


def test_preparation_consumes_request_budget_without_dispatch(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    original = module.result_choice_question
    def slow_question(condition):
        clock[0] += 250_000_000
        return original(condition)
    monkeypatch.setattr(module, "result_choice_question", slow_question)
    data = payload()
    data["request_timeout_seconds"] = 0.2
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("must not dispatch"))) as client:
        with pytest.raises(TimeoutError, match="^ordinary_review_provider_budget_expired$"):
            OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client).review(data)


def test_late_mock_transport_response_is_timeout(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    def handle(_):
        clock[0] += 250_000_000
        return httpx.Response(200, json=response_body())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TimeoutError, match="^ordinary_review_provider_timeout$"):
            OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client, timeout_seconds=0.2).review(payload())


def test_review_uses_same_queue_lock_as_judge(monkeypatch):
    monkeypatch.setenv("REVIEW_TEST_KEY", "synthetic-review-secret")
    entered, release = Event(), Event()
    calls = []
    def handle(request):
        calls.append(request)
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json=decision_body())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="REVIEW_TEST_KEY", client=client)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(provider.judge, payload())
            assert entered.wait(1)
            try:
                with pytest.raises(TimeoutError, match="^ordinary_review_provider_queue_timeout$"):
                    provider.review({**payload(), "request_timeout_seconds": 0.02})
            finally:
                release.set()
            assert pending.result(timeout=1)["choice_result"]["choice"] == "condition_not_met"
    assert len(calls) == 1
