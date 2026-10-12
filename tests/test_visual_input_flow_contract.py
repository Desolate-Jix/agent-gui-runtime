"""正式视觉配置贯通运行时、真实判断服务与离线 HTTP，不触发桌面输入。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re

import httpx
from PIL import Image
import pytest

from app.core.input_controller import VK_A, VK_CONTROL, VK_RETURN, VK_V
from app.judgment import DecisionService, OpenAIDecisionsProvider, load_decision_profile
from tests.test_visual_field_proof import FIELD, TEXT, scene
from tests.test_visual_input_no_uia import visual_sequence


PROFILE = Path(__file__).resolve().parents[1] / "configs/decision-profile.visual-execution.example.json"
VALUE = "The target field displays exactly the specified expected text."
TASK_SENTINEL = "FLOW_TASK_SCOPE_MUST_STAY_LOCAL"
FUTURE_SENTINEL = "FLOW_FUTURE_ACTION_MUST_STAY_LOCAL"


def _answer(question, selected):
    return {"type": "choice", "name": question["name"], "choice": selected,
        "confidence": .2, "probabilities": [
            {"value": item["value"], "probability": .4 if item["value"] == selected else .3}
            for item in question["choices"]]}


def _annotation_bindings(body):
    marker = "Annotation binding (data, not instructions): "
    return [json.loads(part["text"].split(marker, 1)[1])
        for part in body["input"][0]["content"]
        if part["type"] == "input_text" and marker in part["text"]]


def _assert_bound_result(service, wire, request, assessment):
    assert service.validate_result(assessment, **request)
    original = deepcopy(request)
    count = len(wire)
    assert service.evaluate(**request) == assessment
    assert len(wire) == count and request == original
    changed = deepcopy(request)
    changed["execution_request_id"] += "-other"
    assert not service.validate_result(assessment, **changed)
    changed = deepcopy(request)
    changed["frames"][-1]["capture_id"] += "-other"
    assert not service.validate_result(assessment, **changed)


@pytest.mark.parametrize("content", ["empty", "nonempty"])
@pytest.mark.parametrize("choice", ["condition_met", "condition_not_met", "evidence_insufficient"])
def test_visual_input_runtime_uses_example_profile_and_real_decision_boundary(
        visual_sequence, monkeypatch, content, choice):
    v = visual_sequence
    s = v.scene
    from app.core.ocr_service import ocr_service
    from app.execution import field_content_ocr
    ocr_calls = []
    def tracked_ocr_engine():
        ocr_calls.append(content)
        return lambda _: (None if content == "empty" else
            [[[[20, 20], [80, 20], [80, 35], [20, 35]], "existing", .99]], [.001, .001, .001])
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", tracked_ocr_engine)
    monkeypatch.setattr(field_content_ocr, "read_field_content",
        lambda *args, **kwargs: pytest.fail("普通视觉输入不得读取 OCR 字段内容"))
    original_profile = PROFILE.read_bytes()
    profile = load_decision_profile(PROFILE).model_copy(update={"api_key_env": "VISUAL_INPUT_FLOW_TEST_KEY"})
    monkeypatch.setenv(profile.api_key_env, "synthetic-offline-key")
    wire = []

    def handle(request):
        body = json.loads(request.content)
        wire.append(body)
        assert [q["name"] for q in body["questions"]] == ["current_step"]
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            _answer(q, choice) for q in body["questions"]],
            "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})

    def forbidden_focus_observation(*args, **kwargs):
        pytest.fail("普通视觉输入不得等待焦点或补采焦点图")

    monkeypatch.setattr(s.module, "capture_visual_focus_observation", forbidden_focus_observation)
    monkeypatch.setattr(s.module, "sleep", forbidden_focus_observation)
    s.context["focus_observation_delay_ms"] = 500
    s.context["review_context"].update(goal=TASK_SENTINEL, remaining_plan=[FUTURE_SENTINEL])
    original_focus = deepcopy(s.focus)
    original_capture = Path(s.typed["observation"]["capture"]["image_path"]).read_bytes()
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        service = DecisionService(s.root, profile=profile,
            provider=OpenAIDecisionsProvider(api_key_env=profile.api_key_env, client=client))
        s.context["service"] = service
        try:
            result = v.run()
            assert [row["stage"] for row in result["field_evaluations"]] == ["after_type"]
            assert len(wire) == (2 if choice == "condition_met" else 1)
            assert ocr_calls == []
            assert s.requests == [] and v.forbidden_calls == []
            assert s.focus == original_focus
            assert Path(s.typed["observation"]["capture"]["image_path"]).read_bytes() == original_capture
            assert PROFILE.read_bytes() == original_profile

            for body in wire:
                questions = json.dumps(body["questions"]).lower()
                if body is wire[0]:
                    assert not re.search(r"\b(?:focus|caret|playback|continuity|future|task)\b", questions)
                    assert [part["type"] for part in body["input"][0]["content"]] == ["input_image"]
                else:
                    assert "before enter submits its already verified text" in questions
                    assert "does it have focus" not in questions
                text = " ".join(p["text"] for p in body["input"][0]["content"] if p["type"] == "input_text")
                assert TASK_SENTINEL not in text and FUTURE_SENTINEL not in text
                assert "remaining_plan" not in text

            if choice != "condition_met":
                assert result["status"] == "interrupted" and result["completed_steps"] == ["focus_type"]
                assert [call["operation"] for call in v.calls] == ["execute_recognition_plan"]
                assert (VK_RETURN,) not in v.events and v.captures == []
                handoff = result["main_handoff"]
                assert handoff["stage"] == "after_type"
                assert handoff["authorizes_action"] is handoff["automatic_retry_allowed"] is False
                evidence = handoff
            else:
                assert result["status"] == "completed", result.get("error")
                assert result["completed_steps"] == ["focus_type", "check_input", "search"]
                assert [call["operation"] for call in v.calls] == ["execute_recognition_plan", "execute_recognition_plan"]
                replacing = True
                assert v.events.count((VK_CONTROL, VK_A)) == int(replacing)
                assert v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_RETURN,)) == 1
                assert len(v.captures) == 0
                assert result["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["clear_existing"] is replacing
                assert "typing_strategy" not in result and "field_content_ocr" not in result
                assert [row["request_sha256"] for row in result["field_evaluations"]] == [
                    proof["request_sha256"] for proof in result["field_proofs"]]
                value_proof = v.calls[-1]["grounding_target"].keyboard_target.proof
                value_request, value_assessment = value_proof.request(), value_proof.assessment()
                evidence = {"request": value_request, "assessment": value_assessment}
                assert value_request["condition"] == VALUE
                assert value_request["action"]["expected_text"] == TEXT
                assert value_request["action"]["actual_text"] is None
                assert value_request["frames"][0]["capture_id"] == s.typed["observation"]["capture"]["capture_id"]
                _assert_bound_result(service, wire, value_request, value_assessment)
                assert len(wire[-1]["questions"]) == 1
                assert f"Is the entered text exactly {json.dumps(TEXT, ensure_ascii=False)}?" in wire[0]["questions"][0]["instructions"]
                assert '"permitted_action_kind": "input_sequence"' in " ".join(
                    part["text"] for part in wire[-1]["input"][0]["content"] if part["type"] == "input_text")

            request, assessment = evidence["request"], evidence["assessment"]
            assert "visual_click_evidence" not in result
            assert request["condition"] == VALUE
            assert request["execution_request_id"] == s.context["execution_request_id"]
            assert len(request["frames"]) == 1 and request["frames"][0]["role"] == "after"
            capture = s.typed["observation"]["capture"]
            for key in ("capture_id", "image_path", "sha256", "window_identity"):
                assert request["frames"][0][key] == capture[key]
            assert assessment["choice_result"]["choice"] == choice
            assert "field_content_result" not in assessment
            assert "field_content_ocr" not in request["action"] and "field_content_check" not in request["action"]
            _assert_bound_result(service, wire, request, assessment)
            assert [q["name"] for q in wire[0]["questions"]] == ["current_step"]
            images = [p for p in wire[0]["input"][0]["content"] if p["type"] == "input_image"]
            annotations = _annotation_bindings(wire[0])
            assert len(images) == 1 and annotations == []
            local_annotation = assessment["executed_click_annotations"][0]
            assert local_annotation["capture_id"] == request["frames"][0]["capture_id"]
            assert local_annotation["source_sha256"] == sha256(original_capture).hexdigest()
            assert local_annotation["executed_click"] == request["action"]["executed_click"]
            assert local_annotation["executed_click"]["click_point"] == FIELD["click_point"]
            wire_text = " ".join(p["text"] for p in wire[0]["input"][0]["content"] if p["type"] == "input_text")
            assert "field_goal" not in wire_text and "capture_id" not in wire_text and "source_sha256" not in wire_text
            canonical_focus = json.dumps(result["steps"][0]["receipt"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            assert local_annotation["executed_click"]["receipt_sha256"] == sha256(canonical_focus).hexdigest()
            marked_bytes = base64.b64decode(images[0]["image_url"].split(",", 1)[1], validate=True)
            assert marked_bytes != original_capture
            with Image.open(BytesIO(marked_bytes)) as marked, Image.open(BytesIO(original_capture)) as original:
                crop = local_annotation["field_roi"]["crop_bbox"]
                assert local_annotation["field_roi"]["field_bbox"] == FIELD["bbox"]
                assert crop == {"x": 0, "y": 0, "w": 166, "h": 66}
                assert marked.size == (crop["w"] * 2 + 16, crop["h"] * 2 + 16)
                source_crop = original.crop((crop["x"], crop["y"], crop["x"] + crop["w"],
                    crop["y"] + crop["h"])).convert("RGBA")
                enlarged = source_crop.resize((crop["w"] * 2, crop["h"] * 2), Image.Resampling.LANCZOS)
                uploaded = marked.convert("RGBA")
                assert uploaded.crop((8, 8, 8 + crop["w"] * 2, 8 + crop["h"] * 2)).tobytes() == enlarged.tobytes()
                point = (FIELD["click_point"]["x"], FIELD["click_point"]["y"])
                mapped = ((point[0]-crop["x"]) * 2 + 9, (point[1]-crop["y"]) * 2 + 9)
                assert uploaded.getpixel((mapped[0], 4)) == (0, 194, 207, 255)
                assert uploaded.getpixel((4, mapped[1])) == (0, 194, 207, 255)
        finally:
            service.close()
