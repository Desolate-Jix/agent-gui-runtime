"""历史点击仅上传同帧标注整图；原图在本地保留并参与认证。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from app.judgment.evidence import prepare_request
from app.judgment import executed_click_annotation as annotation
from test_decision_choice import runtime
from test_visual_field_proof import FIELD, receipt, module


def arguments(root, *, phase="focus"):
    focus = receipt(root, "focus")
    point = deepcopy(FIELD["click_point"])
    focus["response"]["data"]["click_result"].update(window_point=point, screen_point=point,
        down={"cursor": point}, up={"cursor": point}, window_handle=10, button="left", click_count=1)
    typed = receipt(root, "typed", "type_text") if phase == "value" else None
    from time import perf_counter_ns
    args = module()._request(phase=phase, focus_receipt=focus, input_receipt=typed,
        frame=(typed or focus)["observation"]["capture"], expected_field=deepcopy(FIELD),
        context={"execution_request_id": "annotated-field", "deadline_ns": perf_counter_ns()+30_000_000_000,
            "native_field_evidence": False, "review_context": {"goal": "Search supplied text",
                "step_goal": "Fill search field", "remaining_plan": [], "allowed_states": []}}, value_reading=None)
    # 兼容夹具显式保留旧的无 ROI 请求；新合同在用例中开启。
    args["action"].pop("field_image_scope", None)
    return args


@pytest.mark.parametrize("phase", ["focus", "value"])
def test_completed_click_producer_uploads_only_marked_full_image(tmp_path, monkeypatch, phase):
    args = arguments(tmp_path, phase=phase)
    original = Path(args["frames"][0]["image_path"]).read_bytes()
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed" and result["adopted"]
        assert len(calls) == 1 and not result["authorizes_action"]
        body = json.loads(calls[0].content)
        images = [p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image"]
        assert len(images) == 1
        assert base64.b64decode(images[0].split(",", 1)[1]) != original
        with Image.open(BytesIO(base64.b64decode(images[-1].split(",", 1)[1]))) as marked:
            assert marked.size == (180, 90)
            assert marked.convert("RGB").getpixel((40, 30)) == (255, 255, 255)
        assert Path(args["frames"][0]["image_path"]).read_bytes() == original
        assert sha256(original).hexdigest() == args["frames"][0]["sha256"]
        with Image.open(BytesIO(original)) as source:
            assert source.size == (180, 90)
        assert len(body["questions"]) == 1 and body["questions"][0]["type"] == "choice"
        text = " ".join(p["text"] for p in body["input"][0]["content"] if p["type"] == "input_text")
        assert "Historical executed-click" in text
        if phase == "focus":
            assert "Assess the marked target" in text
            assert "proof of present focus" not in text
            # 问题明确排除焦点核验，选项只比较历史点击与输入框的位置。
            question = body["questions"][0]
            assert "Keyboard focus and the field's value are outside this check." in question["instructions"]
            assert "focus" not in json.dumps(question["choices"]).lower()
            assert "inside the intended input" in question["choices"][0]["description"]
        else:
            assert "same original" in text and "not UI text or evidence" in text
            assert "focus" not in json.dumps(body["questions"]).lower()
        assert result["executed_click_annotations"][0]["executed_click"] == args["action"]["executed_click"]
        assert service.validate_result(result, **args)
        changed = deepcopy(result)
        changed["executed_click_annotations"][0]["executed_click"]["click_point"]["x"] += 1
        assert not service.validate_result(changed, **args)
        assert service.evaluate(**args) == result and len(calls) == 1
    finally:
        service.close()
        client.close()


def test_old_request_and_new_request_ask_exactly_the_same_choice(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    args["condition"] = module().VISUAL_FOCUS_CONDITION
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    old = deepcopy(args)
    old["request_id"] += "-old"
    old["action"].pop("executed_click")
    try:
        old_result = service.evaluate(**old)
        new_result = service.evaluate(**args)
        assert old_result["status"] == new_result["status"] == "completed"
        assert old_result["choice_result"] == new_result["choice_result"]
        before, after = [json.loads(c.content) for c in calls]
        assert before["questions"] == after["questions"]
        def image_parts(body):
            return [p for p in body["input"][0]["content"] if p["type"] == "input_image"]
        assert len(image_parts(before)) == 2 and len(image_parts(after)) == 1
        source = Path(args["frames"][0]["image_path"]).read_bytes()
        assert base64.b64decode(image_parts(before)[0]["image_url"].split(",", 1)[1]) == source
        assert base64.b64decode(image_parts(after)[0]["image_url"].split(",", 1)[1]) != source
        assert service.validate_result(old_result, **old) and service.validate_result(new_result, **args)
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("roi_scope", [False, True])
def test_two_historical_frames_upload_exactly_two_marks_without_building_field_detail(tmp_path, monkeypatch, roi_scope):
    from app.judgment import openai_decisions
    args = arguments(tmp_path)
    args["condition"] = module().VISUAL_FOCUS_CONDITION
    if roi_scope:
        args["action"]["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    before = {**deepcopy(args["frames"][0]), "role": "before"}
    after_path = tmp_path / "captures" / "new-focus-observation.png"
    Image.new("RGB", (180, 90), "lightgray").save(after_path)
    after = {**deepcopy(before), "role": "after", "capture_id": "new-focus-observation",
        "image_path": str(after_path), "sha256": sha256(after_path.read_bytes()).hexdigest()}
    args["frames"] = [before, after]
    originals = [Path(frame["image_path"]).read_bytes() for frame in args["frames"]]
    def forbidden(*a, **kw):
        pytest.fail("marked field frames must not generate detail crops")
    monkeypatch.setattr(openai_decisions, "build_field_detail", forbidden)
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed" and result["adopted"]
        assert len(calls) == 1
        body = json.loads(calls[0].content)
        images = [p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image"]
        assert len(images) == len(args["frames"]) == 2
        for frame, original, image_url in zip(args["frames"], originals, images):
            marked_bytes = base64.b64decode(image_url.split(",", 1)[1])
            assert marked_bytes != original
            with Image.open(BytesIO(marked_bytes)) as marked, Image.open(BytesIO(original)) as source:
                assert source.size == (180, 90)
                assert marked.size == ((166, 66) if roi_scope else (180, 90))
                assert marked.convert("RGBA").getpixel((40, 30)) == source.convert("RGBA").getpixel((40, 30))
            assert Path(frame["image_path"]).read_bytes() == original
            assert sha256(original).hexdigest() == frame["sha256"]
        assert service.validate_result(result, **args)
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("roi_scope", [False, True])
def test_authentication_does_not_render_or_encode(tmp_path, monkeypatch, roi_scope):
    args = arguments(tmp_path)
    if roi_scope:
        args["action"]["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    original, _ = prepare_request(tmp_path, **args)
    def forbidden(*a, **kw):
        pytest.fail("authentication must not render or encode")
    monkeypatch.setattr(annotation, "render_executed_click_annotation", forbidden)
    monkeypatch.setattr(base64, "b64encode", forbidden)
    checked, uploaded = prepare_request(tmp_path, **args, include_upload=False)
    assert checked == original and uploaded == []


@pytest.mark.parametrize("fault", ["identity", "size", "hash", "point", "phase"])
def test_wrong_bindings_rejected_before_provider(tmp_path, monkeypatch, fault):
    args = arguments(tmp_path)
    if fault == "identity":
        args["frames"][0]["window_identity"]["handle"] += 1
    elif fault == "size":
        args["action"]["field"]["window_rect"][2] += 1
    elif fault == "hash":
        args["action"]["focus_receipt_sha256"] = "0" * 64
    elif fault == "point":
        args["action"]["field"]["click_point"]["x"] += 1
    else:
        args["phase"] = "before_action"
        args["frames"][0]["role"] = "before"
    service, calls, client = runtime(tmp_path, monkeypatch)
    try:
        assert service.evaluate(**args)["status"] == "rejected"
        assert calls == []
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("phase", ["focus", "value"])
def test_explicit_field_roi_uploads_one_marked_view_and_keeps_original_binding(tmp_path, monkeypatch, phase):
    args = arguments(tmp_path, phase=phase)
    args["action"]["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    original = Path(args["frames"][0]["image_path"]).read_bytes()
    action = deepcopy(args["action"])
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed" and result["adopted"]
        body = json.loads(calls[0].content)
        images = [p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image"]
        assert len(images) == 1
        # 完整字段框 (10,10,140,40) 加边缘，左上只按原图边界夹取。
        with Image.open(BytesIO(base64.b64decode(images[0].split(",", 1)[1]))) as cropped:
            scale = 2 if phase == "value" else 1
            offset = 8 if phase == "value" else 0
            assert cropped.size == (166 * scale + offset * 2, 66 * scale + offset * 2)
            assert cropped.convert("RGB").getpixel((40 * scale + offset, 30 * scale + offset)) == (255, 255, 255)
        annotation = result["executed_click_annotations"][0]
        assert annotation["schema"] == "decision_executed_click_annotation.v2"
        assert annotation["field_roi"]["crop_bbox"] == {"x": 0, "y": 0, "w": 166, "h": 66}
        assert annotation["field_roi"]["crop_click_point"] == {"x": 40, "y": 30}
        assert annotation["executed_click"]["click_point"] == {"x": 40, "y": 30}
        assert ("unscaled target-field crop" in json.dumps(body)) == (phase == "focus")
        assert Path(args["frames"][0]["image_path"]).read_bytes() == original
        assert result["action"] == action and service.validate_result(result, **args)
        changed = deepcopy(result)
        changed["executed_click_annotations"][0]["field_roi"]["crop_bbox"]["x"] += 1
        assert not service.validate_result(changed, **args)
        assert service.evaluate(**args) == result and len(calls) == 1
    finally:
        service.close()
        client.close()
