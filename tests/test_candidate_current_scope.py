"""标注候选只上传本次点击证据；完整未来计划仍保留本地认证。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest

from app.execution.action_review import CANDIDATE_CONDITION
from test_decision_candidate_annotation_integration import request_args
from test_decision_choice import choice_reply, runtime


INPUT_FEASIBILITY = "This click starts text input in the marked field. "


def candidate_args(root, future):
    args = request_args(root)
    args["request_id"] += "-" + future
    args["action"].update(click_kind="single", native_popup_fact={"owned_popup": False}, permitted_action={
        "kind": "input_sequence", "field_goal": "Browser address bar", "text": "FUTURE_TEXT_" + future,
        "clear_existing": True, "submit_search": True})
    args["review_context"].update(goal="GLOBAL_HISTORY_" + future,
        step_goal="WHOLE_INPUT_STEP_" + future, remaining_plan=["FUTURE_PLAN_" + future],
        allowed_states=["A nonblocking cookie panel may remain visible."])
    return args


def test_choice_candidate_http_omits_future_plan_and_text_without_weakening_local_binding(tmp_path, monkeypatch):
    first = candidate_args(tmp_path, "FIRST")
    second = candidate_args(tmp_path, "SECOND")
    original = deepcopy(first)
    image_path = Path(first["frames"][0]["image_path"])
    image_bytes = image_path.read_bytes()
    service, calls, client = runtime(tmp_path, monkeypatch,
        profile={"auto_conditions": [CANDIDATE_CONDITION], "request_cap": 2})
    try:
        results = [service.evaluate(**args) for args in (first, second)]
        assert all(result["adopted"] for result in results)
        bodies = [json.loads(call.content) for call in calls]
        assert len(bodies) == 2
        for body in bodies:
            assert body["questions"][0]["instructions"].count(INPUT_FEASIBILITY) == 1
            wire = json.dumps(body)
            for forbidden in ("FUTURE_TEXT_", "GLOBAL_HISTORY_", "WHOLE_INPUT_STEP_", "FUTURE_PLAN_",
                    "remaining_plan", "submit_search", "clear_existing", "capture_id", "candidate_id",
                    "source_sha256", "target_window_identity", first["frames"][0]["sha256"]):
                assert forbidden not in wire
            content = body["input"][0]["content"]
            texts = [part["text"] for part in content if part["type"] == "input_text"]
            action = json.loads(next(text.split(": ", 1)[1] for text in texts
                if text.startswith("Current target and action")))
            assert action["target"] == "Browser address bar"
            assert action["click_kind"] == "single"
            assert action["permitted_action_kind"] == "input_sequence"
            assert set(action) == {"target", "click_kind", "permitted_action_kind", "marked_centers_in_composite"}
            popup = json.loads(next(text.split(": ", 1)[1] for text in texts
                if text.startswith("Current popup evidence")))
            assert popup == {"owned_popup": False}
            assert first["review_context"]["allowed_states"][0] in wire
            images = [part for part in content if part["type"] == "input_image"]
            assert len(images) == 1
            marked = base64.b64decode(images[0]["image_url"].split(",", 1)[1])
            assert marked != image_bytes
            with Image.open(BytesIO(marked)) as image:
                assert image.size != (160, 90)
                centers = action["marked_centers_in_composite"]
                assert set(centers) == {"overview", "detail"}
                for x, y in centers.values():
                    assert 0 <= x < image.width and 0 <= y < image.height
                    assert image.convert("RGB").getpixel((x, y)) == (255, 255, 255)
        assert bodies[0] == bodies[1]
        assert results[0]["request_sha256"] != results[1]["request_sha256"]
        assert first == original
        assert image_path.read_bytes() == image_bytes
        assert sha256(image_bytes).hexdigest() == first["frames"][0]["sha256"]
        for args, result in zip((first, second), results):
            assert result["action"] == args["action"]
            assert result["review_context"] == args["review_context"]
            assert service.validate_result(result, **args)
        changed = deepcopy(first)
        changed["action"]["permitted_action"]["text"] += "X"
        assert not service.validate_result(results[0], **changed)
        changed = deepcopy(first)
        changed["review_context"]["remaining_plan"] = ["Changed future plan"]
        assert not service.validate_result(results[0], **changed)
        changed = deepcopy(first)
        changed["action"]["permitted_action"]["kind"] = "click"
        assert not service.validate_result(results[0], **changed)
        assert len(calls) == 2
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("route", ["predicate", "custom_condition", "freshness", "unmarked"])
def test_other_before_action_contracts_keep_full_context(tmp_path, monkeypatch, route):
    args = candidate_args(tmp_path, "COMPAT")
    profile = {"auto_conditions": [CANDIDATE_CONDITION]}
    body = choice_reply()
    if route == "predicate":
        profile["decision_format"] = "predicate"
        body = {"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": "condition_met", "probability": .99},
            {"type": "predicate", "name": "unsafe_effect", "probability": .01},
            {"type": "predicate", "name": "needs_agent_review", "probability": .01}],
            "usage": {"input_tokens": 2, "output_tokens": 0, "total_tokens": 2}}
    elif route == "custom_condition":
        args["condition"] = "The original custom pre-action condition remains binding."
        profile["auto_conditions"] = [args["condition"]]
    elif route == "freshness":
        latest = tmp_path / "latest.png"
        Image.new("RGB", (160, 90), "gray").save(latest)
        args["frames"].append({**args["frames"][0], "capture_id": "latest", "role": "observation",
            "image_path": str(latest), "sha256": sha256(latest.read_bytes()).hexdigest()})
        args["action"]["candidate"]["capture_id"] = "latest"
        args["action"]["freshness_context"] = {"schema": "action_freshness.v1",
            "changed_region": {"x": 120, "y": 60, "w": 10, "h": 10}}
    service, calls, client = runtime(tmp_path, monkeypatch, profile=profile, body=body)
    if route == "unmarked":
        prepare = service._prepare
        def legacy_prepare(kwargs, **options):
            binding, uploaded, digest = prepare(kwargs, **options)
            for frame in uploaded:
                frame.pop("candidate_annotation", None)
            return binding, uploaded, digest
        monkeypatch.setattr(service, "_prepare", legacy_prepare)
    try:
        assert service.evaluate(**args)["status"] == "completed"
        exported = json.loads(calls[0].content)
        assert INPUT_FEASIBILITY not in json.dumps(exported["questions"])
        content = exported["input"][0]["content"]
        texts = [part["text"] for part in content if part["type"] == "input_text"]
        assert json.loads(next(text.split(": ", 1)[1] for text in texts
            if text.startswith("Proposed action context"))) == args["action"]
        assert json.loads(next(text.split(": ", 1)[1] for text in texts
            if text.startswith("Frozen scoped task"))) == args["review_context"]
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("kind", ["click", None])
def test_ordinary_candidate_click_keeps_point_question_without_input_semantics(tmp_path, monkeypatch, kind):
    args = candidate_args(tmp_path, "ORDINARY_CLICK")
    if kind is None:
        args["action"].pop("permitted_action")
    else:
        args["action"]["permitted_action"] = {"kind": kind, "goal": "Browser address bar"}
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [CANDIDATE_CONDITION]})
    try:
        result = service.evaluate(**args)
        assert result["adopted"] is True and service.validate_result(result, **args)
        body = json.loads(calls[0].content)
        instructions = body["questions"][0]["instructions"]
        if kind is None:
            assert "Does the center of the cyan click marker fall inside the visible UI target described below?" in instructions
            assert "Browser address bar" in instructions
            assert "Current target and action" not in json.dumps(body)
        else:
            assert "Current target and action.target" in instructions
            assert "Browser address bar" not in instructions
        assert INPUT_FEASIBILITY not in instructions
        assert len([part for part in body["input"][0]["content"] if part["type"] == "input_image"]) == 1
    finally:
        service.close()
        client.close()
