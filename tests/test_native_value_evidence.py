"""原生输入值仅在完整同帧绑定后解释，坏绑定不得进入 HTTP。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from app.execution.visual_field_proof import VISUAL_VALUE_CONDITION
from tests.test_native_focus_evidence import focus_payload, wire


def value_payload(text="https://www.google.com", source="uia_value"):
    payload = focus_payload()
    action = payload["action"]
    snapshot = action.pop("focus_value_snapshot")
    action["field"]["expected_text"] = text
    snapshot.update(source=source, value_sha256=sha256(text.encode("utf-8")).hexdigest(),
        value_length=len(text), selection=[len(text), len(text)])
    frame = payload["frames"][0]
    reading = {"text": text, "source": source, "frame_sha256": sha256(base64.b64decode(
        frame["data_url"].split(",", 1)[1])).hexdigest(), "capture_id": frame["capture_id"],
        "bbox": deepcopy(action["field"]["bbox"]), "elapsed_ms": 12.0, "evidence": snapshot}
    action.update(field_phase="value", focus_stage=None, focus_receipt_sha256="b" * 64,
        input_receipt_sha256="c" * 64, expected_text=text, actual_text=text, value_reading=reading)
    payload["condition"] = VISUAL_VALUE_CONDITION
    return payload


@pytest.mark.parametrize("source", ["uia_value", "uia_text"])
@pytest.mark.parametrize("text", ["https://www.google.com", "fresh 中文"])
def test_complete_bound_native_value_is_explained_without_requiring_image_ocr(wire, source, text):
    provider, bodies = wire
    payload = value_payload(text, source)
    original = deepcopy(payload)
    provider.judge(payload)
    content = bodies[0]["input"][0]["content"]
    intro = content[0]["text"]
    assert "value_reading" in intro and "complete text" in intro and "not permission" in intro
    question = bodies[0]["questions"][0]["instructions"]
    assert "native value" in question and "wrong target" in question and "obstruction" in question
    assert "character-by-character OCR" in question
    assert payload["condition"] in question
    assert "Refuse if the condition needs temporal evidence" not in question
    assert [p["image_url"] for p in content if p["type"] == "input_image"] == [payload["frames"][0]["data_url"]]
    assert payload == original


@pytest.mark.parametrize("path,value", [
    (("phase",), "before_action"), (("condition",), "Other condition"),
    (("action", "focus_stage"), "after_click"),
    (("action", "focus_receipt_sha256"), "bad"), (("action", "input_receipt_sha256"), None),
    (("action", "expected_text"), "wrong"), (("action", "actual_text"), "wrong"),
    (("action", "field", "expected_text"), "wrong"),
    (("action", "field", "click_point", "x"), 160),
    (("action", "value_reading", "text"), "wrong"),
    (("action", "value_reading", "source"), "roi_ocr"),
    (("action", "value_reading", "capture_id"), "old"),
    (("action", "value_reading", "frame_sha256"), "0" * 64),
    (("action", "value_reading", "bbox", "x"), 11),
    (("action", "value_reading", "bbox", "x"), 10.0),
    (("action", "value_reading", "elapsed_ms"), True),
    (("action", "value_reading", "evidence", "contract_version"), "unknown"),
    (("action", "value_reading", "evidence", "capture_id"), "old"),
    (("action", "value_reading", "evidence", "source"), "uia_text"),
    (("action", "value_reading", "evidence", "read_id"), ""),
    (("action", "value_reading", "evidence", "observed_at_ns"), 0),
    (("action", "value_reading", "evidence", "identity", "window_handle"), 11),
    (("action", "value_reading", "evidence", "identity", "window_rect"), [0, 0, 180, 90]),
    (("action", "value_reading", "evidence", "identity", "control_bbox"), [100, 60, 40, 20]),
    (("action", "value_reading", "evidence", "value_sha256"), "0" * 64),
    (("action", "value_reading", "evidence", "value_length"), 21),
    (("action", "value_reading", "evidence", "selection"), [0, 23]),
])
def test_bad_native_value_binding_rejects_before_http(wire, path, value):
    provider, bodies = wire
    payload = value_payload()
    item = payload
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    if path == ("phase",):
        payload["frames"][0]["role"] = "before"
        payload["enabled_predicates"][1] = "unsafe_effect"
    with pytest.raises(ValueError, match="decision_native_value_evidence_invalid"):
        provider.judge(payload)
    assert bodies == []


@pytest.mark.parametrize("fault", ["extra_snapshot", "extra_reading", "extra_action", "bad_base64", "different_image", "dimensions"])
def test_native_value_closed_evidence_and_actual_image_bytes_are_required(wire, fault):
    provider, bodies = wire
    payload = value_payload()
    reading = payload["action"]["value_reading"]
    if fault == "extra_snapshot": reading["evidence"]["trusted"] = True
    elif fault == "extra_reading": reading["trusted"] = True
    elif fault == "extra_action": payload["action"]["trusted"] = True
    elif fault == "bad_base64": payload["frames"][0]["data_url"] = "data:image/png;base64,not!base64"
    else:
        stream = BytesIO()
        Image.new("RGB", (179, 90) if fault == "dimensions" else (180, 90), "red").save(stream, format="PNG")
        payload["frames"][0]["data_url"] = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
        if fault == "dimensions": reading["frame_sha256"] = sha256(stream.getvalue()).hexdigest()
    with pytest.raises(ValueError, match="decision_native_value_evidence_invalid"):
        provider.judge(payload)
    assert bodies == []


@pytest.mark.parametrize("kind", ["missing", "partial", "roi"])
def test_non_native_value_evidence_keeps_existing_visible_review(wire, kind):
    provider, bodies = wire
    payload = value_payload()
    reading = payload["action"]["value_reading"]
    if kind == "missing": reading.pop("evidence")
    elif kind == "partial": reading["evidence"] = {"source": "uia_value", "read_id": "old-partial"}
    else:
        reading["source"] = "roi_ocr"
        reading["evidence"] = {"engine": "rapidocr_onnxruntime", "score": .999}
    provider.judge(payload)
    intro = bodies[0]["input"][0]["content"][0]["text"]
    assert intro == "Evaluate only visible evidence. Frame roles are temporal labels, not proof of success."


def test_native_value_facts_do_not_raise_a_refused_model_probability(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("NATIVE_VALUE_TEST_KEY", "offline-only")
    def handle(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": q["name"], "probability": .41 if q["name"] == "condition_met" else 0.0}
            for q in body["questions"]], "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="NATIVE_VALUE_TEST_KEY", client=client)
        result = provider.judge(value_payload())
    assert result["predicates"]["condition_met"] == {"type": "predicate", "probability": .41}
