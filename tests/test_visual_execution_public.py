"""公开客户端到维护队列的离线恢复；不创建宿主进程或桌面输入。"""
import asyncio
from copy import deepcopy
from pathlib import Path

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.instant_mcp import InstantSession, build_server
from tests.test_instant_mcp import Alive
from tests.test_task_plan_client import client
from tests.test_task_plan_pre_dispatch_review import intervention, reject, binding
from tests.test_point_visibility_no_dispatch import visibility_route


def test_public_client_resumes_bound_zero_input_with_new_ticket(tmp_path, monkeypatch, intervention):
    s = intervention.create(version="task_plan.v3", policy=None)
    old, original_path, original_bytes = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    transport = InstantSession(Path(__file__).resolve().parents[1], tmp_path, allow_local_input=True)
    transport.session, transport.process = tmp_path, Alive()
    write_json_snapshot(tmp_path / "report.json", {"phase": "ready", "task_plan_run": waiting})
    def submit(request_id, command):
        path = tmp_path / "commands" / (request_id + ".json")
        if path.exists():
            assert read_json_snapshot(path) == command
            return transport.result(request_id)
        write_json_snapshot(path, command)
        result = s.runtime.control(command["request"], request_id)
        write_json_snapshot(tmp_path / "responses" / (request_id + ".json"), {
            "status": "returned", "command": deepcopy(command), "result": result})
        write_json_snapshot(tmp_path / "report.json", {"phase": "ready", "task_plan_run": result})
        return transport.result(request_id)
    monkeypatch.setattr(transport, "submit", submit)
    opened = client(tmp_path, build_server(transport), allow_actions=True)
    async def scenario():
        blocked = await opened.run_plan("public-status", {"kind": "task_plan", "request": {
            "action": "status", "run_id": s.run_id}}, total_timeout=.5)
        command = {"kind": "task_plan", "request": {"action": "resume_pre_dispatch",
            **binding(waiting), "reason": "Main checked this exact harmless obstruction"}}
        resumed = await opened.run_plan("public-resume", command, total_timeout=.2)
        return blocked, resumed
    blocked, resumed = asyncio.run(scenario())
    assert blocked["client_state"] == "review_required"
    assert blocked["result"]["review_packet"]["after"] is None
    assert resumed["client_state"] == "pending", resumed
    assert resumed["result"]["active_command_id"] != old["execution_request_id"]
    assert resumed["result"]["recovery_policy"] == "intervention_v1"
    assert original_path.read_bytes() == original_bytes
    commands = [read_json_snapshot(p) for p in (tmp_path / "commands").glob("*.json")]
    inputs = [c for c in commands if c["kind"] == "step"]
    assert len(inputs) == 2
    assert inputs[-1]["action_review"]["plan"]["schema_version"] == "task_plan.v3"
