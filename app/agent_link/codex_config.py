"""Codex 兼容的 Agent Link MCP 配置渲染。"""
from __future__ import annotations

import json
from typing import Any

_ENABLED_TOOLS = (
    "agent_link_status",
    "submit_learning_batch",
    "read_learning_feedback",
    "submit_relearning_candidate",
    "search_workflow_memory",
    "get_workflow_memory",
    "search_interface_memory",
    "get_interface_memory",
    "list_interface_relearning_feedback",
    "get_interface_relearning_feedback",
    "submit_interface_relearning_candidate",
    "request_interface_membership",
    "search_workflow_projects",
    "get_workflow_project_memory",
    "start_learning_segment",
    "get_learning_segment",
    "finish_learning_segment",
    "prepare_learning_runtime",
    "get_learning_runtime",
    "cancel_learning_runtime",
    "request_learning_action",
    "get_learning_action_result",
    "observe_learning_screen",
    "submit_observed_interface_learning",
    "inspect_learning_content",
    "read_learning_content",
    "prepare_fresh_learning_runtime",
    "request_fresh_learning_action",
    "get_fresh_learning_runtime",
    "cancel_fresh_learning_runtime",
)


def _toml_string(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Codex configuration values must be strings")
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render_codex_config(configuration: dict[str, Any]) -> str:
    """将对话框字段渲染为最小 Codex TOML 配置，不改动产品设置。"""
    if not isinstance(configuration, dict):
        raise ValueError("Codex configuration must be a dictionary")
    command = _toml_string(configuration.get("command"))
    raw_args = configuration.get("args")
    env = configuration.get("env")
    if not isinstance(raw_args, list) or not isinstance(env, dict):
        raise ValueError("Codex configuration requires args and env")
    args = ", ".join(_toml_string(value) for value in raw_args)
    base_url = _toml_string(env.get("AGENT_LINK_BASE_URL"))
    token = _toml_string(env.get("AGENT_LINK_TOKEN"))
    # 名单只保留客户端可见性；服务端能力协商、范围授权与独立人工确认仍生效。
    tools = ", ".join(_toml_string(tool) for tool in _ENABLED_TOOLS)
    bundle = (
        "AGENT_LINK_ARTIFACT_BUNDLE = " + _toml_string(env["AGENT_LINK_ARTIFACT_BUNDLE"]) + "\n"
        if "AGENT_LINK_ARTIFACT_BUNDLE" in env else ""
    )
    return (
        "[mcp_servers.agent_review]\n"
        f"command = {command}\n"
        f"args = [{args}]\n"
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 240\n"
        "required = true\n"
        f"enabled_tools = [{tools}]\n\n"
        "[mcp_servers.agent_review.env]\n"
        f"AGENT_LINK_BASE_URL = {base_url}\n"
        f"AGENT_LINK_TOKEN = {token}\n"
        f"{bundle}"
    )
