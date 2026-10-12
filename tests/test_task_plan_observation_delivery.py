"""MCP只返回明确追加观察的原像素，拒绝错绑或失效文件。"""
import asyncio
import base64
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.instant_mcp import build_server


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    root = tmp_path / "session"
    path = root / "task-plan-observations" / "manual.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (80, 60), "blue").save(path)
    raw = path.read_bytes()
    frame = {"role": "observation", "capture_id": "manual-one", "image_path": str(path),
        "sha256": sha256(raw).hexdigest(), "window_identity": {"handle": 11, "process_id": 22, "process_create_time": 33.0}}
    packet = {"schema": "review_packet.v3", "packet_sha256": "b" * 64, "latest_observation": deepcopy(frame),
        "input_evidence_refs": [{"path": "task-plan-observations/manual.png", "sha256": frame["sha256"]}]}
    receipt = {"request_id": "manual-request", "status": "returned", "operation_success_scope": "task_plan_control",
        "command": {"kind": "task_plan", "request": {"action": "observe"}},
        "result": {"review_packet": packet, "manual_observation": {"status": "captured", "packet_sha256": "b" * 64,
            "observation_request_id": "logical-one", "frame": deepcopy(frame)}}}
    checks = []
    def validate(packet, state, session):
        checks.append((deepcopy(packet), deepcopy(state), session))
    monkeypatch.setattr("app.execution.task_plan_review.validate_packet", validate)
    class Session:
        session = root
        def result(self, request_id):
            assert request_id == "manual-request"
            return deepcopy(receipt)
        def image(self, *args, **kwargs):
            pytest.fail("追加观察不能调用原动作 after 图接口")
        def _path(self, request_id, folder):
            return root / folder / (request_id + ".json")
    return SimpleNamespace(root=root, path=path, raw=raw, frame=frame, receipt=receipt, checks=checks, session=Session())


def call_result(d, *, images="after"):
    return asyncio.run(build_server(d.session).call_tool("instant_result", {
        "request_id": "manual-request", "detail": "full", "images": images}))


@pytest.mark.parametrize("images", ["after", "both"])
def test_manual_observation_mcp_delivers_one_labeled_image(delivery, images):
    result = call_result(delivery, images=images)
    blocks = [block for block in result.content if block.type == "image"]
    assert len(blocks) == 1
    assert base64.b64decode(blocks[0].data) == delivery.raw
    value = json.loads(result.content[0].text)
    assert value["image_delivery"][0]["view"] == "observation"
    assert value["image_delivery"][0]["sha256"] == delivery.frame["sha256"]
    assert len(delivery.checks) == 1


def test_no_image_option_does_not_read_observation_evidence(delivery):
    delivery.path.write_bytes(b"changed")
    result = call_result(delivery, images="none")
    assert not any(block.type == "image" for block in result.content)
    assert delivery.checks == []


@pytest.mark.parametrize("damage", ["hash", "outside", "reference", "packet", "frame", "png", "validation"])
def test_manual_observation_delivery_rejects_corrupt_or_unbound_evidence(delivery, monkeypatch, damage):
    d = delivery
    p = d.receipt["result"]["review_packet"]
    outcome = d.receipt["result"]["manual_observation"]
    if damage == "hash":
        d.path.write_bytes(b"changed")
    elif damage == "outside":
        outside = d.root.parent / "outside.png"
        outside.write_bytes(d.raw)
        p["latest_observation"]["image_path"] = str(outside)
        outcome["frame"]["image_path"] = str(outside)
    elif damage == "reference":
        p["input_evidence_refs"] = []
    elif damage == "packet":
        outcome["packet_sha256"] = "c" * 64
    elif damage == "frame":
        outcome["frame"]["capture_id"] = "other-frame"
    elif damage == "png":
        raw = b"not a PNG"
        d.path.write_bytes(raw)
        p["latest_observation"]["sha256"] = outcome["frame"]["sha256"] = sha256(raw).hexdigest()
        p["input_evidence_refs"][0]["sha256"] = sha256(raw).hexdigest()
    else:
        def invalid(*args):
            raise ValueError("synthetic private path")
        monkeypatch.setattr("app.execution.task_plan_review.validate_packet", invalid)
    result = call_result(d)
    assert not any(block.type == "image" for block in result.content)
    value = json.loads(result.content[0].text)
    assert value["image_delivery"][0]["status"] == "unavailable"
    assert "synthetic private path" not in str(value.get("image_delivery"))
    assert value["image_delivery"][0]["automatic_retry_allowed"] is False
