from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


def test_bridge_command_switches_to_relocated_companion_when_frozen(tmp_path, monkeypatch):
    from app.desktop_review.launch_paths import agent_bridge_command

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    command = agent_bridge_command()
    assert command["command"] == sys.executable
    assert Path(command["args"][0]).name == "start_agent_review.py"
    assert command["args"][1:] == ["--agent-link-mcp"]
    assert Path(command["args"][0]).is_file()
    monkeypatch.setattr(sys, "frozen", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "AgentReview.exe"))
    assert agent_bridge_command() == {"command": str(tmp_path / "AgentReviewBridge.exe"), "args": ["--agent-link-mcp"]}


def test_default_user_data_is_separate_from_installation_and_working_directory(tmp_path, monkeypatch):
    from app.desktop_review.entrypoint import gui_arguments

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    assert gui_arguments(None) == ["--state-path", str(tmp_path / "local-appdata/AgentGuiRuntime/inbox.json"), "--review-root", str(tmp_path / "local-appdata/AgentGuiRuntime/reviews"), "--listen-port", "0", "--vision-config", str(tmp_path / "local-appdata/AgentGuiRuntime/configs/vision.json")]
    explicit = tmp_path / "chosen"
    assert gui_arguments(explicit)[1] == str(explicit / "inbox.json")
    assert not explicit.exists()


def test_mcp_entry_never_launches_native_gui(monkeypatch):
    from app.desktop_review import entrypoint
    from app.agent_link import mcp_bridge

    calls = []
    monkeypatch.setattr(mcp_bridge, "run_stdio", lambda: calls.append("mcp"))
    monkeypatch.setattr(entrypoint, "_launch_gui", lambda args: pytest.fail("MCP must not launch GUI"))
    assert entrypoint.main(["--agent-link-mcp"]) == 0
    assert calls == ["mcp"]


def test_gui_entry_forwards_to_existing_native_runtime_launcher(tmp_path, monkeypatch):
    from app.desktop_review import entrypoint

    calls = []
    monkeypatch.setattr(entrypoint, "_launch_gui", lambda args: calls.append(args) or 0)
    assert entrypoint.main(["--data-dir", str(tmp_path / "chosen")]) == 0
    assert calls == [["--state-path", str(tmp_path / "chosen/inbox.json"), "--review-root", str(tmp_path / "chosen/reviews"), "--listen-port", "0", "--vision-config", str(tmp_path / "chosen/configs/vision.json")]]


def test_diagnostics_reports_actual_metadata_without_constructing_runtime(monkeypatch, capsys):
    from app.desktop_review import entrypoint

    monkeypatch.setattr(entrypoint, "_launch_gui", lambda args: pytest.fail("diagnostics must not launch GUI"))
    assert entrypoint.main(["--diagnostics", "--profile", "agent_bridge"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["contract_version"] == "native_environment_metadata_v1"
    assert output["profile"] == "agent_bridge"
    assert output["status"] == "metadata_present_unverified"
    assert output["runtime_verified"] is False
    assert output["model_assets_checked"] is False


@pytest.mark.parametrize("arguments", [["--agent-link-mcp", "--diagnostics"], ["--agent-link-mcp", "--data-dir", "never-created"], ["--diagnostics", "--data-dir", "never-created"], ["--profile", "agent_bridge"]])
def test_invalid_or_mixed_modes_fail_before_launch(arguments, monkeypatch):
    from app.desktop_review import entrypoint

    monkeypatch.setattr(entrypoint, "_launch_gui", lambda args: pytest.fail("invalid input must not launch GUI"))
    with pytest.raises(SystemExit) as error:
        entrypoint.main(arguments)
    assert error.value.code == 2


def test_gui_failure_reports_type_without_exposing_private_exception(tmp_path, monkeypatch):
    from app.desktop_review import entrypoint

    def fail(args):
        raise RuntimeError("private-token-must-not-appear")

    errors = []
    monkeypatch.setattr(entrypoint, "_launch_gui", fail)
    monkeypatch.setattr(entrypoint, "_show_startup_error", errors.append)
    assert entrypoint.main(["--data-dir", str(tmp_path / "data")]) == 2
    assert errors == ["RuntimeError"]


def test_missing_mcp_streams_fail_instead_of_opening_ui(monkeypatch):
    from app.desktop_review import entrypoint

    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(entrypoint, "_launch_gui", lambda args: pytest.fail("missing streams must not launch GUI"))
    with pytest.raises(RuntimeError, match="STDIO"):
        entrypoint.main(["--agent-link-mcp"])
