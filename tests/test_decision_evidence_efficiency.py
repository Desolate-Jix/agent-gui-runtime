"""上传内容精简不能改变本地证据认证、当前条件或请求次数。"""
import base64
from copy import deepcopy
from io import BytesIO

from PIL import Image
import json
import pytest

from test_decision_choice import runtime, choice_reply
from test_decision_service import arguments as result_arguments
from test_executed_click_integration import arguments as field_arguments
from test_adaptive_decision_policy import context


@pytest.mark.parametrize("choice,adopted", [("condition_met", True),
    ("condition_not_met", False), ("evidence_insufficient", False)])
def test_cropped_field_choice_preserves_ambiguous_completion_handoff_without_another_request(tmp_path, monkeypatch, choice, adopted):
    args = field_arguments(tmp_path, phase="value")
    args["action"]["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    service, calls, client = runtime(tmp_path, monkeypatch, body=choice_reply(choice),
        profile={"auto_conditions": [args["condition"]]})
    try:
        result = service.evaluate(**args)
        question = json.loads(calls[0].content)["questions"][0]
        assert "gray completion immediately following the typed text" in question["instructions"]
        assert "separate shortcut hints" in question["instructions"]
        assert "choose evidence_insufficient" in question["instructions"]
        assert result["choice_result"]["choice"] == choice and result["adopted"] is adopted
        assert result["disposition"] == ("continue" if adopted else "review_required")
        assert not result["authorizes_action"] and not result["automatic_retry_allowed"]
        assert service.validate_result(result, **args)
        assert service.evaluate(**args) == result and len(calls) == 1
    finally:
        service.close()
        client.close()


def test_field_roi_upload_keeps_only_comparison_text_but_authenticates_complete_original(tmp_path, monkeypatch):
    args = field_arguments(tmp_path, phase="value")
    args["action"]["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    original = deepcopy(args)
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed"
        assert len(calls) == 1
        body = json.loads(calls[0].content)
        text = " ".join(p["text"] for p in body["input"][0]["content"] if p["type"] == "input_text")
        assert args["frames"][0]["sha256"] not in text
        assert args["action"]["executed_click"]["receipt_sha256"] not in text
        assert "process_create_time" not in text
        assert "crop_bbox" not in text and "crop_click_point" not in text
        assert "field_goal" not in text and args["action"]["field"]["field_goal"] not in text
        assert len([p for p in body["input"][0]["content"] if p["type"] == "input_text"]) == 0
        assert "Ignore icons, the click marker, dropdown choices and separate shortcut hints" in body["questions"][0]["instructions"]
        assert len(body["questions"]) == 1
        url = next(p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image")
        roi = result["executed_click_annotations"][0]["field_roi"]["upload_size"]
        with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            assert image.size == (roi["width"] * 2 + 16, roi["height"] * 2 + 16)
        assert json.dumps(args["action"]["expected_text"], ensure_ascii=False) in body["questions"][0]["instructions"]
        assert len([p for p in body["input"][0]["content"] if p["type"] == "input_image"]) == 1
        assert args == original and service.validate_result(result, **args)
        altered = deepcopy(args)
        altered["action"]["executed_click"]["receipt_sha256"] = "0" * 64
        assert not service.validate_result(result, **altered)
        altered = deepcopy(args)
        altered["action"]["expected_text"] += "x"
        altered["action"]["field"]["expected_text"] += "x"
        assert not service.validate_result(result, **altered)
        assert len(calls) == 1
    finally:
        service.close()
        client.close()


def test_ordinary_result_choice_does_not_recheck_action_feasibility(tmp_path, monkeypatch):
    condition = "The document displays exactly 'Saved draft' and the File menu is closed."
    args = result_arguments(tmp_path, condition=condition, review_context=context())
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [condition]})
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed" and len(calls) == 1
        body = json.loads(calls[0].content)
        question = body["questions"][0]
        prompt = question["instructions"]
        assert condition in prompt and len(body["questions"]) == 1
        assert "feasibility" not in json.dumps(question).lower()
        assert "cropped" in prompt and "uncaptured" in prompt
        assert "evidence_insufficient" in prompt and "condition_not_met" in prompt
        assert "earlier" in prompt and "future" in prompt
        assert "screen text" in prompt and "temporal" in prompt
        assert service.validate_result(result, **args)
    finally:
        service.close()
        client.close()
