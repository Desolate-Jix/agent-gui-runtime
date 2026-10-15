"""默认替换只确认真实点击和输入结果，不识别空框。"""
import json
import pytest
from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
from tests.test_visual_empty_input import content_service, visual_sequence, scene
from tests.test_visual_field_proof import TEXT

@pytest.mark.parametrize("ocr_state", ["empty", "nonempty", "uncertain"])
def test_default_replacement_never_reads_empty_state(visual_sequence, monkeypatch, ocr_state):
    from app.core.ocr_service import ocr_service
    v = visual_sequence
    service, client = content_service(v, ocr_state)
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", lambda: pytest.fail("默认替换不得启动OCR"))
    monkeypatch.setattr(v.scene.module, "capture_visual_focus_observation",
        lambda *args, **kwargs: pytest.fail("默认替换不得补采焦点图"))
    monkeypatch.setattr(v.scene.module, "sleep",
        lambda *args, **kwargs: pytest.fail("默认替换不得额外等待焦点"))
    try:
        result = v.run()
        assert result["status"] == "completed", result.get("error")
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        assert v.events.count((VK_RETURN,)) == 1
        assert v.events.count("gate-click") == 2
        assert [call["operation"] for call in v.calls] == ["execute_recognition_plan"] * 2
        assert len(v.scene.requests) == 2
        assert [row["stage"] for row in result["field_evaluations"]] == ["after_type"]
        assert "field_content_ocr" not in result and "typing_strategy" not in result
        assert result["steps"][0]["name"] == "focus_type"
        assert "visual_click_evidence" not in result
        value, submit = [json.loads(request.content) for request in v.scene.requests]
        assert all([q["name"] for q in body["questions"]] == ["current_step"]
            for body in (value, submit))
        prompt = value["questions"][0]["instructions"]
        assert f"Does the entered field text exactly equal {json.dumps(TEXT, ensure_ascii=False)}?" in prompt
        assert "If gray unaccepted completion is attached" in prompt
        assert "Ignore separate icons and shortcut hints" in prompt
        for removed in ("empty", "focus", "caret", "usable", "read-only", "can text be entered"):
            assert removed not in prompt.lower()
        submit_prompt = submit["questions"][0]["instructions"]
        assert "Match the marked text input itself." in submit_prompt
        assert "focus" not in submit_prompt.lower() and "caret" not in submit_prompt.lower()
        submit_text = " ".join(part["text"] for part in submit["input"][0]["content"]
            if part["type"] == "input_text")
        assert '"permitted_action_kind": "input_sequence"' in submit_text
        assert '"marked_centers_in_composite"' in submit_text
        assert [sum(part["type"] == "input_image" for part in body["input"][0]["content"])
            for body in (value, submit)] == [1, 1]
        assert v.forbidden_calls == []
    finally:
        service.close()
        client.close()

@pytest.mark.parametrize("choice", ["condition_not_met", "evidence_insufficient"])
def test_wrong_value_still_stops_before_enter(visual_sequence, choice):
    v = visual_sequence
    service, client = content_service(v, "empty", value_choice=choice)
    try:
        result = v.run()
        assert result["status"] == "interrupted" and result["completed_steps"] == ["focus_type"]
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        assert (VK_RETURN,) not in v.events
        assert result["main_handoff"]["stage"] == "after_type"
    finally:
        service.close()
        client.close()


def test_no_clear_does_not_silently_replace_or_guess_append(visual_sequence):
    v = visual_sequence
    with pytest.raises(ValueError, match="visual_field_append_requires_explicit_native_route"):
        v.run(clear_existing=False)
    assert v.calls == [] and v.events == []
