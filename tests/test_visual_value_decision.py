"""纯视觉输入值不伪造原生读值，坏绑定在远端请求前拒绝。"""
from copy import deepcopy
import json

import pytest

from app.execution.visual_field_proof import VISUAL_SELECTION_CONDITION
from tests.test_native_focus_evidence import focus_payload, wire
from tests.test_native_value_evidence import value_payload


def visual_value_payload():
    value = value_payload()
    value["action"].update(value_verification="visual", actual_text=None, value_reading=None)
    return value


def test_visual_value_uses_screenshot_without_claiming_expected_text_was_read(wire):
    provider, bodies = wire
    request = visual_value_payload()
    original = deepcopy(request)
    provider.judge(request)
    content = bodies[0]["input"][0]["content"]
    context = next(item["text"] for item in content if item.get("text", "").startswith("Proposed action context"))
    action = json.loads(context.split(": ", 1)[1])
    assert action["value_verification"] == "visual"
    assert action["actual_text"] is None and action["value_reading"] is None
    question = bodies[0]["questions"][0]["instructions"]
    assert "comparison target, not an observed value" in question
    assert "clipped" in question and "wrong field" in question
    assert request["condition"] in question
    assert "bound native value" not in question
    assert request == original


@pytest.mark.parametrize("mutation", ["actual", "reading", "snapshot", "expected", "field_expected",
    "phase", "field_phase", "condition", "receipt", "stage", "marker", "frame_role"])
def test_visual_value_rejects_mixed_or_invalid_evidence_before_http(wire, mutation):
    provider, bodies = wire
    payload = visual_value_payload()
    action = payload["action"]
    if mutation == "actual": action["actual_text"] = action["expected_text"]
    elif mutation == "reading": action["value_reading"] = value_payload()["action"]["value_reading"]
    elif mutation == "snapshot": action["focus_value_snapshot"] = focus_payload()["action"]["focus_value_snapshot"]
    elif mutation == "expected": action["expected_text"] = "different"
    elif mutation == "field_expected": action["field"]["expected_text"] = "different"
    elif mutation == "phase":
        payload["phase"] = "before_action"
        payload["enabled_predicates"][1] = "unsafe_effect"
    elif mutation == "field_phase": action["field_phase"] = "focus"
    elif mutation == "condition": payload["condition"] = "unrelated"
    elif mutation == "receipt": action["input_receipt_sha256"] = "bad"
    elif mutation == "stage": action["focus_stage"] = "after_selection"
    elif mutation == "marker": action["value_verification"] = "trust_input"
    elif mutation == "frame_role": payload["frames"][0]["role"] = "before"
    with pytest.raises(ValueError, match="decision_visual_value_evidence_invalid"):
        provider.judge(payload)
    assert bodies == []


def test_empty_field_selection_is_explicit_without_treating_placeholder_as_value(wire):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"].pop("focus_value_snapshot")
    payload["action"].update(focus_stage="after_selection")
    payload["condition"] = VISUAL_SELECTION_CONDITION
    provider.judge(payload)
    question = bodies[0]["questions"][0]["instructions"]
    assert "empty" in question and "placeholder" in question
    assert "all existing characters" in question
    assert "clearly empty" in question and "no selection highlight is required" in question
    assert "clearly empty in both the before and after frames" in question
    assert "caret blink alone is not focus loss" in question


@pytest.mark.parametrize("mismatch", ["condition", "field_phase", "missing_field_phase"])
def test_selection_metadata_cannot_replace_a_different_condition_or_phase(wire, mismatch):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"].pop("focus_value_snapshot")
    payload["action"].update(focus_stage="after_selection")
    payload["condition"] = VISUAL_SELECTION_CONDITION
    if mismatch == "condition":
        payload["condition"] = "The requested result page is loaded."
    elif mismatch == "field_phase":
        payload["action"]["field_phase"] = "value"
    else:
        payload["action"].pop("field_phase")
    original = deepcopy(payload)
    provider.judge(payload)
    question = bodies[0]["questions"][0]["instructions"]
    assert payload["condition"] in question
    assert "Assess only replacement readiness" not in question
    assert payload == original


def test_visual_focus_requires_visible_focus_evidence_without_future_typing(wire):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"].pop("focus_value_snapshot")
    provider.judge(payload)
    question = bodies[0]["questions"][0]["instructions"]
    assert "selected input text" in question and "active-field styling" in question
    assert "prior click alone" in question and "Do not require the expected text" in question
    assert payload["condition"] in question


def test_focus_pair_keeps_both_frames_and_explains_caret_continuity(wire):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"].pop("focus_value_snapshot")
    first = deepcopy(payload["frames"][0])
    first.update(role="before", capture_id="original-click-after")
    payload["frames"].insert(0, first)
    provider.judge(payload)
    question = bodies[0]["questions"][0]["instructions"]
    assert "Compare the before and after frames" in question
    assert "caret blink alone" in question
    assert "focus moves elsewhere" in question
    assert payload["condition"] in question


@pytest.mark.parametrize("stage", ["after_click", "after_selection"])
def test_focus_upload_omits_future_text_but_keeps_original_binding(wire, stage):
    provider, bodies = wire
    payload = focus_payload()
    payload["action"].pop("focus_value_snapshot")
    payload["action"].update(focus_stage=stage)
    payload["action"]["field"]["expected_text"] = "https://www.google.com"
    if stage == "after_selection":
        payload["condition"] = VISUAL_SELECTION_CONDITION
    original = deepcopy(payload)
    provider.judge(payload)
    content = bodies[0]["input"][0]["content"]
    context = next(item["text"] for item in content if item.get("text", "").startswith("Proposed action context"))
    assert "https://www.google.com" not in context
    action = json.loads(context.split(": ", 1)[1])
    assert action["field"]["field_goal"] == payload["action"]["field"]["field_goal"]
    assert "expected_text" not in action and "expected_text" not in action["field"]
    assert payload == original


@pytest.mark.parametrize("stage", ["after_click", "after_selection", "value"])
def test_visual_field_sends_bound_same_frame_detail_and_original(wire, stage):
    provider, bodies = wire
    payload = visual_value_payload() if stage == "value" else focus_payload()
    if stage != "value":
        payload["action"].pop("focus_value_snapshot")
        payload["action"]["focus_stage"] = stage
        if stage == "after_selection":
            payload["condition"] = VISUAL_SELECTION_CONDITION
    original = deepcopy(payload)
    provider.judge(payload)
    content = bodies[0]["input"][0]["content"]
    images = [item["image_url"] for item in content if item["type"] == "input_image"]
    assert len(images) == 2 * len(payload["frames"])
    for index, frame in enumerate(payload["frames"]):
        assert images[index * 2] == frame["data_url"]
    details = [json.loads(item["text"].split(": ", 1)[1]) for item in content
        if item.get("text", "").startswith("Same-frame field detail: ")]
    assert [item["source_capture_id"] for item in details] == [item["capture_id"] for item in payload["frames"]]
    assert payload == original


@pytest.mark.parametrize("width", [990, 1900])
def test_wide_visual_field_detail_preserves_every_target_pixel(wire, width):
    from PIL import Image
    from tests.test_native_field_detail import png_url, decode, details
    provider, bodies = wire
    payload = focus_payload()
    payload["action"].pop("focus_value_snapshot")
    payload["action"]["field"].update(window_rect=[18, 10, 2200, 1372],
        bbox={"x": 75, "y": 43, "w": width, "h": 35})
    original = Image.new("RGB", (2200, 1372), "white")
    original.putpixel((75 + width - 1, 60), (1, 2, 3))
    payload["frames"][0]["data_url"] = png_url(original)
    provider.judge(payload)
    content = bodies[0]["input"][0]["content"]
    images = [item["image_url"] for item in content if item["type"] == "input_image"]
    assert len(images) == 2
    assert details(bodies[0])[0]["crop_bbox"] == {"x": 59, "y": 27, "w": width + 32, "h": 67}
    assert decode(images[1]).convert("RGBA").tobytes() == original.crop((59, 27, 75 + width + 16, 94)).convert("RGBA").tobytes()
