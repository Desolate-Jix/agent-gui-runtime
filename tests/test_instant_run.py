"""真实 MCP 工具封装的等待、幂等、图片和精简输出；不启动桌面宿主。"""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import pytest
from PIL import Image

from app.instant_mcp import InstantSession, build_server, write_json
from app.instant_receipt import compact_receipt


class Alive:
    def poll(self):
        return None


@pytest.fixture
def session(tmp_path):
    session = InstantSession(Path(__file__).resolve().parents[1], tmp_path, tmp_path, allow_local_input=True)
    session.session = tmp_path / "session-test"
    for folder in ("commands", "responses"):
        (session.session / folder).mkdir(parents=True)
    write_json(session.session / "report.json", {"phase": "ready"})
    session.process = Alive()
    return session


def completed(session):
    frames = []
    for name, color in (("before", "white"), ("after", "blue")):
        path = session.session / (name + ".png")
        Image.new("RGB", (3, 2), color).save(path)
        frames.append({"image_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    command = {"kind": "step", "operation": "press_key", "request": {"key": "Enter", "x": 1, "y": 1}}
    write_json(session._path("one", "commands"), command)
    write_json(session._path("one", "responses"), {"status": "returned", "command": command,
        "result": {"contract_version": "local_direct_step_v1", "operation": "press_key", "phase": "returned",
            "capture": frames[0], "observation": {"status": "captured", "capture": frames[1]},
            "response": {"success": True, "data": {"pressed": True, "large_trace": "x" * 10000}}}})
    return command, frames


def call(session, name, arguments):
    result = asyncio.run(build_server(session).call_tool(name, arguments))
    return result, json.loads(result.content[0].text)


def test_run_retrieves_completed_id_once_with_exact_original_images(session):
    command, frames = completed(session)
    original = session._path("one", "commands").read_bytes()
    result, value = call(session, "instant_run", {"request_id": "one", "command": command, "images": "both"})
    assert not result.is_error and value["operation_succeeded"] is True
    assert value["receipt_detail"] == "compact" and "large_trace" not in result.content[0].text
    assert [hashlib.sha256(base64.b64decode(x.data)).hexdigest() for x in result.content[1:]] == [f["sha256"] for f in frames]
    assert [x["content_index"] for x in value["image_delivery"]] == [1, 2]
    assert session._path("one", "commands").read_bytes() == original


def test_wait_expiry_is_pending_not_cancel_or_replay(session):
    result, value = call(session, "instant_run", {"request_id": "one", "command": {"kind": "capture"}, "wait_ms": 0})
    assert not result.is_error and value["status"] == "pending"
    assert value["wait_expired"] is True and value["command_cancelled"] is False
    assert value["next"]["arguments"]["request_id"] == "one"
    assert len(list((session.session / "commands").glob("*.json"))) == 1


@pytest.mark.parametrize("kind,requested,expected", [
    ("form_fill", None, 45000), ("capture", None, 25000),
    ("form_fill", 0, 0), ("form_fill", 25000, 25000), ("form_fill", 120000, 120000),
])
def test_run_wait_budget_is_command_aware_and_explicit_wait_wins(kind, requested, expected):
    from app.instant_mcp import _run_wait_budget
    assert _run_wait_budget(kind, requested) == expected


@pytest.mark.parametrize("requested", [-1, 120001, True, 1.5, "45000"])
def test_run_wait_budget_rejects_invalid_values(requested):
    from app.instant_mcp import _run_wait_budget
    with pytest.raises(ValueError):
        _run_wait_budget("form_fill", requested)


def test_run_accepts_long_wait_without_replaying_completed_command(session):
    command, _ = completed(session)
    before = session._path("one", "commands").read_bytes()
    result, value = call(session, "instant_run", {
        "request_id": "one", "command": command, "wait_ms": 60000})
    assert not result.is_error and value["operation_succeeded"] is True
    assert session._path("one", "commands").read_bytes() == before


def test_invalid_sequence_reports_error_without_queuing(session):
    result, value = call(session, "instant_run", {"request_id": "bad", "command": {
        "kind": "input_sequence", "request": {"field_goal": "Search", "text": "private-value"}}})
    assert result.is_error and value["accepted"] is False
    assert "private-value" not in result.content[0].text
    assert list((session.session / "commands").glob("*.json")) == []


def test_missing_image_does_not_change_dispatched_input_outcome(session):
    command, frames = completed(session)
    Path(frames[1]["image_path"]).write_bytes(b"corrupt fixture")
    result, value = call(session, "instant_run", {"request_id": "one", "command": command})
    assert value["operation_succeeded"] is True
    assert value["image_delivery"][0]["error"]["code"] == "image_format_invalid"
    assert len(result.content) == 1


def test_original_result_default_remains_full_json(session):
    completed(session)
    result, value = call(session, "instant_result", {"request_id": "one"})
    assert len(result.content) == 1 and "large_trace" in result.content[0].text
    assert "command" not in value


def test_compact_retains_error_discovery_and_reading_without_mutating_original():
    for result in ({"windows": [{"handle": 1, "process_id": 2}]}, {"text": "Chinese: \u641c\u7d22"}):
        value = compact_receipt({"request_id": "one", "status": "returned", "result": result})
        assert value["result"] == result
    raw = {"request_id": "one", "status": "returned", "result": {
        "contract_version": "local_direct_step_v1", "response": {"success": False,
            "error": {"code": "ambiguous", "details": {"candidates": [{"text": "Maps", "bbox": [1, 2, 3, 4]}]}}}}}
    value = compact_receipt(raw)
    assert value["error"] == raw["result"]["response"]["error"]
    assert "error" not in raw


@pytest.mark.parametrize("tool", ["instant_run", "instant_submit"])
@pytest.mark.parametrize("bad_id", ["Bad-id", "../escape", "x" * 81])
def test_invalid_id_is_structured_and_connection_remains_usable(session, tool, bad_id):
    result, value = call(session, tool, {"request_id": bad_id, "command": {"kind": "capture"}})
    assert result.is_error and value["status"] == "validation_rejected"
    assert value["error"]["code"] == "invalid_request_id"
    assert value["accepted"] is False and value["action_executed"] is False
    assert list((session.session / "commands").glob("*.json")) == []
    logged = json.loads((session.session / "validation-errors.jsonl").read_text(encoding="utf-8"))
    assert logged["error"]["code"] == "invalid_request_id"
    _, next_value = call(session, "instant_run", {"request_id": "valid-next", "command": {"kind": "capture"}, "wait_ms": 0})
    assert next_value["status"] == "pending"
    assert len(list((session.session / "commands").glob("*.json"))) == 1


@pytest.mark.parametrize("contract", ["local_direct_step_v1", "input_sequence_v1"])
@pytest.mark.parametrize("stage", ["after_condition_wait", "after_render_wait"])
def test_agent_review_preserves_recorded_observation_stage(session, contract, stage):
    completed(session)
    path = session._path("one", "responses")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["result"].update(contract_version=contract, status="completed")
    raw["result"]["observation"]["capture"]["observation_stage"] = stage
    write_json(path, raw)
    _, value = call(session, "instant_result", {"request_id": "one", "detail": "compact"})
    assert value["agent_review"]["after"]["observation_stage"] == stage
    assert value["image"]["observation_stage"] == stage
