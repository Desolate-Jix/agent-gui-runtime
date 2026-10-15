"""默认替换完全绕过 OCR 分流，历史策略只读且不能重写新请求。"""
from copy import deepcopy
import json

import pytest

from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
from tests.test_visual_empty_input import content_service, visual_sequence, scene
from tests.test_visual_field_proof import TEXT


def _assert_value_then_submit_gate(requests):
    assert len(requests) == 2
    value, submit = [json.loads(request.content) for request in requests]
    assert all([question["name"] for question in body["questions"]] == ["current_step"]
        for body in (value, submit))
    assert f"Does the entered field text exactly equal {json.dumps(TEXT, ensure_ascii=False)}?" in value["questions"][0]["instructions"]
    assert "Match the marked text input itself." in submit["questions"][0]["instructions"]
    assert [sum(part["type"] == "input_image" for part in body["input"][0]["content"])
        for body in (value, submit)] == [1, 1]
    return value, submit


@pytest.mark.parametrize("state", ["empty", "nonempty", "uncertain"])
def test_runtime_never_loads_ocr_or_classifies_field_content(visual_sequence, monkeypatch, state):
    from app.core.ocr_service import ocr_service
    from app.execution import field_content_ocr
    v = visual_sequence
    scans = []
    def forbidden(*args, **kwargs):
        scans.append((args, kwargs))
        pytest.fail("默认替换不得启动 OCR 或字段内容分类")
    service, client = content_service(v, state)
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", forbidden)
    monkeypatch.setattr(field_content_ocr, "read_field_content", forbidden)
    try:
        result = v.run()
        assert result["status"] == "completed", result.get("error")
        assert scans == []
        assert all([q["name"] for q in json.loads(request.content)["questions"]] == ["current_step"]
            for request in v.scene.requests)
        assert "typing_strategy" not in result and "field_content_ocr" not in result
        assert v.events.count((VK_CONTROL, VK_A)) == 1
        assert v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_RETURN,)) == 1
        _assert_value_then_submit_gate(v.scene.requests)
        assert [call["operation"] for call in v.calls] == ["execute_recognition_plan"] * 2
        assert v.events.count("gate-click") == 2
        assert v.forbidden_calls == []
    finally:
        service.close()
        client.close()


def test_default_replacement_ignores_stale_content_context_without_mutating_caller(visual_sequence):
    from app.core.visual_typing_strategy import validated_effective_typing_request
    from tests.test_visual_empty_partial import sequence_command
    v = visual_sequence
    v.scene.context.update(field_content_check={"schema": "obsolete-content"},
        field_content_ocr={"schema": "obsolete-ocr"})
    original = deepcopy({key: v.scene.context[key] for key in ("field_content_check", "field_content_ocr")})
    service, client = content_service(v, "uncertain")
    try:
        result = v.run()
        assert result["status"] == "completed", result.get("error")
        command = sequence_command()
        before = deepcopy(command)
        assert validated_effective_typing_request(result, command["request"]) == command["request"]
        assert command == before
        assert {key: v.scene.context[key] for key in original} == original
        assert "visual_click_evidence" not in result
        assert result["completed_steps"] == ["focus_type", "check_input", "search"]
        value, submit = _assert_value_then_submit_gate(v.scene.requests)
        for body in (value, submit):
            action = body["input"][0]["content"]
            assert "field_content_check" not in json.dumps(action)
            assert "field_content_ocr" not in json.dumps(action)
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        assert v.events.count("gate-click") == 2
    finally:
        service.close()
        client.close()


def test_append_preclick_rejection_never_loads_unavailable_ocr(visual_sequence, monkeypatch):
    from app.core.ocr_service import ocr_service
    v = visual_sequence
    service, client = content_service(v, "uncertain")
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", lambda: pytest.fail("拒绝追加不得加载 OCR"))
    try:
        with pytest.raises(ValueError, match="visual_field_append_requires_explicit_native_route"):
            v.run(clear_existing=False)
        assert v.calls == v.events == v.scene.requests == []
    finally:
        service.close()
        client.close()
