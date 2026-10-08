"""活动视觉命令期间允许读取和控制原任务，不接纳竞争请求。"""

_SAFE_KINDS = {
    "close", "agent_command_status", "agent_command_continue", "agent_command_cancel",
    "grounding_resolve", "grounding_status", "grounding_cancel",
}
_WORKFLOW_CONTROLS = {
    "status", "cancel", "continue", "review", "verify", "takeover_preview", "takeover_commit",
}


def requires_idle_agent(kind, command=None):
    if (kind == "task_plan" and isinstance(command, dict)
            and (command.get("request") or {}).get("action") in {"status", "cancel", "continue", "review"}):
        return False
    if (kind == "learning_workflow" and isinstance(command, dict)
            and (command.get("request") or {}).get("action") in _WORKFLOW_CONTROLS):
        return False
    return kind not in _SAFE_KINDS
