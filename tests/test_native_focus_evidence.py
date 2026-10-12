"""原生焦点观察的传输合同；只用合成图与离线 HTTP。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from app.judgment import OpenAIDecisionsProvider


FOCUS_CONDITION = ("The specified ordinary readable text field visibly has keyboard focus, is enabled and editable, "
    "and is not a password or masked field.")
NATIVE_INTRO = ("Evaluate the screenshot together with the supplied runtime observations. The focus_value_snapshot is a read-only native observation: the currently keyboard-focused writable, enabled, non-password field was read twice consistently, belongs to the bound window and contains the original click point. This is evidence of focus, not task success or permission. Inspect the image to check that this same field matches the requested field goal and has no visible contradictory obstacle.")
NATIVE_QUESTION = ("Given the bound native focus observation, is that focused field the visible intended input target described by action.field.field_goal, with no visible contradiction to entering the specified text? Do not require a blinking caret to be visible when native focus is observed. Reject a wrong target, mismatching location or obstructing popup. Do not require typing or navigation to have already occurred.")


def focus_payload():
    stream = BytesIO()
    Image.new("RGB", (180, 90), "white").save(stream, format="PNG")
    identity = {"target_field_id": "visual-field", "window_handle": 10, "process_id": 20,
        "process_create_time": 123.0, "runtime_id": [42, 1], "window_rect": [100, 200, 180, 90],
        "control_bbox": [20, 20, 100, 20]}
    snapshot = {"contract_version": "text_field_snapshot_reference_v1", "identity": identity,
        "capture_id": "after-click", "read_id": "read-one", "observed_at_ns": 100,
        "source": "uia_value", "value_sha256": sha256(b"old").hexdigest(), "value_length": 3,
        "selection": [0, 0]}
    return {"schema_version": "decision_request.v2", "phase": "after_action", "condition": FOCUS_CONDITION,
        "enabled_predicates": ["condition_met", "visible_error", "needs_agent_review"],
        "review_context": {"goal": "Search", "step_goal": "Address bar", "remaining_plan": [], "allowed_states": []},
        "request_sha256": "a" * 64, "frames": [{"capture_id": "after-click", "role": "after",
            "data_url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")}],
        "action": {"operation": "visual_field_check", "field_phase": "focus", "focus_stage": "after_click",
            "field": {"field_goal": "Browser address bar", "bbox": {"x": 10, "y": 10, "w": 140, "h": 40},
                "click_point": {"x": 40, "y": 30}, "window_identity": {"handle": 10, "process_id": 20,
                    "process_create_time": 123.0}, "window_rect": [100, 200, 180, 90],
                "field_kind": "address_bar", "expected_text": "https://example.test/"},
            "focus_value_snapshot": snapshot}}


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("NATIVE_FOCUS_TEST_KEY", "offline-only")
    bodies = []
    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": q["name"], "probability": .97 if q["name"] == "condition_met" else .01}
            for q in body["questions"]], "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        yield OpenAIDecisionsProvider(api_key_env="NATIVE_FOCUS_TEST_KEY", client=client), bodies


@pytest.mark.parametrize("source", ["uia_value", "uia_text"])
def test_bound_native_focus_is_explained_with_same_image_and_target(wire, source):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"]["focus_value_snapshot"]["source"] = source
    original = deepcopy(payload)
    result = provider.judge(payload)
    assert len(bodies) == 1 and result["request_sha256"] == "a" * 64
    content = bodies[0]["input"][0]["content"]
    assert content[0]["text"] == NATIVE_INTRO
    assert bodies[0]["questions"][0]["instructions"] == NATIVE_QUESTION
    assert [p["image_url"] for p in content if p["type"] == "input_image"] == [payload["frames"][0]["data_url"]]
    action_text = next(p["text"] for p in content if p.get("text", "").startswith("Proposed action context"))
    assert json.loads(action_text.split(": ", 1)[1]) == payload["action"]
    assert payload == original


def test_wrong_target_description_is_sent_unchanged_for_native_focus_semantic_review(wire):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"]["field"]["field_goal"] = "The web page search field in the middle of the page"
    provider.judge(payload)
    assert bodies[0]["questions"][0]["instructions"] == NATIVE_QUESTION
    assert any(payload["action"]["field"]["field_goal"] in p.get("text", "") for p in bodies[0]["input"][0]["content"])


@pytest.mark.parametrize("path,value", [
    (("contract_version",), "unknown"), (("source",), "roi_ocr"), (("read_id",), ""),
    (("observed_at_ns",), True), (("observed_at_ns",), 0), (("capture_id",), "old"),
    (("identity", "target_field_id"), "other"), (("identity", "window_handle"), 11),
    (("identity", "process_id"), 21), (("identity", "process_create_time"), 124.0),
    (("identity", "process_create_time"), True), (("identity", "process_create_time"), float("nan")),
    (("identity", "window_rect"), [0, 0, 180, 90]), (("identity", "runtime_id"), []),
    (("identity", "runtime_id"), [True]), (("identity", "control_bbox"), [50, 20, 100, 20]),
    (("identity", "control_bbox"), [20, 20, 200, 20]), (("value_sha256",), "bad"),
    (("value_length",), True), (("value_length",), -1), (("selection",), [0, 4]),
])
def test_mismatched_or_malformed_native_focus_refuses_before_http(wire, path, value):
    provider, bodies = wire
    payload = focus_payload()
    current = payload["action"]["focus_value_snapshot"]
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(ValueError, match="decision_native_focus_evidence_invalid"):
        provider.judge(payload)
    assert bodies == []


@pytest.mark.parametrize("fault", ["extra_snapshot", "extra_identity", "missing", "role", "two_frames", "point", "condition"])
def test_native_focus_closed_binding_refuses_before_http(wire, fault):
    provider, bodies = wire
    payload = focus_payload()
    snapshot = payload["action"]["focus_value_snapshot"]
    if fault == "extra_snapshot": snapshot["trusted"] = True
    elif fault == "extra_identity": snapshot["identity"]["trusted"] = True
    elif fault == "missing": snapshot.pop("source")
    elif fault == "role": payload["frames"][0]["role"] = "before"
    elif fault == "two_frames": payload["frames"].append(deepcopy(payload["frames"][0]))
    elif fault == "point": payload["action"]["field"]["click_point"]["x"] = 160
    else: payload["condition"] = "Navigation has completed"
    with pytest.raises(ValueError, match="decision_native_focus_evidence_invalid"):
        provider.judge(payload)
    assert bodies == []


@pytest.mark.parametrize("scope", ["missing", "selection", "value", "before", "other"])
def test_unrelated_and_missing_snapshot_requests_keep_original_prompt(wire, scope):
    provider, bodies = wire
    payload = focus_payload()
    if scope == "missing": payload["action"].pop("focus_value_snapshot")
    elif scope == "selection": payload["action"]["focus_stage"] = "after_selection"
    elif scope == "value": payload["action"]["field_phase"] = "value"
    elif scope == "before":
        payload["phase"] = "before_action"
        payload["frames"][0]["role"] = "before"
        payload["enabled_predicates"][1] = "unsafe_effect"
    else: payload["action"]["operation"] = "scene_check"
    provider.judge(payload)
    assert bodies[0]["input"][0]["content"][0]["text"] == "Evaluate only visible evidence. Frame roles are temporal labels, not proof of success."
    assert bodies[0]["questions"][0]["instructions"] != NATIVE_QUESTION
