"""三图判断待审核时，公共接口交付原三帧且拒绝被替换的证据。"""
import asyncio
import base64
from copy import deepcopy
import json
from pathlib import Path

from app.instant_mcp import build_server
from tests.test_video_picture_change_runtime import picture_scene, capture_three


def test_public_result_delivers_exact_three_bound_frames_without_recapture(tmp_path, monkeypatch):
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch)
    state = capture_three(s, clock)
    packet = state["review_packet"]
    assert packet["video_playback"]["schema"] == "video_playback_binding.v2"
    receipt = {"request_id": "picture-status", "status": "returned",
        "operation_success_scope": "task_plan_control", "result": state}

    class Session:
        session = tmp_path

        def result(self, request_id):
            assert request_id == "picture-status"
            return deepcopy(receipt)

        def _path(self, request_id, folder):
            return tmp_path / folder / (request_id + ".json")

        def image(self, *args, **kwargs):
            raise AssertionError("不得把观察图冒充原动作 after")

    server = build_server(Session())
    request = {"request_id": "picture-status", "detail": "full", "images": "after"}
    result = asyncio.run(server.call_tool("instant_result", request))
    value = json.loads(result.content[0].text)
    blocks = [block for block in result.content if block.type == "image"]
    assert len(blocks) == 3 and len(calls.capture) == 3
    samples = packet["video_playback"]["samples"]
    assert [sample["elapsed_ms"] for sample in samples] == [1000, 1500, 2000]
    for index, sample in enumerate(samples):
        assert base64.b64decode(blocks[index].data) == Path(sample["frame"]["image_path"]).read_bytes()
        assert value["image_delivery"][index]["elapsed_ms"] == sample["elapsed_ms"]
        assert value["image_delivery"][index]["original_action_after"] is False
        assert sample["frame"]["capture_id"] != original.capture["capture_id"]
    Path(samples[1]["frame"]["image_path"]).write_bytes(b"tampered-middle")
    invalid = asyncio.run(server.call_tool("instant_result", request))
    assert not any(block.type == "image" for block in invalid.content)
    assert json.loads(invalid.content[0].text)["image_delivery"][0]["status"] == "unavailable"
    assert len(calls.capture) == 3
