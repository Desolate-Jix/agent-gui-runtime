"""MCP 识别交接使用真实协议与文件快照，不在契约测试中操作桌面。"""
import asyncio
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from app.instant_mcp import InstantCommand, InstantSession, build_server, write_json


def prepare_command():
    return {"kind": "grounding_prepare", "request": {"goal": "Search",
        "configuration": {"source": "agent_current"},
        "capabilities": {"image_transport": "supported", "current_vision": "supported"}}}


def test_mcp_admits_explicit_grounding_command_without_action():
    command = prepare_command()
    assert InstantCommand.model_validate(command).command() == command


@pytest.mark.parametrize("change", [{"operation": "press_key"}, {"observation_wait_ms": 1}])
def test_grounding_command_does_not_accept_action_fields(change):
    with pytest.raises(ValueError):
        InstantCommand.model_validate({**prepare_command(), **change}).command()


def test_grounding_prepare_rejects_unknown_request_fields():
    command = prepare_command()
    command["request"]["execute"] = True
    with pytest.raises(ValueError):
        InstantCommand.model_validate(command).command()


def test_host_handoff_and_real_mcp_receipt_keep_image_and_null_verification(tmp_path):
    from app.vision.grounding_handoff import GroundingHandoffStore
    from scripts.run_local_step_session import run_grounding_command
    frame = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "white").save(frame)
    capture = {"image_path": str(frame), "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
        "window_identity": {"handle": 12, "process_id": 34, "process_create_time": 100.0}}
    store = GroundingHandoffStore(tmp_path, owner_id="host-1")
    prepared, observation = run_grounding_command(store, lambda: capture, "g-1", prepare_command())
    assert prepared["phase"] == "awaiting_grounding"
    assert prepared["execution_available"] is False
    assert prepared["output_schema"]["properties"]["schema_version"]["const"] == "grounding.v1"
    assert prepared["output_schema"]["additionalProperties"] is False
    assert observation["capture_id"] == prepared["capture"]["capture_id"]

    session = InstantSession(Path(__file__).resolve().parents[1], tmp_path, tmp_path)
    session.session = tmp_path
    (tmp_path / "responses").mkdir()
    write_json(tmp_path / "responses/g-1.json", {"status": "returned",
        "result": prepared, "observation": observation})
    mcp = asyncio.run(build_server(session).call_tool("instant_result", {
        "request_id": "g-1", "detail": "compact", "images": "after"}))
    receipt = json.loads(mcp.content[0].text)
    assert receipt["task_effect_verified"] is None
    assert receipt["action_executed"] is False
    assert receipt["operation_success_scope"] == "grounding_only"
    assert any(item.type == "image" for item in mcp.content)

    payload = {"schema_version": "grounding.v1", "request_id": "g-1",
        "capture_id": observation["capture_id"], "status": "absent", "coordinate_space": "capture_image_pixels",
        "image_size": {"width": 100, "height": 80}, "candidates": [], "selected_candidate_id": None}
    resolve = {"kind": "grounding_resolve", "request": {"grounding_request_id": "g-1", "result": payload}}
    assert InstantCommand.model_validate(resolve).command() == resolve
    resolved, unchanged_image = run_grounding_command(store,
        lambda: pytest.fail("resolving must not recapture or substitute evidence"), "g-2", resolve)
    assert resolved["phase"] == "absent"
    assert unchanged_image["sha256"] == capture["sha256"]
    assert resolved["input_dispatched"] is False


def test_prepare_checks_capability_before_capturing_private_screen(tmp_path):
    from app.vision.grounding_handoff import GroundingHandoffStore, GroundingHandoffError
    from scripts.run_local_step_session import run_grounding_command
    command = prepare_command()
    command["request"]["capabilities"]["current_vision"] = "unsupported"
    with pytest.raises(GroundingHandoffError, match="vision_unsupported"):
        run_grounding_command(GroundingHandoffStore(tmp_path, owner_id="host-1"),
            lambda: pytest.fail("unavailable route must not capture"), "g-1", command)


def test_prepare_cannot_override_session_source_or_delegate_profile(tmp_path):
    from app.vision.grounding_handoff import GroundingHandoffStore, GroundingHandoffError
    from app.vision.recognition_source import RecognitionSourceConfig
    from scripts.run_local_step_session import run_grounding_command
    command = prepare_command()
    for config in (RecognitionSourceConfig(source="local"),
                   RecognitionSourceConfig(source="agent_delegate", delegate_profile="luna")):
        with pytest.raises(GroundingHandoffError, match="session_recognition_source_mismatch"):
            run_grounding_command(GroundingHandoffStore(tmp_path, owner_id="host-1"),
                lambda: pytest.fail("source mismatch must not capture"), "g-1", command,
                session_configuration=config)


def test_handoff_cancel_uses_original_id(tmp_path):
    from app.vision.grounding_handoff import GroundingHandoffStore, GroundingHandoffError
    from scripts.run_local_step_session import run_grounding_command
    command = {"kind": "grounding_cancel", "request": {"grounding_request_id": "not-created"}}
    assert InstantCommand.model_validate(command).command() == command
    with pytest.raises(GroundingHandoffError, match="request_unknown"):
        run_grounding_command(GroundingHandoffStore(tmp_path, owner_id="host-1"),
                              lambda: pytest.fail("cancel must not capture"), "cancel-1", command)


@pytest.mark.parametrize("attempted", [True, False])
def test_status_after_execution_does_not_claim_no_input(tmp_path, attempted):
    session = InstantSession(Path(__file__).resolve().parents[1], tmp_path, tmp_path)
    session.session = tmp_path
    (tmp_path / "responses").mkdir()
    write_json(tmp_path / "responses/status-1.json", {"status":"returned", "result":{
        "contract_version":"grounding_handoff.v1", "phase":"completed",
        "execution_id":"exec-1", "input_attempted":attempted,
        "input_dispatched":None if attempted else False}})
    receipt = session.result("status-1")
    assert receipt["action_executed"] is (None if attempted else False)
    assert receipt["input_attempted"] is attempted
    assert receipt["execution_request_id"] == "exec-1"
