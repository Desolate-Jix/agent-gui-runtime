from __future__ import annotations

import tomllib

from app.agent_link.codex_config import _ENABLED_TOOLS, render_codex_config


LIVING_MEMORY_TOOLS = {
    "search_interface_memory",
    "get_interface_memory",
    "request_interface_membership",
    "search_workflow_projects",
    "get_workflow_project_memory",
}
ORIGINAL_NATIVE_TOOLS = {
    "agent_link_status", "submit_learning_batch", "read_learning_feedback",
    "submit_relearning_candidate", "search_workflow_memory", "get_workflow_memory",
    "start_learning_segment", "get_learning_segment", "finish_learning_segment",
    "prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime",
    "request_learning_action", "get_learning_action_result", "observe_learning_screen",
    "prepare_fresh_learning_runtime", "request_fresh_learning_action",
    "get_fresh_learning_runtime", "cancel_fresh_learning_runtime",
}


def _config() -> dict:
    return tomllib.loads(render_codex_config({
        "command": "python.exe",
        "args": ["bridge.py"],
        "env": {
            "AGENT_LINK_BASE_URL": "http://127.0.0.1:49123",
            "AGENT_LINK_TOKEN": "isolated-token",
        },
    }))['mcp_servers']['agent_review']


def test_codex_export_exposes_living_interface_and_project_memory_tools():
    config = _config()
    assert LIVING_MEMORY_TOOLS <= set(config["enabled_tools"])
    assert ORIGINAL_NATIVE_TOOLS <= set(config["enabled_tools"])
    assert set(_ENABLED_TOOLS) <= set(config["enabled_tools"])
    assert len(config["enabled_tools"]) == len(set(config["enabled_tools"]))


def test_codex_export_has_no_approval_or_global_configuration_changes():
    config = _config()
    assert "approval_mode" not in config
    assert "default_tools_approval_mode" not in config
    assert "tools" not in config
    assert set(config) == {
        "command", "args", "env", "enabled_tools", "required",
        "startup_timeout_sec", "tool_timeout_sec",
    }
