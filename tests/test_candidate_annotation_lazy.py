"""只省未上传的整窗 PNG 编码，所有模型请求字节保持原样。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import struct
import zlib

import httpx
from PIL import Image
import pytest

from app.judgment import candidate_annotation, evidence, OpenAIDecisionsProvider
from test_candidate_current_scope import candidate_args
from test_decision_candidate_annotation_integration import request_args
from test_decision_service import arguments as result_args
from test_executed_click_integration import arguments as field_args


# 修改生产代码前由真实 httpx Request.content 冻结，包含完整图片和问题字节。
BODY_SHA256 = {
    "legacy": "96043b20ad154bd2520cd5bcb98135ce9647d881f01ef8ab37d15b47f0ff35e8",
    "graphic": "6238918872f3832b00bccc2cc2e9683e422d965bdf4c9031277db6e16f7ba245",
    "field": "97fb12211a5e73189084412798cc7d06de23967fe2f1d9b9e5f7e47de7f67a24",
    "focus": "677f1b1522b0c1cdb6db2eaa5f54aa5e8f3562cba042450b4d21f6cfd782a53e",
    "value": "3c45e32c1144a952595813599473a86254352a08fe5c7ffb08e7a8b6a4b75bbb",
    "freshness": "bc023eae460265d476ae636d8499745b18204b1af7762984d2a733e113a7de6e",
    # 已用旧工厂复原原摘要 0ecf5a26；新正文仅替换冻结结果问句。
    "unmarked": "57c7e0196ae6553995219a8bf7ed9ba3132e8ac2bce569536901585dc3368673",
    "ordinary": "b0232d40ead1cf01ca18d97fc4b2f5e1238b6e83048aaae7d0919a11190a9374",
}


class Stop(BaseException):
    pass


def payload(root, route):
    if route in {"focus", "value"}:
        args = field_args(root, phase=route)
    elif route == "unmarked":
        args = result_args(root)
    elif route == "legacy":
        args = request_args(root)
    else:
        args = candidate_args(root, "FIXED")
        if route == "graphic":
            args["action"]["permitted_action"] = {"kind": "click", "goal": "Browser address bar"}
        if route in {"graphic", "field", "ordinary"}:
            args["action"]["target_check"] = {"schema": "target_check.v1",
                "kind": "graphic" if route == "graphic" else "input_field", "target": "Browser address bar",
                "appearance": "Long light field", "container": "Browser toolbar"}
        if route == "freshness":
            path = root / "latest.png"
            Image.new("RGB", (160, 90), "gray").save(path)
            args["frames"].append({**args["frames"][0], "capture_id": "latest", "role": "observation",
                "image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()})
            args["action"]["candidate"]["capture_id"] = "latest"
            args["action"]["freshness_context"] = {"schema": "action_freshness.v1",
                "changed_region": {"x": 120, "y": 60, "w": 10, "h": 10}}
    binding, frames = evidence.prepare_request(root, **args)
    result = {"condition": binding["condition"], "phase": binding["phase"], "frames": frames,
        "action": binding["action"], "request_sha256": "a" * 64, "schema_version": "decision_request.v2",
        "enabled_predicates": [], "review_context": binding.get("review_context")}
    if route != "legacy":
        result["decision_format"] = "choice"
    else:
        result["enabled_predicates"] = ["condition_met", "unsafe_effect"]
    return args, binding, result


def wire(value, monkeypatch, *, ordinary=False):
    monkeypatch.setenv("LAZY_ANNOTATION_TEST_KEY", "offline-dummy")
    sent = []
    def capture(request):
        sent.append(request.content)
        raise Stop()
    with httpx.Client(transport=httpx.MockTransport(capture)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="LAZY_ANNOTATION_TEST_KEY", client=client)
        with pytest.raises(Stop):
            (provider.review if ordinary else provider.judge)(value)
    assert len(sent) == 1
    return sent[0]


@pytest.mark.parametrize("route", list(BODY_SHA256))
def test_complete_real_httpx_body_matches_before_optimization(tmp_path, monkeypatch, route):
    _, _, value = payload(tmp_path, route)
    actual = sha256(wire(value, monkeypatch, ordinary=route == "ordinary")).hexdigest()
    assert actual == BODY_SHA256[route], (route, actual)


def test_preparation_does_not_render_or_encode_marked_full_window(tmp_path, monkeypatch):
    args = candidate_args(tmp_path, "FIXED")
    def forbidden(*args, **kwargs):
        raise AssertionError("unused marked PNG must not render or encode")
    monkeypatch.setattr(candidate_annotation, "render_candidate_annotation", forbidden)
    monkeypatch.setattr(Image.Image, "save", forbidden)
    binding, frames = evidence.prepare_request(tmp_path, **args)
    assert set(frames[0]["candidate_annotation"]) == {"metadata"}
    authenticated, omitted = evidence.prepare_request(tmp_path, **args, include_upload=False)
    assert authenticated == binding and omitted == []


@pytest.mark.parametrize("route,expected", [("graphic", 0), ("field", 0), ("freshness", 1), ("legacy", 1)])
def test_only_compatibility_route_lazily_renders_full_window(tmp_path, monkeypatch, route, expected):
    original = candidate_annotation.render_candidate_annotation
    calls = []
    def render(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(candidate_annotation, "render_candidate_annotation", render)
    _, _, value = payload(tmp_path, route)
    assert calls == []
    wire(value, monkeypatch)
    assert len(calls) == expected


@pytest.mark.parametrize("route", ["graphic", "field", "legacy", "freshness"])
def test_old_eager_frame_and_new_metadata_frame_produce_identical_http_bytes(tmp_path, monkeypatch, route):
    _, _, value = payload(tmp_path, route)
    eager = deepcopy(value)
    for frame in eager["frames"]:
        if "candidate_annotation" in frame:
            annotation = frame["candidate_annotation"]
            source = base64.b64decode(frame["data_url"].split(",", 1)[1])
            marked = candidate_annotation.render_candidate_annotation(source, annotation["metadata"])
            annotation["data_url"] = "data:image/png;base64," + base64.b64encode(marked).decode("ascii")
    original = deepcopy(value)
    assert wire(value, monkeypatch) == wire(eager, monkeypatch)
    assert value == original


def test_candidate_prepare_still_decodes_pixels_before_dispatch_marker(tmp_path):
    args = candidate_args(tmp_path, "FIXED")
    path = tmp_path / "capture.png"
    original = path.read_bytes()
    chunks, cursor = [original[:8]], 8
    while cursor < len(original):
        length = struct.unpack(">I", original[cursor:cursor+4])[0]
        kind = original[cursor+4:cursor+8]
        data = original[cursor+8:cursor+8+length]
        if kind == b"IDAT":
            data = b"invalid compressed pixels"
        chunks.append(struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data)))
        cursor += length + 12
    broken = b"".join(chunks)
    with Image.open(BytesIO(broken)) as image:
        image.verify()
    path.write_bytes(broken)
    args["frames"][0]["sha256"] = sha256(broken).hexdigest()
    with pytest.raises(ValueError, match="candidate_annotation_image_invalid"):
        evidence.prepare_request(tmp_path, **args)


@pytest.mark.parametrize("fault", ["public_skip", "invalid_legacy_url"])
def test_new_internal_shape_does_not_accept_skip_flags_or_weaken_legacy_validation(tmp_path, monkeypatch, fault):
    _, _, value = payload(tmp_path, "field")
    annotation = value["frames"][0]["candidate_annotation"]
    annotation["skip_render" if fault == "public_skip" else "data_url"] = True if fault == "public_skip" else None
    with pytest.raises(ValueError, match="candidate_annotation_invalid"):
        wire(value, monkeypatch)
