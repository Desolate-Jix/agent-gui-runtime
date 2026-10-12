"""真实运行器与判断服务跨层闭合；桌面采样和 HTTP 均为离线合成证据。"""
import base64
from hashlib import sha256
import json

import httpx
import pytest

from app.core.json_snapshot import read_json_snapshot
from tests.test_task_plan_adaptive_review import review_request
from tests.test_task_plan_video_playback import CONDITION, playback_scene, tick_samples
from tests.test_video_playback_decision import service


@pytest.mark.parametrize("refusal", [False, True])
def test_public_video_playback_uses_real_authenticated_temporal_decision_once(tmp_path, monkeypatch, refusal):
    def refused(request):
        names = [question["name"] for question in json.loads(request.content)["questions"]]
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "refusal", "name": name} for name in names],
            "usage": {"input_tokens": 3, "output_tokens": 0, "total_tokens": 3}})
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"auto_conditions": [CONDITION]},
        handler=refused if refusal else None)
    try:
        s, original, clock, calls = playback_scene(tmp_path, monkeypatch, service=runtime, mode="unknown")
        result = tick_samples(s, clock, count=3)
        assert len(requests) == 1 and len(calls.capture) == 3
        assert len(list(tmp_path.glob("commands/*.json"))) == 1
        assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
        body = json.loads(requests[0].content)
        content = body["input"][0]["content"]
        labels = [item["text"] for item in content if item["type"] == "input_text" and item["text"].startswith("Frame role:")]
        images = [item["image_url"] for item in content if item["type"] == "input_image"]
        assert labels == ["Frame role: sample_start", "Frame role: sample_middle", "Frame role: sample_end"] and len(images) == 3
        hashes = [sha256(base64.b64decode(url.split(",", 1)[1], validate=True)).hexdigest() for url in images]
        from app.execution.video_playback_verification import VideoPlaybackLedger
        ledger = VideoPlaybackLedger(s.runtime.backend, original.command_id)
        samples = ledger.samples()
        assert hashes == [sample["frame"]["sha256"] for sample in samples]
        assert "video picture" in body["questions"][0]["instructions"].lower()
        assert original.capture["sha256"] not in hashes
        if refusal:
            assert result["review_required"] is True and result["history"] == []
            packet = result["review_packet"]
            assert packet["schema"] == "review_packet.v4"
            assert packet["execution_request_id"] == original.command_id
            assert len(packet["video_playback"]["samples"]) == 3
            assert "refus" in packet["reason"]
            for index in range(2):
                status = s.runtime.control({"action": "status", "run_id": s.run_id}, "main-status-" + str(index))
                assert status["review_packet"] == packet and s.runtime.tick(force=True) is None
            reviewed = s.runtime.control(review_request(s, result, original), "temporal-main-review")
            assert reviewed["status"] == "completed" and reviewed["history"][0]["judged_by"] == "agent"
        else:
            assert result["status"] == "completed" and result["history"][0]["judged_by"] == "decision"
            assert result["history"][0]["execution_request_id"] == original.command_id
            assert result["history"][0]["original_input_status"] == "completed"
        assert len(requests) == 1 and len(calls.capture) == 3
        assert len(list(tmp_path.glob("commands/*.json"))) == 1
        assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
    finally:
        runtime.close()
        client.close()
