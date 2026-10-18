"""描述已载入的任务定义，不判定运行效果或执行资格。"""
from __future__ import annotations


def summarize_definition(snapshot: dict) -> dict:
    """计数使用载入快照，编辑草稿和实际运行证据另行处理。"""
    steps = snapshot["definition"]["steps"]
    applicable = [step for step in steps if step["action"]["kind"] in {"click", "input_sequence"}]
    return {
        "saved": snapshot.get("program_id") is not None,
        "total_steps": len(steps),
        "reviewed_steps": sum(step["review_status"] == "reviewed" for step in steps),
        "pending_steps": sum(step["review_status"] == "pending" for step in steps),
        "target_memory_steps": sum("target_memory" in step["action"] for step in applicable),
        "target_applicable_steps": len(applicable),
        "verification_rule_steps": sum(bool(step.get("verification")) and (
            step["verification"]["kind"] != "agent_judgment" or bool(step["verification"].get("image_check"))) for step in steps),
        "image_check_steps": sum((step.get("verification") or {}).get("kind") == "agent_judgment"
            and bool((step.get("verification") or {}).get("image_check")) for step in steps),
        "agent_judgment_steps": sum((step.get("verification") or {}).get("kind") == "agent_judgment" for step in steps),
    }
