"""新会话被旧会话阻止时，仍返回结构化错误且保留恢复证据。"""

import asyncio
import json

import pytest

from app.instant_mcp import InstantSession, build_server, write_json


@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("cleanup_verified,pending", [(False, False), (True, True), (False, True)])
def test_new_session_rejection_preserves_previous_session(tmp_path, reconnect, cleanup_verified, pending):
    directory = tmp_path / ("session-" + "a" * 32)
    (directory / "commands").mkdir(parents=True)
    (directory / "responses").mkdir()
    write_json(directory / "report.json", {
        "phase": "stopped", "host_phase": "stopped", "finished_at": "then",
        "cleanup_errors": [] if cleanup_verified else [{"operation": "shutdown"}],
        "sampler_stopped": True,
    })
    if pending:
        write_json(directory / "commands/prior.json", {"kind": "capture"})
    pointer = tmp_path / "latest-session.json"
    write_json(pointer, {"name": directory.name, "host_identity": None})
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    session = InstantSession(tmp_path, tmp_path, tmp_path, allow_local_input=True)
    if not reconnect:
        session.session = directory
    server = build_server(session)
    try:
        for _ in range(2):
            result = asyncio.run(server.call_tool("instant_start", {"new_session": True}))
            value = json.loads(result.content[0].text)
            assert result.is_error
            assert value["status"] == "start_rejected"
            assert value["error"]["code"] == "previous_session_not_resolved"
            assert value["host_launch_attempted"] is False
            assert value["automatic_retry_allowed"] is False
            assert "instant_status" in value["next"]
            assert "instant_result" in value["next"]
            assert session.session == directory
            assert session.process is None
            assert list(tmp_path.glob("session-*")) == [directory]
            assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == before
        logs = [json.loads(line) for line in (tmp_path / "startup-errors.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(logs) == 2
        assert all(log["error"]["code"] == "previous_session_not_resolved" for log in logs)
        reattached = asyncio.run(server.call_tool("instant_start", {}))
        assert not reattached.is_error
        status = json.loads(reattached.content[0].text)
        assert status["cleanup_verified"] is cleanup_verified
        assert status["pending_ids"] == (["prior"] if pending else [])
    finally:
        if session.lock_file:
            session.lock_file.close()
