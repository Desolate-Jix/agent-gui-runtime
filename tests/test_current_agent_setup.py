"""Current-agent setup is a local selection, without service calls or global writes."""
import json
import os
from pathlib import Path
import sys
import tomllib
from unittest.mock import patch

import pytest

from scripts import configure_instant_mcp


def configure(monkeypatch, tmp_path, *options):
    bundle = tmp_path / "bundle"
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    entry = bundle / "scripts" / "configure_instant_mcp.py"
    monkeypatch.setattr(configure_instant_mcp, "__file__", str(entry))
    monkeypatch.setattr(sys, "argv", [str(entry), "--python", sys.executable,
        "--data-dir", str(tmp_path / "data"), *options])
    configure_instant_mcp.main()
    return bundle


@pytest.mark.parametrize("source_args", [(), ("--recognition-source", "agent_current")])
def test_current_agent_generates_matching_local_configs_without_credentials(monkeypatch, tmp_path, source_args):
    monkeypatch.setenv("OPENAI_API_KEY", "current-agent-secret-not-for-output")
    bundle = configure(monkeypatch, tmp_path, "--current-agent", *source_args)
    raw = (bundle / "mcp-config.local.json").read_text(encoding="utf-8")
    server = json.loads(raw)["mcpServers"]["agent-review-instant"]
    arguments = server["args"]
    assert arguments == [str(bundle / "scripts" / "start_instant_mcp.py"),
        "--data-dir", str(tmp_path / "data"), "--recognition-source", "agent_current"]
    assert "current-agent-secret-not-for-output" not in raw
    assert server["env"] == {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "AGENT_GUI_DECISION_PROFILE": ""}
    toml = tomllib.loads((bundle / "mcp-config.local.toml").read_text(encoding="utf-8"))
    assert toml["mcp_servers"]["agent-review-instant"]["args"] == arguments
    assert toml["mcp_servers"]["agent-review-instant"]["env"] == server["env"]
    assert not (tmp_path / "data").exists()
    assert sorted(path.name for path in bundle.iterdir()) == [
        "mcp-config.local.json", "mcp-config.local.toml", "scripts"]


@pytest.mark.parametrize("option", ["--model-directory", "--api-profile", "--decision-profile", "--delegate-profile"])
def test_current_agent_rejects_service_and_model_options_before_output(monkeypatch, tmp_path, capsys, option):
    with pytest.raises(SystemExit) as failure:
        configure(monkeypatch, tmp_path, "--current-agent", option, "not-loaded")
    assert failure.value.code == 2
    assert "--current-agent cannot be combined" in capsys.readouterr().err
    assert not (tmp_path / "bundle" / "mcp-config.local.json").exists()
    assert not (tmp_path / "bundle" / "mcp-config.local.toml").exists()


@pytest.mark.parametrize("source", ["local", "external_api", "agent_delegate"])
def test_current_agent_rejects_an_explicit_different_route(monkeypatch, tmp_path, capsys, source):
    with pytest.raises(SystemExit) as failure:
        configure(monkeypatch, tmp_path, "--current-agent", "--recognition-source", source)
    assert failure.value.code == 2
    assert "--current-agent conflicts" in capsys.readouterr().err
    assert not (tmp_path / "bundle" / "mcp-config.local.json").exists()


def test_current_agent_preserves_explicit_host_input_option(monkeypatch, tmp_path):
    bundle = configure(monkeypatch, tmp_path, "--current-agent", "--enable-local-input")
    arguments = json.loads((bundle / "mcp-config.local.json").read_text(encoding="utf-8"))[
        "mcpServers"]["agent-review-instant"]["args"]
    assert Path(arguments[0]).name == "start_instant_mcp.py"
    assert arguments[-1] == "--allow-local-input"
    assert "vision_capabilities" not in " ".join(arguments)


def test_current_agent_rejects_administrator_before_generating_config(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as failure:
        configure(monkeypatch, tmp_path, "--current-agent", "--administrator")
    assert failure.value.code == 2
    assert "does not support --administrator" in capsys.readouterr().err
    assert not (tmp_path / "bundle" / "mcp-config.local.json").exists()
    assert not (tmp_path / "bundle" / "mcp-config.local.toml").exists()


def ambient_decision_profile(tmp_path):
    profile = tmp_path / "ambient-decision.json"
    profile.write_text(json.dumps({"contract_version": "decision_profile.v1", "mode": "shadow"}),
        encoding="utf-8")
    return profile.resolve()


@pytest.mark.parametrize("format_name", ["json", "toml"])
def test_generated_current_agent_environment_disables_effective_decision_loading(monkeypatch, tmp_path, format_name):
    from app.core.decision_configuration import create_session_decision_service
    from app.instant_mcp import InstantSession

    ambient = ambient_decision_profile(tmp_path)
    monkeypatch.setenv("AGENT_GUI_DECISION_PROFILE", str(ambient))
    inherited = InstantSession(tmp_path, tmp_path / "inherited", recognition_source="agent_current")
    assert inherited.decision_profile == str(ambient)
    bundle = configure(monkeypatch, tmp_path, "--current-agent")
    if format_name == "json":
        server = json.loads((bundle / "mcp-config.local.json").read_text(encoding="utf-8"))[
            "mcpServers"]["agent-review-instant"]
    else:
        server = tomllib.loads((bundle / "mcp-config.local.toml").read_text(encoding="utf-8"))[
            "mcp_servers"]["agent-review-instant"]
    environment = {**os.environ, **server["env"]}
    with patch.dict(os.environ, environment, clear=True):
        session = InstantSession(bundle, tmp_path / "current-session", recognition_source="agent_current",
            allow_local_input=True)
        assert session.decision_profile is None
        assert session._startup_configuration().source == "agent_current"
        service = create_session_decision_service(tmp_path / "current-host")
        try:
            assert service.enabled is False and service.adoption_mode == "off"
            assert not (tmp_path / "current-host" / "decision-profile.snapshot.json").exists()
        finally:
            service.close()
    assert os.environ["AGENT_GUI_DECISION_PROFILE"] == str(ambient)
    assert not (tmp_path / "current-session").exists()


def test_legacy_agent_configuration_preserves_ambient_decision_loading(monkeypatch, tmp_path):
    from app.instant_mcp import InstantSession
    from app.judgment.service import DecisionService

    ambient = ambient_decision_profile(tmp_path)
    monkeypatch.setenv("AGENT_GUI_DECISION_PROFILE", str(ambient))
    bundle = configure(monkeypatch, tmp_path, "--recognition-source", "agent_current", "--administrator")
    server = json.loads((bundle / "mcp-config.local.json").read_text(encoding="utf-8"))[
        "mcpServers"]["agent-review-instant"]
    toml = tomllib.loads((bundle / "mcp-config.local.toml").read_text(encoding="utf-8"))[
        "mcp_servers"]["agent-review-instant"]
    assert server["env"] == toml["env"] == {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    assert Path(server["args"][0]).name == "start_instant_mcp_admin.py"
    with patch.dict(os.environ, {**os.environ, **server["env"]}, clear=True):
        session = InstantSession(bundle, tmp_path / "legacy-session", recognition_source="agent_current")
        assert session.decision_profile == str(ambient)
        service = DecisionService.from_environment(tmp_path / "legacy-host")
        try:
            assert service.enabled is True and service.adoption_mode == "shadow"
        finally:
            service.close()


def test_omitted_mode_keeps_local_default_and_model_requirement(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as failure:
        configure(monkeypatch, tmp_path)
    assert failure.value.code == 2
    assert "local recognition requires an existing model directory" in capsys.readouterr().err
    assert not (tmp_path / "bundle" / "mcp-config.local.json").exists()
