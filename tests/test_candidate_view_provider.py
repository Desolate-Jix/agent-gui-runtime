"""候选复合图只改变模型视图，不改变原图、点位和本地认证。"""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from app.execution.action_review import CANDIDATE_CONDITION
from app.judgment import evidence
from test_candidate_current_scope import INPUT_FEASIBILITY, candidate_args
from test_decision_choice import choice_reply, runtime


def provider_payload(root):
    args = candidate_args(root, "PROVIDER")
    binding, uploaded = evidence.prepare_request(root, **args)
    return args, {"condition": binding["condition"], "phase": binding["phase"],
        "action": binding["action"], "frames": uploaded, "request_sha256": "a" * 64,
        "schema_version": "decision_request.v2", "decision_format": "choice",
        "enabled_predicates": [], "review_context": binding["review_context"]}


def test_choice_candidate_wire_uses_compact_current_semantics_and_one_hollow_composite(tmp_path, monkeypatch):
    args, payload = provider_payload(tmp_path)
    source = Path(args["frames"][0]["image_path"]).read_bytes()
    original = deepcopy(payload)
    service, calls, client = runtime(tmp_path, monkeypatch)
    try:
        answer = service._get_provider().judge(payload)
        assert answer["choice_result"]["choice"] == "condition_met"
        assert len(calls) == 1
        body = json.loads(calls[0].content)
        content = body["input"][0]["content"]
        texts = [part["text"] for part in content if part["type"] == "input_text"]
        action = json.loads(next(text.split(": ", 1)[1] for text in texts
            if text.startswith("Current target and action")))
        assert action["target"] == "Browser address bar"
        assert action["permitted_action_kind"] == "input_sequence"
        assert action["click_kind"] == "single"
        assert set(action["marked_centers_in_composite"]) == {"overview", "detail"}
        images = [part for part in content if part["type"] == "input_image"]
        assert len(images) == 1
        composite = base64.b64decode(images[0]["image_url"].split(",", 1)[1], validate=True)
        with Image.open(BytesIO(composite)) as image:
            assert image.size != (160, 90)
            for x, y in action["marked_centers_in_composite"].values():
                assert 0 <= x < image.width and 0 <= y < image.height
                assert image.convert("RGB").getpixel((x, y)) == (255, 255, 255)
        question = body["questions"][0]["instructions"]
        assert len(body["questions"]) == 1
        assert question.count(INPUT_FEASIBILITY) == 1
        assert "Current target and action.target" in question
        assert "Browser address bar" not in question
        wire = json.dumps(body)
        for forbidden in ("capture_id", "candidate_id", "source_sha256", "target_window_identity",
                "envelope_sha256", args["frames"][0]["sha256"], "remaining_plan", "FUTURE_TEXT_",
                "GLOBAL_HISTORY_", "WHOLE_INPUT_STEP_", "FUTURE_PLAN_", "clear_existing", "submit_search"):
            assert forbidden not in wire
        assert args["review_context"]["allowed_states"][0] in wire
        popup = json.loads(next(text.split(": ", 1)[1] for text in texts
            if text.startswith("Current popup evidence")))
        assert popup == {"owned_popup": False}
        assert "An unrelated popup that does not obscure or block the target is not by itself a blocker." in question
        assert "wrong, disabled or directly blocked target" in question
        assert "explicit interactive prerequisite for this target" in question
        assert "without unsafe destructive, final-submit, send, confirm or payment effects" in question
        for forbidden in ("focused", "caret", "empty field", "can type", "future results",
                "would only dismiss", "without first handling an interactive popup"):
            assert forbidden not in question.lower()
        assert payload == original
        assert Path(args["frames"][0]["image_path"]).read_bytes() == source
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("fault", ["original_bytes", "source_hash", "view_dimensions", "candidate_point", "extra_metadata"])
def test_candidate_source_or_annotation_tamper_is_rejected_before_http(tmp_path, monkeypatch, fault):
    _, payload = provider_payload(tmp_path)
    annotation = payload["frames"][0]["candidate_annotation"]["metadata"]
    if fault == "original_bytes":
        replacement = BytesIO()
        Image.new("RGB", (160, 90), "gray").save(replacement, format="PNG")
        payload["frames"][0]["data_url"] = "data:image/png;base64," + base64.b64encode(replacement.getvalue()).decode("ascii")
    elif fault == "source_hash":
        annotation["source_sha256"] = "0" * 64
    elif fault == "view_dimensions":
        annotation["viewport_size"]["width"] += 1
    elif fault == "candidate_point":
        payload["action"]["candidate"]["click_point"]["x"] += 1
    else:
        annotation["forged_view"] = {"marker_center": [0, 0]}
    service, calls, client = runtime(tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError):
            service._get_provider().judge(payload)
        assert calls == []
    finally:
        service.close()
        client.close()


def test_two_frame_candidate_does_not_enter_single_frame_compact_view(tmp_path, monkeypatch):
    args, payload = provider_payload(tmp_path)
    # 服务入口本就要求两帧具有 freshness；此处单独验证 provider 的单帧边界。
    original = deepcopy(payload["frames"][0])
    original.pop("candidate_annotation")
    original["capture_id"] = "earlier"
    payload["frames"].insert(0, original)
    payload["frames"][1]["role"] = "observation"
    payload["frames"][1]["candidate_annotation"]["metadata"]["role"] = "observation"
    service, calls, client = runtime(tmp_path, monkeypatch)
    try:
        service._get_provider().judge(payload)
        body = json.loads(calls[0].content)
        content = body["input"][0]["content"]
        texts = [part["text"] for part in content if part["type"] == "input_text"]
        assert not any(text.startswith("Current target and action") for text in texts)
        action = json.loads(next(text.split(": ", 1)[1] for text in texts
            if text.startswith("Proposed action context")))
        assert action == args["action"]
        assert INPUT_FEASIBILITY not in body["questions"][0]["instructions"]
        assert len([part for part in content if part["type"] == "input_image"]) == 2
    finally:
        service.close()
        client.close()
