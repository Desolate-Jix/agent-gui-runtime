"""区分学习材料与已整理界面，并只读定位所属学习流程。"""
from __future__ import annotations

from copy import deepcopy
from app.agent_link.contracts import AgentLinkError


def annotate_learning_content(facade, snapshot: dict) -> dict:
    result = deepcopy(snapshot)
    result.pop("learning_flow", None)
    result.pop("learning_context_error", None)
    result["learning_status"] = "interface_content"
    source = snapshot.get("source", {})
    store = getattr(getattr(facade, "_service", None), "_store", None)
    if store is None or not isinstance(source, dict):
        return result

    def read_context(state):
        batch = state.get("batches", {}).get(source.get("batch_id"), {})
        fresh = batch.get("fresh_learning_source")
        if not isinstance(fresh, dict) or batch.get("task_id") != source.get("task_id"):
            return None
        connection = state.get("connections", {}).get(fresh.get("connection_id"), {})
        segment = connection.get("learning_segments", {}).get(fresh.get("segment_id"), {})
        observations = segment.get("observations", [])
        if (connection.get("task_id") != source.get("task_id") or not observations
                or not any(item.get("batch_id") == source.get("batch_id")
                           and item.get("source") == fresh for item in observations)):
            return None
        return {"anchor": observations[0]["batch_id"], "segment_id": fresh["segment_id"],
                "title": segment.get("title", "学习流程"), "segment_status": segment.get("status")}

    try:
        context = store.read(read_context)
    except AgentLinkError as error:
        if error.code != "store_closed":
            raise
        # 历史内容允许离线查看，但不能把不可查询的来源猜成已完成学习。
        result["learning_status"] = "source_unavailable"
        result["learning_context_error"] = error.code
        return result
    if context is None:
        return result
    # 截图落盘只是原始观察；不能因为保存成功就冒充完成了界面学习。
    if snapshot.get("revision") == 1 and not snapshot.get("content", {}).get("regions"):
        result["learning_status"] = "observation_only"
    result["learning_flow"] = {
        "logical_workflow_id": "workflow-" + facade._workspace_key(source["task_id"], context["anchor"]),
        "title": context["title"], "segment_id": context["segment_id"],
        "segment_status": context["segment_status"], "status": "recorded_not_verified",
        "artifact_is_authorization": False,
    }
    return result


def is_observation_only(facade, snapshot: dict) -> bool:
    return annotate_learning_content(facade, snapshot)["learning_status"] == "observation_only"


def learning_project_notice(snapshot: dict) -> str:
    graph = snapshot.get("graph", {})
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    if not nodes:
        return ""
    if not edges:
        return "已收集界面材料，尚未记录跳转；不是已跑通的流程。输入值属于步骤参数，输入前后截图不代表两个独立界面。"
    return "当前是可修改的流程记忆，存在连线不代表整段已验证；人工补充的关系仍需实测。输入值属于步骤参数，操作前后截图是证据，不代表新增界面。"
