"""三张截图的画面变化协议；仅离线校验真实传图和原证据绑定。"""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest

from app.judgment.evidence import prepare_request
from tests.test_video_playback_decision import CONDITION, arguments as v1_arguments, frame, service


def arguments(root):
    args = v1_arguments(root)
    args["request_id"] = "picture-change-one"
    samples = [{"frame": sample["frame"], "elapsed_ms": 1000 + index * 500}
        for index, sample in enumerate(args["temporal_context"]["samples"])]
    for index, sample in enumerate(samples):
        path = Path(sample["frame"]["image_path"])
        Image.new("RGB", (16, 16), (index * 60, 40, 80)).save(path)
        sample["frame"]["sha256"] = sha256(path.read_bytes()).hexdigest()
    args["temporal_context"] = {"schema": "temporal_playback.v2", "original_after": deepcopy(args["frames"][0]),
        "samples": samples, "selected_capture_ids": [sample["frame"]["capture_id"] for sample in samples],
        "timeout_seconds": 2}
    return args


def test_picture_change_uploads_exactly_three_ordered_authenticated_samples(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    binding, uploads = prepare_request(tmp_path, **args)
    assert binding["frames"] == args["frames"]
    assert binding["temporal_context"] == args["temporal_context"]
    assert [(f["capture_id"], f["role"]) for f in uploads] == [
        ("sample-0", "sample_start"), ("sample-1", "sample_middle"), ("sample-2", "sample_end")]
    for sample, uploaded in zip(args["temporal_context"]["samples"], uploads):
        data = base64.b64decode(uploaded["data_url"].split(",", 1)[1], validate=True)
        assert data == Path(sample["frame"]["image_path"]).read_bytes()
        assert sha256(data).hexdigest() == sample["frame"]["sha256"]
    assert args["frames"][0]["capture_id"] not in [f["capture_id"] for f in uploads]
    monkeypatch.setattr("app.judgment.temporal_playback.base64.b64encode",
        lambda *a: pytest.fail("采用认证不应重新编码图片"))
    assert prepare_request(tmp_path, **args, include_upload=False) == (binding, [])


@pytest.mark.parametrize("times", [[1000, 1500, 2000], [6999, 7499, 7999], [1000.5, 1500.5, 2000.5]])
def test_picture_change_accepts_bounded_read_only_capture_times(tmp_path, times):
    args = arguments(tmp_path)
    for sample, elapsed in zip(args["temporal_context"]["samples"], times):
        sample["elapsed_ms"] = elapsed
    assert len(prepare_request(tmp_path, **args)[1]) == 3


def test_picture_change_service_sends_one_three_image_request_with_new_question(tmp_path, monkeypatch):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == "completed" and result["adopted"]
        assert result["frames"] == args["frames"] and result["temporal_context"] == args["temporal_context"]
        body = json.loads(calls[0].content)
        content = body["input"][0]["content"]
        images = [part["image_url"] for part in content if part["type"] == "input_image"]
        assert len(images) == 3
        for data_url, sample in zip(images, args["temporal_context"]["samples"]):
            assert sha256(base64.b64decode(data_url.split(",", 1)[1])).hexdigest() == sample["frame"]["sha256"]
        question = body["questions"][0]["instructions"]
        assert all(word in question for word in ("sample_start", "sample_middle", "sample_end", "picture", "change"))
        assert "Do not require" in question and "playback" in question
        assert "buttons appearing/disappearing" in question
        assert "Treat screen change alone as insufficient" not in question
        assert "per-sample observed state" not in question and "content_bbox" not in question
        assert "actually advance" not in question and "Static frames establish visible states" not in question
        metadata = next(part["text"] for part in content if part["type"] == "input_text"
            and "Frozen temporal playback evidence" in part["text"])
        assert '"schema": "temporal_playback.v2"' in metadata and "sample_middle" in metadata
        assert '"observation":' not in metadata and '"analysis":' not in metadata and '"region":' not in metadata
        assert str(tmp_path) not in json.dumps(body)
        assert runtime.validate_result(result, **args) and runtime.validate_result(result)
        assert runtime.evaluate(**args) == result and len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("schema,expected", [("v2", "decision_prompt.temporal_playback.v2"),
    ("v1", "decision_prompt.temporal_playback.v1"), ("static", "decision_prompt.v2")])
def test_picture_prompt_version_is_part_of_authenticated_policy(tmp_path, monkeypatch, schema, expected):
    import app.judgment.service as module
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path) if schema == "v2" else v1_arguments(tmp_path)
    if schema == "static":
        args.pop("temporal_context")
    policies, original = [], module._canonical
    def capture(value):
        if isinstance(value, dict) and "policy" in value:
            policies.append(value["policy"])
        return original(value)
    monkeypatch.setattr(module, "_canonical", capture)
    try:
        runtime._prepare(args)
        assert policies[-1]["prompt_version"] == expected and calls == []
    finally:
        client.close()


@pytest.mark.parametrize("damage", ["extra", "region", "analysis", "observation", "schema", "count2", "count4",
    "early", "short_interval", "unordered", "deadline", "nan", "infinity", "boolean", "huge", "selection2",
    "selection_order", "duplicate_id", "original_id", "duplicate_path", "window", "dimensions", "hash", "outside",
    "jpeg", "original_mismatch", "original_size", "timeout0", "timeout9"])
def test_picture_change_rejects_invalid_evidence_without_provider_call(tmp_path, monkeypatch, damage):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    context = args["temporal_context"]
    samples = context["samples"]
    if damage in ("extra", "region", "analysis"):
        context[{"extra": "prompt", "region": "region", "analysis": "analysis"}[damage]] = {}
    elif damage == "observation":
        samples[0]["observation"] = {"state": "playing"}
    elif damage == "schema":
        context["schema"] = "temporal_playback.v3"
    elif damage == "count2":
        samples.pop()
    elif damage == "count4":
        samples.append({"frame": frame(tmp_path, "fourth"), "elapsed_ms": 2500})
    elif damage in ("early", "short_interval", "unordered", "deadline", "nan", "infinity", "boolean", "huge"):
        index, value = {"early": (0, 999), "short_interval": (1, 1499), "unordered": (1, 900),
            "deadline": (2, 8000), "nan": (1, float("nan")), "infinity": (1, float("inf")),
            "boolean": (0, True), "huge": (1, 10 ** 400)}[damage]
        samples[index]["elapsed_ms"] = value
    elif damage == "selection2":
        context["selected_capture_ids"] = ["sample-0", "sample-2"]
    elif damage == "selection_order":
        context["selected_capture_ids"].reverse()
    elif damage == "duplicate_id":
        samples[1]["frame"]["capture_id"] = samples[0]["frame"]["capture_id"]
        context["selected_capture_ids"][1] = samples[0]["frame"]["capture_id"]
    elif damage == "original_id":
        samples[1]["frame"]["capture_id"] = context["original_after"]["capture_id"]
        context["selected_capture_ids"][1] = context["original_after"]["capture_id"]
    elif damage == "duplicate_path":
        samples[1]["frame"]["image_path"] = samples[0]["frame"]["image_path"]
        samples[1]["frame"]["sha256"] = samples[0]["frame"]["sha256"]
    elif damage == "window":
        samples[1]["frame"]["window_identity"]["handle"] += 1
    elif damage == "dimensions":
        samples[1]["frame"] = frame(tmp_path, "sample-1", size=(17, 16))
    elif damage == "hash":
        Path(samples[1]["frame"]["image_path"]).write_bytes(b"changed")
    elif damage == "outside":
        samples[1]["frame"] = frame(tmp_path.parent / "outside", "sample-1")
    elif damage == "jpeg":
        item = samples[1]["frame"]
        Image.new("RGB", (16, 16)).save(item["image_path"], format="JPEG")
        item["sha256"] = sha256(Path(item["image_path"]).read_bytes()).hexdigest()
    elif damage == "original_mismatch":
        context["original_after"]["capture_id"] = "different"
    elif damage == "original_size":
        args["frames"][0] = frame(tmp_path, "original", "after", size=(17, 16))
        context["original_after"] = deepcopy(args["frames"][0])
    else:
        context["timeout_seconds"] = 0 if damage == "timeout0" else 9
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == "rejected" and not result["adopted"] and calls == []
    finally:
        client.close()


@pytest.mark.parametrize("which", ["original_after", 0, 1, 2])
def test_picture_change_refuses_animated_png_at_every_frame(tmp_path, monkeypatch, which):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    item = args["frames"][0] if which == "original_after" else args["temporal_context"]["samples"][which]["frame"]
    path = Path(item["image_path"])
    Image.new("RGB", (16, 16), "black").save(path, format="PNG", save_all=True,
        append_images=[Image.new("RGB", (16, 16), "white")], duration=100, loop=0)
    item["sha256"] = sha256(path.read_bytes()).hexdigest()
    if which == "original_after":
        args["temporal_context"]["original_after"] = deepcopy(item)
    try:
        assert runtime.evaluate(**args)["status"] == "rejected" and calls == []
    finally:
        client.close()


def test_picture_change_authentication_keeps_middle_frame_and_original_after_bound(tmp_path, monkeypatch):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        assert runtime.validate_result(result, **args)
        changed = deepcopy(args)
        for sample in changed["temporal_context"]["samples"]:
            sample["elapsed_ms"] += 10
        assert not runtime.validate_result(result, **changed)
        assert runtime.evaluate(**changed)["status"] == "conflict" and len(calls) == 1
        forged = deepcopy(result)
        forged["temporal_context"]["timeout_seconds"] = 1
        assert not runtime.validate_result(forged)
        Path(args["temporal_context"]["samples"][1]["frame"]["image_path"]).write_bytes(b"middle changed")
        assert not runtime.validate_result(result, **args) and len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("kind", ["timeout", "refusal", "always_main", "missing_key"])
def test_picture_change_uncertainty_preserves_main_and_never_retries(tmp_path, monkeypatch, kind):
    def handle(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        names = [q["name"] for q in json.loads(request.content)["questions"]]
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "refusal", "name": name} for name in names],
            "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1}})
    runtime, calls, client = service(tmp_path, monkeypatch, handler=handle,
        profile={"review_policy": "always_main"} if kind == "always_main" else {})
    if kind == "missing_key":
        monkeypatch.delenv("TEMPORAL_DECISION_TEST_KEY")
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == {"timeout": "timeout", "refusal": "refused", "always_main": "skipped",
            "missing_key": "not_connected"}[kind]
        assert not result["adopted"] and result["disposition"] == "review_required"
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result and len(calls) == (0 if kind in ("always_main", "missing_key") else 1)
    finally:
        client.close()


@pytest.mark.parametrize("damage", ["two_uploads", "order", "role", "id", "budget"])
def test_picture_change_provider_requires_all_three_roles_and_bound_budget(tmp_path, monkeypatch, damage):
    runtime, calls, client = service(tmp_path, monkeypatch)
    try:
        binding, uploads, digest = runtime._prepare(arguments(tmp_path))
        payload = {"condition": CONDITION, "phase": "after_action", "frames": uploads, "request_sha256": digest,
            "schema_version": "decision_request.v2", "enabled_predicates": ["condition_met", "visible_error", "needs_agent_review"],
            "review_context": binding["review_context"], "temporal_context": binding["temporal_context"]}
        if damage == "two_uploads":
            payload["frames"].pop(1)
        elif damage == "order":
            payload["frames"].reverse()
        elif damage == "role":
            payload["frames"][1]["role"] = "sample_end"
        elif damage == "id":
            payload["frames"][1]["capture_id"] = "unbound"
        else:
            payload["request_timeout_seconds"] = 3
        with pytest.raises(ValueError):
            runtime._provider.judge(payload)
        assert calls == []
    finally:
        client.close()


def test_picture_change_does_not_expand_static_frame_limit(tmp_path):
    args = arguments(tmp_path)
    args.pop("temporal_context")
    args["frames"] += [frame(tmp_path, "before-1", "before"), frame(tmp_path, "before-2", "before")]
    with pytest.raises(ValueError, match="decision_frames_invalid"):
        prepare_request(tmp_path, **args)
