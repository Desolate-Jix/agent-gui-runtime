"""公共Client/MCP到原运行器、正式截图边界、审核和显式续接的离线联调。"""
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from PIL import Image

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.instant_mcp import InstantSession, build_server
from tests.test_instant_mcp import Alive
from tests.test_task_plan_adaptive_review import review_request
from tests.test_task_plan_client import client
from tests.test_task_plan_manual_observation import manual_scene, observe_request


@pytest.mark.parametrize("later_observation", [False, True])
def test_public_observe_review_continue_preserves_original_and_delivers_new_pixels(tmp_path, monkeypatch, later_observation):
    from app.execution import task_plan_manual_observation as manual
    from app.execution import task_plan_observation_capture as capture
    maintained_capture = capture.capture_followup
    s, original, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    original_bytes = original.after.read_bytes()
    original_receipt_bytes = (tmp_path / "responses" / (original.command_id + ".json")).read_bytes()
    monkeypatch.setattr(manual, "capture_followup", maintained_capture)
    source = tmp_path / "captures" / "fresh-maintained-source.png"
    Image.new("RGB", (80, 60), "blue").save(source)
    fresh_bytes = source.read_bytes()
    calls = []
    class Owner:
        def call(self, fn):
            return fn()
    s.co._owner = Owner()
    def capture_memory(coordinator, handle, process_id, recipe):
        calls.append((handle, process_id))
        active_source = source
        if len(calls) > 1:
            active_source = source.with_name("second-maintained-source.png")
            Image.new("RGB", (80, 60), "red").save(active_source)
        return {"capture_id": active_source.stem, "image_path": str(active_source),
            "sha256": sha256(active_source.read_bytes()).hexdigest(), "window_identity": deepcopy(s.target),
            "window_rect": [0, 0, 80, 60], "image_size": {"width": 80, "height": 60}}, None
    monkeypatch.setattr(capture, "capture_memory_observation", capture_memory)
    transport = InstantSession(Path(__file__).resolve().parents[1], tmp_path, allow_local_input=True)
    transport.session, transport.process = tmp_path, Alive()
    write_json_snapshot(tmp_path / "report.json", {"phase": "ready"})
    def submit(request_id, command):
        command_path = tmp_path / "commands" / (request_id + ".json")
        if command_path.exists():
            assert read_json_snapshot(command_path) == command
            return transport.result(request_id)
        write_json_snapshot(command_path, command)
        result = s.runtime.control(command["request"], request_id)
        write_json_snapshot(tmp_path / "responses" / (request_id + ".json"), {
            "status": "returned", "command": deepcopy(command), "result": result})
        return transport.result(request_id)
    monkeypatch.setattr(transport, "submit", submit)
    server = build_server(transport)
    opened = client(tmp_path, server, allow_actions=True)
    events = []
    request = observe_request(s, waiting)
    async def scenario():
        await opened.run_plan("before-look-status", {"kind": "task_plan", "request": {
            "action": "status", "run_id": s.run_id}}, event_callback=events.append)
        result = await opened.run_plan("look-public", {"kind": "task_plan", "request": request}, event_callback=events.append)
        if later_observation:
            second_request = observe_request(s, result["result"], logical="manual-two")
            await opened.run_plan("look-public-second", {"kind": "task_plan", "request": second_request}, event_callback=events.append)
        repeated = await opened.run_plan("look-public-replay", {"kind": "task_plan", "request": request}, event_callback=events.append)
        image_result = await server.call_tool("instant_result", repeated["observation_image"]["arguments"])
        current = s.runtime.control({"action": "status", "run_id": s.run_id}, "direct-status")
        reviewed = await opened.run_plan("review-public", {"kind": "task_plan",
            "request": review_request(s, current, original)}, event_callback=events.append)
        return result, repeated, image_result, reviewed, current
    result, repeated, image_result, reviewed, current = asyncio.run(scenario())
    assert result["client_state"] == repeated["client_state"] == "review_required"
    assert result["result"]["manual_observation"] == repeated["result"]["manual_observation"]
    assert repeated["result"]["review_packet"] == current["review_packet"]
    assert current["review_packet"]["packet_revision"] == (2 if later_observation else 1)
    assert len(events) == (3 if later_observation else 2) and len(calls) == (2 if later_observation else 1)
    assert reviewed["client_state"] == "continue_required"
    images = [block for block in image_result.content if block.type == "image"]
    assert len(images) == 1 and base64.b64decode(images[0].data) == fresh_bytes
    delivery = json.loads(image_result.content[0].text)["image_delivery"][0]
    assert delivery["view"] == "observation" and delivery["original_action_after"] is False
    if later_observation:
        from app.execution.task_plan_observation_delivery import manual_observation_image
        replay = transport.result("look-public-replay")["result"]
        for field, replacement in (("observation_request_id", "manual-two"),
                ("frame", current["review_packet"]["latest_observation"])):
            changed = deepcopy(replay)
            changed["manual_observation"][field] = replacement
            with pytest.raises(ValueError, match="task_plan_observation_delivery_binding_invalid"):
                manual_observation_image(tmp_path, changed)
    packet = current["review_packet"]
    assert Path(packet["latest_observation"]["image_path"]).parent == tmp_path / "task-plan-observations"
    assert packet["after"]["sha256"] == sha256(original_bytes).hexdigest()
    assert len(s.co._decision_service.calls) == 1
    before_continue = [p for p in (tmp_path / "commands").glob("*.json") if read_json_snapshot(p)["kind"] != "task_plan"]
    assert len(before_continue) == 1
    s.runtime.control({"action": "continue", "run_id": s.run_id, "wait_id": waiting["wait"]["wait_id"]}, "continue-public")
    s.runtime.tick(force=True)
    input_commands = [p for p in (tmp_path / "commands").glob("*.json") if read_json_snapshot(p)["kind"] != "task_plan"]
    assert len(input_commands) == 2
    assert original.after.read_bytes() == original_bytes
    assert (tmp_path / "responses" / (original.command_id + ".json")).read_bytes() == original_receipt_bytes
