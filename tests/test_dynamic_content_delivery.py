"""通用动态判据贯穿真实判断服务、运行器及公共审核交付。"""
import asyncio
import base64
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.instant_mcp import build_server
from tests.test_task_plan_adaptive_review import review_request
from tests.test_task_plan_video_playback import playback_scene, tick_samples
from tests.test_video_playback_decision import service


CONDITION = "The main clock display is updating."
TARGET = "The seconds digits of the main clock display"


def dynamic_plan():
    return {"schema_version": "task_plan.v2", "title": "Check the public live clock", "inputs": {},
        "steps": [{"step_id": "clock", "action": {"kind": "click", "goal": "Open the public clock"},
            "verification": {"kind": "dynamic_content", "target_description": TARGET,
                "decision_condition": CONDITION}}]}


@pytest.mark.parametrize("configured", [False, True])
def test_dynamic_condition_uses_authenticated_three_images_or_original_main(tmp_path, monkeypatch, configured):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"auto_conditions": [CONDITION],
        "after_action_pass_threshold": .8, "after_action_review_threshold": .7})
    try:
        s, original, clock, calls = playback_scene(tmp_path, monkeypatch,
            source=dynamic_plan(), service=runtime if configured else None, mode="unknown")
        result = tick_samples(s, clock)
        assert len(calls.capture) == 3 and calls.locate == [] and calls.observe == []
        assert len(list(tmp_path.glob("commands/*.json"))) == 1
        if configured:
            assert result["status"] == "completed" and result["history"][0]["judged_by"] == "decision"
            assert len(requests) == 1
            body = json.loads(requests[0].content)
            content = body["input"][0]["content"]
            images = [item["image_url"] for item in content if item["type"] == "input_image"]
            assert len(images) == 3
            assert TARGET in json.dumps(body)
            from app.execution.video_playback_verification import VideoPlaybackLedger
            ledger = VideoPlaybackLedger(s.runtime.backend, original.command_id)
            assert ledger.summary()["schema"] == "dynamic_content_binding.v1"
            for image, sample in zip(images, ledger.samples()):
                assert base64.b64decode(image.split(",", 1)[1]) == Path(sample["frame"]["image_path"]).read_bytes()
        else:
            assert result["review_required"] is True and result["history"] == [] and requests == []
            packet = result["review_packet"]
            assert packet["video_playback"]["schema"] == "dynamic_content_binding.v1"
            receipt = {"request_id": "dynamic-status", "status": "returned",
                "operation_success_scope": "task_plan_control", "result": result}

            class Session:
                session = tmp_path

                def result(self, request_id):
                    return deepcopy(receipt)

                def _path(self, request_id, folder):
                    return tmp_path / folder / (request_id + ".json")

                def image(self, *args, **kwargs):
                    raise AssertionError("动态观察不能冒充原动作后图")

            server = build_server(Session())
            delivered = asyncio.run(server.call_tool("instant_result", {
                "request_id": "dynamic-status", "detail": "full", "images": "after"}))
            images = [item for item in delivered.content if item.type == "image"]
            assert len(images) == 3
            for image, sample in zip(images, packet["video_playback"]["samples"]):
                assert base64.b64decode(image.data) == Path(sample["frame"]["image_path"]).read_bytes()
            review = review_request(s, result, original)
            review["step_id"] = packet["step_id"]
            reviewed = s.runtime.control(review, "dynamic-main-review")
            assert reviewed["status"] == "completed" and reviewed["history"][0]["judged_by"] == "agent"
        assert len(calls.capture) == 3 and len(list(tmp_path.glob("commands/*.json"))) == 1
    finally:
        runtime.close()
        client.close()
