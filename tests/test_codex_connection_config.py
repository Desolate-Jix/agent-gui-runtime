from __future__ import annotations

import copy
import json
import sys
import tomllib

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.agent_link.codex_config import render_codex_config
from app.desktop_review.connection_dialog import ConnectionManagerDialog
from app.desktop_review.window import ensure_application
from test_desktop_relearn_window import _wait


_NATIVE_AGENT_TOOLS = [
    "agent_link_status", "submit_learning_batch", "read_learning_feedback",
    "submit_relearning_candidate", "search_workflow_memory", "get_workflow_memory",
    "search_interface_memory", "get_interface_memory", "request_interface_membership",
    "search_workflow_projects", "get_workflow_project_memory",
    "start_learning_segment", "get_learning_segment", "finish_learning_segment",
    "prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime",
    "request_learning_action", "get_learning_action_result",
    "observe_learning_screen", "submit_observed_interface_learning", "prepare_fresh_learning_runtime",
    "request_fresh_learning_action", "get_fresh_learning_runtime",
    "cancel_fresh_learning_runtime",
]


class _Connections:
    def __init__(self):
        self.records = []
        self.host = {
            "contract_version": "native_review_host_v1",
            "host_id": "host-test",
            "phase": "ready",
            "base_url": "http://127.0.0.1:49123",
            "staging_only": True,
        }

    def host_status(self):
        return copy.deepcopy(self.host)

    def list_connections(self):
        return copy.deepcopy(self.records)

    def create_connection(self, task_id, agent_name):
        self.records.append({"connection_id": "connection-new", "task_id": task_id, "agent_name": agent_name, "revoked": False, "created_at": 1})
        return {
            "contract_version": "agent_link_v1",
            "connection_id": "connection-new",
            "task_id": task_id,
            "agent_name": agent_name,
            "token": "synthetic-agent-secret-123456",
            "staging_only": True,
        }


def _ready():
    application = ensure_application()
    dialog = ConnectionManagerDialog(_Connections())
    dialog.show()
    _wait(lambda: dialog.snapshot is not None and not dialog._jobs)
    return application, dialog


def _create(dialog):
    dialog.task_id.setText("task-native")
    dialog.agent_name.setText("合成 MCP 客户端")
    QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    _wait(lambda: not dialog._jobs)


def _close(dialog):
    dialog.clear_secret()
    dialog.close()
    ensure_application().processEvents()


def test_render_codex_config_round_trips_windows_chinese_and_controls():
    rendered = render_codex_config({
        "command": "C:\\Python\\python.exe",
        "args": ["C:\\工作目录\\start \"agent\".py", "line\nnext\t\u0001"],
        "env": {
            "AGENT_LINK_BASE_URL": "http://127.0.0.1:49123",
            "AGENT_LINK_TOKEN": "令牌\"\n\u0001",
        },
    })
    parsed = tomllib.loads(rendered)
    server = parsed["mcp_servers"]["agent_review"]
    assert server["command"] == "C:\\Python\\python.exe"
    assert server["args"] == ["C:\\工作目录\\start \"agent\".py", "line\nnext\t\u0001"]
    assert server["env"] == {
        "AGENT_LINK_BASE_URL": "http://127.0.0.1:49123",
        "AGENT_LINK_TOKEN": "令牌\"\n\u0001",
    }
    assert server["enabled_tools"] == _NATIVE_AGENT_TOOLS
    assert server["startup_timeout_sec"] == 30
    assert 180 < server["tool_timeout_sec"] <= 300
    assert server["required"] is True
    assert set(parsed) == {"mcp_servers"}
    assert set(server) == {"command", "args", "env", "enabled_tools", "required",
                           "startup_timeout_sec", "tool_timeout_sec"}
    assert "default_tools_approval_mode" not in server
    assert "tools" not in server


def test_dialog_defaults_to_masked_codex_preview_and_copies_only_on_explicit_action():
    application, dialog = _ready()
    try:
        _create(dialog)
        assert dialog.config_format.currentText() == "Codex (TOML)"
        assert any("Codex" in label.text() and "批准" in label.text() for label in dialog.findChildren(type(dialog.host_label)))
        preview = dialog.config_preview.toPlainText()
        assert "[mcp_servers.agent_review]" in preview
        assert "synthetic-agent-secret" not in preview
        assert "<本连接密钥已隐藏>" in preview
        assert QApplication.clipboard().text() != preview
        QTest.mouseClick(dialog.copy_config_button, Qt.MouseButton.LeftButton)
        copied_codex = tomllib.loads(QApplication.clipboard().text())
        assert copied_codex["mcp_servers"]["agent_review"]["env"]["AGENT_LINK_TOKEN"] == "synthetic-agent-secret-123456"
        assert copied_codex["mcp_servers"]["agent_review"]["enabled_tools"] == _NATIVE_AGENT_TOOLS
        dialog.config_format.setCurrentText("通用 STDIO MCP (JSON)")
        assert json.loads(dialog.config_preview.toPlainText())["env"]["AGENT_LINK_TOKEN"] == "<本连接密钥已隐藏>"
        QTest.mouseClick(dialog.copy_config_button, Qt.MouseButton.LeftButton)
        copied = json.loads(QApplication.clipboard().text())
        assert copied["env"]["AGENT_LINK_TOKEN"] == "synthetic-agent-secret-123456"
    finally:
        QApplication.clipboard().clear()
        _close(dialog)


def test_explicit_artifact_bundle_is_preserved_without_forwarding_other_environment():
    rendered = render_codex_config({
        "command": "C:\\Python\\python.exe",
        "args": ["D:\\runtime\\scripts\\start_agent_link_mcp.py"],
        "env": {
            "AGENT_LINK_BASE_URL": "http://127.0.0.1:49123",
            "AGENT_LINK_TOKEN": "synthetic-agent-secret-123456",
            "AGENT_LINK_ARTIFACT_BUNDLE": "D:\\审核截图\\bundle.json",
            "AGENT_LINK_REVIEWER_TOKEN": "must-not-forward",
        },
    })
    env = tomllib.loads(rendered)["mcp_servers"]["agent_review"]["env"]
    assert env["AGENT_LINK_ARTIFACT_BUNDLE"] == "D:\\审核截图\\bundle.json"
    assert "AGENT_LINK_REVIEWER_TOKEN" not in env
    assert "must-not-forward" not in rendered


def test_native_tool_deadline_outlasts_the_bridge_model_request_deadline():
    config = tomllib.loads(render_codex_config({
        "command": "python.exe", "args": ["bridge.py"],
        "env": {"AGENT_LINK_BASE_URL": "http://127.0.0.1:49123",
                "AGENT_LINK_TOKEN": "synthetic-agent-secret-123456"},
    }))["mcp_servers"]["agent_review"]
    # 模型读取在桥内最多等待 180 秒，客户端不能先在第 30 秒掐断。
    assert 180 < config["tool_timeout_sec"] <= 300
    assert config["startup_timeout_sec"] == 30


def test_frozen_dialog_exports_relocated_bridge_without_development_python(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "AgentReview.exe"))
    application, dialog = _ready()
    try:
        _create(dialog)
        QTest.mouseClick(dialog.copy_config_button, Qt.MouseButton.LeftButton)
        config = tomllib.loads(QApplication.clipboard().text())["mcp_servers"]["agent_review"]
        assert config["command"] == str(tmp_path / "AgentReviewBridge.exe")
        assert config["args"] == ["--agent-link-mcp"]
        assert config["enabled_tools"] == _NATIVE_AGENT_TOOLS
        assert "tools" not in config
        assert "default_tools_approval_mode" not in config
        assert "synthetic-agent-secret" not in dialog.config_preview.toPlainText()
    finally:
        QApplication.clipboard().clear()
        _close(dialog)
