"""空框也执行原请求的替换语义；不读取桌面或调用付费服务。"""
from copy import deepcopy
from hashlib import sha256
import json

import httpx
from PIL import Image, ImageDraw
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
from tests.test_visual_field_proof import scene
from tests.test_visual_input_no_uia import visual_sequence


def content_service(v, state, *, value_choice="condition_met"):
    """构造不同合成字段与 OCR 环境，保留共享测试入口。"""
    from app.core.ocr_service import ocr_service
    if state != "empty":
        frame = v.scene.focus["observation"]["capture"]
        with Image.open(frame["image_path"]) as source:
            image = source.copy()
        if state == "nonempty":
            ImageDraw.Draw(image).text((20, 20), "existing", fill="black")
        else:
            image.putpixel((30, 25), (128, 128, 128))
        image.save(frame["image_path"], format="PNG")
        from pathlib import Path
        frame["sha256"] = sha256(Path(frame["image_path"]).read_bytes()).hexdigest()

    def engine(path):
        if state == "uncertain":
            raise RuntimeError("offline_ocr_unavailable")
        return (None if state == "empty" else
            [[[[20, 20], [80, 20], [80, 35], [20, 35]], "existing", .99]]), [.001, .001, .001]
    v.monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", lambda: engine)
    def handle(request):
        v.scene.requests.append(request)
        questions = json.loads(request.content)["questions"]
        answers = []
        for question in questions:
            selected = state if question["name"] == "field_content" else (
                value_choice if (VK_CONTROL, VK_V) in v.events else "condition_met")
            options = [item["value"] for item in question["choices"]]
            answers.append({"type": "choice", "name": question["name"], "choice": selected,
                "confidence": .1, "probabilities": [{"value": option,
                    "probability": .4 if option == selected else .3} for option in options]})
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": answers,
            "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    service = DecisionService(v.scene.root, profile=DecisionProfile.model_validate({
        **v.scene.service.profile.model_dump(mode="json"), "decision_format": "choice"}),
        provider=OpenAIDecisionsProvider(api_key_env="VISUAL_FIELD_TEST_KEY", client=client))
    v.scene.context["service"] = service
    return service, client


@pytest.mark.parametrize("state", ["empty", "nonempty", "uncertain"])
def test_field_content_does_not_rewrite_requested_replacement(visual_sequence, state):
    v = visual_sequence
    service, client = content_service(v, state)
    try:
        result = v.run()
        assert result["status"] == "completed", result.get("error")
        assert v.events.count((VK_CONTROL, VK_A)) == 1
        assert v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_RETURN,)) == 1
        assert v.events.index((VK_CONTROL, VK_A)) < v.events.index((VK_CONTROL, VK_V)) < v.events.index((VK_RETURN,))
        assert len(v.scene.requests) == 2
        assert [r["stage"] for r in result["field_evaluations"]] == ["after_type"]
        assert result["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["clear_existing"] is True
        assert "typing_strategy" not in result and "typing_strategy_evidence" not in result
        assert "field_content_ocr" not in result
        assert all("field_content_ocr" not in proof for proof in result["field_proofs"])
        assert v.forbidden_calls == []
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("state", ["empty", "nonempty", "uncertain"])
def test_ordinary_append_rejects_before_click_without_classifying_content(visual_sequence, state):
    v = visual_sequence
    service, client = content_service(v, state)
    try:
        with pytest.raises(ValueError, match="^visual_field_append_requires_explicit_native_route$"):
            v.run(clear_existing=False)
        assert v.calls == v.events == v.captures == v.scene.requests == []
        assert v.forbidden_calls == []
    finally:
        service.close()
        client.close()


def test_empty_field_replacement_wrong_value_still_blocks_enter(visual_sequence):
    v = visual_sequence
    service, client = content_service(v, "empty", value_choice="condition_not_met")
    try:
        result = v.run()
        assert result["status"] == "interrupted" and result["completed_steps"] == ["focus_type"]
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        assert (VK_RETURN,) not in v.events
        assert result["main_handoff"]["stage"] == "after_type"
    finally:
        service.close()
        client.close()


def test_public_no_clear_preserves_original_request_for_preclick_rejection(visual_sequence):
    from app.execution.public_input_defaults import adopt_public_input_command
    original = {"kind": "input_sequence", "request": {"field_goal": "Search field", "text": "java",
        "clear_existing": False, "submit_search": True}}
    before = deepcopy(original)
    adopted = adopt_public_input_command("direct-empty", original)
    assert original == before
    assert adopted["request"]["clear_existing"] is False
    assert adopted["field_evidence_mode"] == "visual"
    with pytest.raises(ValueError, match="visual_field_append_requires_explicit_native_route"):
        visual_sequence.run(**adopted["request"])
    assert original == before and visual_sequence.calls == []


def test_v3_plan_preserves_append_request_instead_of_silently_replacing():
    from app.execution.task_plan_contract import validate_task_plan
    verification = {"kind": "agent_judgment", "decision_condition": "Search results are visible."}
    plan = {"schema_version": "task_plan.v3", "title": "Empty field", "goal": "Search java", "inputs": {},
        "steps": [{"step_id": "search", "action": {"kind": "input_sequence", "field_goal": "Search field",
            "text": "java", "clear_existing": False, "submit_search": True}, "verification": verification}],
        "completion": {"step_id": "search", "verification": verification}}
    assert validate_task_plan(plan)["steps"][0]["action"]["clear_existing"] is False


def test_explicit_legacy_append_command_and_existing_ticket_keep_original_semantics():
    from app.execution.public_input_defaults import adopt_public_input_command
    original = {"kind": "input_sequence", "field_evidence_mode": "legacy", "request": {
        "field_goal": "Search field", "text": "java", "clear_existing": False, "submit_search": True}}
    before = deepcopy(original)
    adopted = adopt_public_input_command("explicit-native", original)
    replayed = adopt_public_input_command("explicit-native", original, existing_command=adopted)
    assert adopted == replayed == original == before
