"""回环 API 的实际候选贯穿学习归档和草稿；仅隔离系统边界。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from app.core.json_snapshot import write_json_snapshot
from app.instant_mcp import InstantCommand
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash
from scripts.run_local_step_session import dispatch_agent_command
from tests.test_api_flow import api_server, flow, terminal


def test_real_api_candidate_reaches_reviewable_saved_workflow(flow, monkeypatch):
    from app.learning_memory import memory_observation
    identity = {"status": "observed", "target_window_handle": 10, "process_id": 20,
                "process_create_time": 30.0, "executable_path": "C:/fixture/editor.exe"}
    controls = [{"name": "Record desk", "control_type": "Text", "automation_id": "page-title",
                 "visible": True, "enabled": True, "runtime_id": [1],
                 "bbox": {"x": 3, "y": 3, "w": 100, "h": 20}},
                {"name": "Search", "control_type": "Button", "automation_id": "search",
                 "visible": True, "enabled": True, "runtime_id": [2],
                 "bbox": {"x": 30, "y": 40, "w": 71, "h": 31}}]
    reads = []

    def snapshot(_bound):
        reads.append(len(flow.clicks))
        return {"status": "ok", "scan_complete": True, "truncated": False, "scan_scope": "bound_window",
                "window": {"handle": 10, "process_id": 20}, "controls": deepcopy(controls)}

    monkeypatch.setattr(memory_observation, "WindowsNativeIdentityReader",
                        lambda **_: SimpleNamespace(read_identity=lambda _: deepcopy(identity)))
    monkeypatch.setattr(memory_observation, "WindowsUIAProvider",
                        lambda: SimpleNamespace(snapshot_window=snapshot))
    monkeypatch.setattr(memory_observation, "_window_class", lambda _: "Fixture")
    session = Path(flow.store.session_root)
    (session / "responses").mkdir(exist_ok=True)
    learning = LearningEventStore(session)
    started = learning.control("learning_start", {"scope": "workflow", "title": "查询记录",
        "project_id": "api-new-learning"}, "start")
    command = InstantCommand.model_validate({"kind": "step", "operation": "execute_recognition_plan",
        "request": {"goal": "Search", "enable_post_click_verification": False}}).command()
    ticket = learning.prepare("api-learn-click", command, {"handle": 10, "process_id": 20})
    learning.reserve(ticket)
    initial = dispatch_agent_command(flow.jobs, "api-learn-click", command, {"handle": 10, "process_id": 20},
        learning_context={"event_id": "api-learn-click", "command_sha256": ticket["command_sha256"]})
    state = terminal(flow.jobs, "api-learn-click")
    assert state["status"] == "completed"
    assert reads == [0] and len(flow.clicks) == 1
    write_json_snapshot(session / "responses/api-learn-click.json", {
        "status": "returned", "command": command, "learning_binding": ticket, "result": initial})
    learning.record("api-learn-click", ticket)
    event = learning.control("learning_event", {"event_id": "api-learn-click"}, "read")["event"]
    assert event["target_observation"]["kind"] == "learning_target_observation"
    assert event["before"]["capture_id"].startswith("memory-capture-")
    learning.control("learning_review", {"review": {"event_id": "api-learn-click",
        "event_sha256": content_hash(event), "verdict": "success", "reviewer": "protocol-contract",
        "reason": "隔离输入和 UIA 的协议集成，不是实机成功证明",
        "before": {"interface_key": "search", "state_key": "home", "meaning": "查询首页",
                   "frame_sha256": event["before"]["sha256"]},
        "after": {"interface_key": "search", "state_key": "results", "meaning": "查询结果",
                  "frame_sha256": event["after"]["sha256"]}}}, "review")
    learning.control("learning_stop", {}, "stop")
    draft = learning.control("learning_workflow", {"action": "compile",
        "learning_session_id": started["learning_id"]}, "compile")
    proposals = draft["proposed_target_recipes"]
    assert len(proposals) == 1 and proposals[0]["recipe"]["strategies"][0]["automation_id"] == "search"
    baseline = learning.control("learning_workflow", {"action": "read", "workflow_id": draft["workflow_id"]}, "read-program")
    saved = learning.control("learning_workflow", {"action": "save", "workflow_id": draft["workflow_id"],
        "expected_sha256": baseline["content_sha256"], "definition": draft["definition"],
        "target_recipes": [item["recipe"] for item in proposals]}, "save")
    assert saved["definition"]["steps"][0]["action"]["target_memory"] == proposals[0]["reference"]
    assert saved["definition"]["steps"][0]["review_status"] == "pending"
    assert len(flow.clicks) == 1
