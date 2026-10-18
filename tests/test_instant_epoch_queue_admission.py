"""恢复准入未完成时，公开入队必须保留空宿主及原请求。"""
import asyncio
import json

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.execution.session_epoch_admission import SessionEpochAdmission
from app.instant_mcp import build_server
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes


def incomplete_admission(scene, monkeypatch):
    original = SessionEpochAdmission._ready
    monkeypatch.setattr(SessionEpochAdmission, "_ready", lambda self, record: False)
    preview = scene.manager.preview_recovery()
    result = scene.manager.recover_session("delayed-admission", preview["preview_sha256"])
    monkeypatch.setattr(SessionEpochAdmission, "_ready", original)
    assert result["host_alive"] is True and result["phase"] == "ready"
    assert result["recovery_admission"]["phase"] == "pointer_published"
    assert result["recovery_admission"]["new_epoch_ready"] is False
    return preview


@pytest.mark.parametrize("tool", ["instant_submit", "instant_run"])
@pytest.mark.parametrize("command", [
    {"kind": "select", "handle": 123, "process_id": 456},
    {"kind": "capture"},
    {"kind": "step", "operation": "execute_recognition_plan",
     "request": {"goal": "Open the current test folder"}},
])
def test_host_ready_does_not_admit_commands_before_epoch_ready(epoch_scene, monkeypatch, tool, command):
    scene = epoch_scene
    preview = incomplete_admission(scene, monkeypatch)
    old = old_bytes(scene)
    arguments = {"request_id": "before-admission-ready", "command": command}
    if tool == "instant_run":
        arguments.update(wait_ms=0, images="none")
    reply = asyncio.run(build_server(scene.manager).call_tool(tool, arguments))
    value = reply.structured_content
    assert reply.is_error
    assert value["status"] == "state_rejected" and value["accepted"] is False
    assert value["action_executed"] is False and value["automatic_retry_allowed"] is False
    assert value["error"]["code"] == "recovery_admission_not_ready"
    assert value["next"] == {"tool": "instant_recover_session", "arguments": {
        "request_id": "delayed-admission", "preview_sha256": preview["preview_sha256"]}}
    assert not list((scene.manager.session / "commands").glob("*.json"))
    assert old_bytes(scene) == old and len(scene.launches) == 1


def test_same_admission_becomes_ready_before_a_new_command(epoch_scene, monkeypatch):
    scene = epoch_scene
    preview = incomplete_admission(scene, monkeypatch)
    server = build_server(scene.manager)
    rejected = asyncio.run(server.call_tool("instant_submit", {
        "request_id": "not-yet-ready", "command": {"kind": "capture"}}))
    assert rejected.is_error
    ready = asyncio.run(server.call_tool("instant_recover_session", rejected.structured_content["next"]["arguments"]))
    assert not ready.is_error
    assert ready.structured_content["recovery_admission"]["phase"] == "ready"
    assert ready.structured_content["recovery_admission"]["new_epoch_ready"] is True
    accepted = asyncio.run(server.call_tool("instant_submit", {
        "request_id": "after-ready", "command": {"kind": "capture"}}))
    assert not accepted.is_error and accepted.structured_content["status"] == "pending"
    assert len(scene.launches) == 1
    assert [p.stem for p in (scene.manager.session / "commands").glob("*.json")] == ["after-ready"]


def test_original_receipt_reread_does_not_consume_or_restart_host(epoch_scene, monkeypatch):
    scene = epoch_scene
    incomplete_admission(scene, monkeypatch)
    command = {"kind": "select", "handle": 123, "process_id": 456}
    cp = scene.manager.session / "commands" / "original-accepted.json"
    rp = scene.manager.session / "responses" / "original-accepted.json"
    write_json_snapshot(cp, command)
    write_json_snapshot(rp, {"status": "returned", "command": command, "result": {"status": "focused"}})
    before = (cp.read_bytes(), rp.read_bytes())
    response = asyncio.run(build_server(scene.manager).call_tool("instant_submit", {
        "request_id": "original-accepted", "command": command}))
    assert not response.is_error and response.structured_content["status"] == "returned"
    assert (cp.read_bytes(), rp.read_bytes()) == before and len(scene.launches) == 1
    assert len(list((scene.manager.session / "commands").glob("*.json"))) == 1


@pytest.mark.parametrize("invalid_field", ["preview_sha256", "new_session_name"])
def test_invalid_current_admission_rejects_before_queue(epoch_scene, monkeypatch, invalid_field):
    scene = epoch_scene
    incomplete_admission(scene, monkeypatch)
    path = scene.manager.data_root / "recovery-admissions" / "delayed-admission.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record[invalid_field] = ("f" * 64 if invalid_field == "preview_sha256"
                             else "session-" + "f" * 32)
    write_json_snapshot(path, record)
    response = asyncio.run(build_server(scene.manager).call_tool("instant_submit", {
        "request_id": "invalid-current-admission", "command": {"kind": "capture"}}))
    assert response.is_error
    assert response.structured_content["error"]["code"] == "recovery_admission_invalid"
    assert response.structured_content["accepted"] is False
    assert not list((scene.manager.session / "commands").glob("*.json"))


def test_ready_current_epoch_does_not_use_another_epoch_record(epoch_scene):
    scene = epoch_scene
    preview = scene.manager.preview_recovery()
    scene.manager.recover_session("ready-current", preview["preview_sha256"])
    directory = scene.manager.data_root / "recovery-admissions"
    record = json.loads((directory / "ready-current.json").read_text(encoding="utf-8"))
    record.update(request_id="another-epoch", new_session_name="session-" + "e" * 32,
                  phase="pointer_published", new_host_identity={"pid": 900999, "created": 900.125})
    write_json_snapshot(directory / "another-epoch.json", record)
    response = asyncio.run(build_server(scene.manager).call_tool("instant_submit", {
        "request_id": "current-epoch-only", "command": {"kind": "capture"}}))
    assert not response.is_error and response.structured_content["status"] == "pending"
