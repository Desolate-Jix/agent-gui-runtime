"""完整时序审核包通过公共 MCP 投递原像素，不触发新观察。"""
import asyncio
import base64
from copy import deepcopy
import json
from pathlib import Path

from app.instant_mcp import build_server
from tests.test_task_plan_video_playback import playback_scene, tick_samples


def test_maintained_component_collects_playback_dependencies_without_gui():
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    _, _, sources = collect_execution_sources(root)
    paths = {path.relative_to(root).as_posix() for path in sources}
    assert {"app/execution/video_playback_observer.py", "app/execution/video_playback_evidence.py",
            "app/execution/video_playback_verification.py", "app/judgment/temporal_playback.py"} <= paths


def test_public_result_delivers_bound_temporal_sequence(tmp_path, monkeypatch):
    s, _, clock, calls = playback_scene(tmp_path, monkeypatch, mode="unknown")
    state = tick_samples(s, clock, count=3)
    assert state["review_packet"]["schema"] == "review_packet.v4"
    receipt = {"request_id": "video-status", "status": "returned",
        "operation_success_scope": "task_plan_control", "result": state}
    class Session:
        session = tmp_path
        def result(self, request_id):
            assert request_id == "video-status"
            return deepcopy(receipt)
        def _path(self, request_id, folder):
            return tmp_path / folder / (request_id + ".json")
        def image(self, *args, **kwargs):
            raise AssertionError("不得把观察图冒充原动作 after")
    server = build_server(Session())
    result = asyncio.run(server.call_tool("instant_result", {
        "request_id": "video-status", "detail": "full", "images": "after"}))
    value = json.loads(result.content[0].text)
    blocks = [b for b in result.content if b.type == "image"]
    assert len(blocks) == 3
    assert len(calls.capture) == 3
    for index, sample in enumerate(state["review_packet"]["video_playback"]["samples"]):
        assert base64.b64decode(blocks[index].data) == Path(sample["frame"]["image_path"]).read_bytes()
        assert value["image_delivery"][index]["elapsed_ms"] == sample["elapsed_ms"]
        assert value["image_delivery"][index]["original_action_after"] is False
    Path(state["review_packet"]["video_playback"]["samples"][0]["frame"]["image_path"]).write_bytes(b"tampered")
    invalid = asyncio.run(server.call_tool("instant_result", {
        "request_id": "video-status", "detail": "full", "images": "after"}))
    assert not any(b.type == "image" for b in invalid.content)
    assert json.loads(invalid.content[0].text)["image_delivery"][0]["status"] == "unavailable"
