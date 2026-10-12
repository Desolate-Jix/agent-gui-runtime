"""通用三图变化只比较明确目标；沿用原证据、预算和认证边界。"""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService
from app.judgment.evidence import prepare_request
from tests.test_video_picture_change_decision import arguments as video_arguments
from tests.test_video_playback_decision import frame, service as video_service


CONDITION = "The clock digits visibly change during the observed interval."
TARGET = "The hours, minutes and seconds digits of the large public clock."


def arguments(root):
    args = video_arguments(root)
    args.update(request_id="dynamic-clock-one", condition=CONDITION)
    args["review_context"].update(goal=CONDITION, step_goal="Inspect the clock digits")
    args["temporal_context"].update(schema="temporal_visual_change.v1", target_description=TARGET)
    return args


def service(root, monkeypatch, *, profile=None, handler=None):
    return video_service(root, monkeypatch,
        profile={"auto_conditions": [CONDITION], "after_action_pass_threshold": 0.8,
                 "after_action_review_threshold": 0.7, **(profile or {})}, handler=handler)


def test_generic_context_uploads_all_three_bound_images_and_retains_target(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    binding, uploads = prepare_request(tmp_path, **args)
    assert binding["temporal_context"] == args["temporal_context"]
    assert binding["frames"] == args["frames"]
    assert [(item["capture_id"], item["role"]) for item in uploads] == [
        ("sample-0", "sample_start"), ("sample-1", "sample_middle"), ("sample-2", "sample_end")]
    for sample, uploaded in zip(args["temporal_context"]["samples"], uploads):
        data = base64.b64decode(uploaded["data_url"].split(",", 1)[1], validate=True)
        assert data == Path(sample["frame"]["image_path"]).read_bytes()
        assert sha256(data).hexdigest() == sample["frame"]["sha256"]
    monkeypatch.setattr("app.judgment.temporal_playback.base64.b64encode",
        lambda *args: pytest.fail("只读认证不能再次编码上传图片"))
    assert prepare_request(tmp_path, **args, include_upload=False) == (binding, [])


@pytest.mark.parametrize("description", ["x", "x" * 1000, "  Clock digits  ", "\u5927\u65f6\u949f\u7684\u79d2\u6570"])
def test_target_description_preserves_exact_valid_text(tmp_path, description):
    args = arguments(tmp_path)
    args["temporal_context"]["target_description"] = description
    binding, uploads = prepare_request(tmp_path, **args)
    assert binding["temporal_context"]["target_description"] == description and len(uploads) == 3


@pytest.mark.parametrize("description", [None, True, 1, [], {}, "", " \t\n", "x" * 1001])
def test_invalid_target_description_is_rejected_before_model_dispatch(tmp_path, monkeypatch, description):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    args["temporal_context"]["target_description"] = description
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == "rejected" and not result["adopted"] and calls == []
    finally:
        client.close()


@pytest.mark.parametrize("damage", ["missing_target", "extra", "count2", "count4", "early", "interval", "deadline",
    "selection", "duplicate", "window", "path", "hash", "original"])
def test_generic_schema_keeps_existing_three_image_evidence_guards(tmp_path, monkeypatch, damage):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    context = args["temporal_context"]
    samples = context["samples"]
    if damage == "missing_target":
        context.pop("target_description")
    elif damage == "extra":
        context["analysis"] = {"status": "playing"}
    elif damage == "count2":
        samples.pop()
        context["selected_capture_ids"].pop()
    elif damage == "count4":
        samples.append({"frame": frame(tmp_path, "sample-3"), "elapsed_ms": 2500})
        context["selected_capture_ids"].append("sample-3")
    elif damage == "early":
        samples[0]["elapsed_ms"] = 999
    elif damage == "interval":
        samples[1]["elapsed_ms"] = 1499
    elif damage == "deadline":
        samples[2]["elapsed_ms"] = 8000
    elif damage == "selection":
        context["selected_capture_ids"].reverse()
    elif damage == "duplicate":
        samples[1]["frame"]["capture_id"] = "sample-0"
        context["selected_capture_ids"][1] = "sample-0"
    elif damage == "window":
        samples[1]["frame"]["window_identity"]["process_id"] += 1
    elif damage == "path":
        samples[1]["frame"] = frame(tmp_path.parent / "outside", "sample-1")
    elif damage == "hash":
        Path(samples[1]["frame"]["image_path"]).write_bytes(b"changed")
    else:
        context["original_after"]["capture_id"] = "another-original"
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == "rejected" and not result["adopted"] and calls == []
    finally:
        client.close()


def test_generic_prompt_compares_only_target_and_sends_bound_description(tmp_path, monkeypatch):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == "completed" and result["adopted"]
        body = json.loads(calls[0].content)
        question = body["questions"][0]["instructions"]
        assert all(text in question for text in (TARGET, CONDITION, "sample_start", "sample_middle", "sample_end"))
        assert "Do not require" in question and "OCR" in question
        assert all(text in question for text in ("mouse", "occlusion", "loading", "controls"))
        assert "refuse" in question and "whole page" in question
        assert "video" not in question and "actually advance" not in question
        content = body["input"][0]["content"]
        images = [part["image_url"] for part in content if part["type"] == "input_image"]
        assert len(images) == 3
        assert [sha256(base64.b64decode(url.split(",", 1)[1])).hexdigest() for url in images] == [
            sample["frame"]["sha256"] for sample in args["temporal_context"]["samples"]]
        metadata = next(part["text"] for part in content if part["type"] == "input_text"
            and '"target_description"' in part["text"])
        assert TARGET in metadata and '"schema": "temporal_visual_change.v1"' in metadata
        assert str(tmp_path) not in json.dumps(body)
        assert runtime.validate_result(result, **args) and runtime.validate_result(result)
        assert runtime.evaluate(**args) == result and len(calls) == 1
    finally:
        client.close()


def test_generic_prompt_version_and_target_are_authenticated(tmp_path, monkeypatch):
    import app.judgment.service as module
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    policies, canonical = [], module._canonical
    def capture(value):
        if isinstance(value, dict) and "policy" in value:
            policies.append(value["policy"])
        return canonical(value)
    monkeypatch.setattr(module, "_canonical", capture)
    try:
        _, _, digest = runtime._prepare(args)
        assert policies[-1]["prompt_version"] == "decision_prompt.temporal_visual_change.v1"
        changed = deepcopy(args)
        changed["temporal_context"]["target_description"] = "The other clock digits."
        assert runtime._prepare(changed)[2] != digest and calls == []
        result = runtime.evaluate(**args)
        assert runtime.validate_result(result, **args)
        assert not runtime.validate_result(result, **changed)
        assert runtime.evaluate(**changed)["status"] == "conflict" and len(calls) == 1
        forged = deepcopy(result)
        forged["temporal_context"]["target_description"] = changed["temporal_context"]["target_description"]
        assert not runtime.validate_result(forged)
        Path(args["temporal_context"]["samples"][1]["frame"]["image_path"]).write_bytes(b"middle changed")
        assert not runtime.validate_result(result, **args)
    finally:
        client.close()


@pytest.mark.parametrize("met,error,review,verdict,disposition", [
    (0.799999, 0.01, 0.01, "uncertain", "review_required"),
    (0.8, 0.1, 0.699999, "success", "continue"),
    (0.8, 0.01, 0.7, "success", "review_required"),
    (0.8, 0.100001, 0.01, "uncertain", "review_required"),
    (0.8, 0.9, 0.01, "uncertain", "review_required"),
])
def test_generic_adoption_uses_only_authorized_after_action_thresholds(tmp_path, monkeypatch, met, error, review, verdict, disposition):
    def handler(request):
        values = {"condition_met": met, "visible_error": error, "needs_agent_review": review}
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": question["name"], "probability": values[question["name"]]}
            for question in json.loads(request.content)["questions"]],
            "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1}})
    runtime, calls, client = service(tmp_path, monkeypatch, handler=handler)
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        assert (result["verdict"], result["disposition"]) == (verdict, disposition)
        assert result["adopted"] is (disposition == "continue")
        assert runtime.validate_result(result, **args) and len(calls) == 1
        changed = DecisionService(tmp_path, profile=DecisionProfile.model_validate({
            **runtime.profile.model_dump(), "after_action_pass_threshold": 0.81}))
        assert not changed.validate_result(result, **args)
    finally:
        client.close()


@pytest.mark.parametrize("kind", ["refusal", "timeout", "always_main", "missing_key"])
def test_generic_uncertainty_keeps_main_and_does_not_redispatch(tmp_path, monkeypatch, kind):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "refusal", "name": question["name"]} for question in json.loads(request.content)["questions"]],
            "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1}})
    runtime, calls, client = service(tmp_path, monkeypatch, handler=handler,
        profile={"review_policy": "always_main"} if kind == "always_main" else {})
    args = arguments(tmp_path)
    if kind == "missing_key":
        monkeypatch.delenv("TEMPORAL_DECISION_TEST_KEY")
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == {"refusal": "refused", "timeout": "timeout", "always_main": "skipped",
                                    "missing_key": "not_connected"}[kind]
        assert not result["adopted"] and result["disposition"] == "review_required"
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result
        assert len(calls) == (0 if kind in ("always_main", "missing_key") else 1)
    finally:
        client.close()


def test_target_description_cannot_silently_change_video_schema(tmp_path):
    args = video_arguments(tmp_path)
    args["temporal_context"]["target_description"] = TARGET
    with pytest.raises(ValueError, match="decision_temporal_fields_invalid"):
        prepare_request(tmp_path, **args)
