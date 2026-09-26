from pathlib import Path
import json
import sys
import tomllib

import pytest

from scripts import configure_instant_mcp, smoke_instant_mcp
from scripts.instant_admin_worker import server_command


def profile_file(path: Path) -> Path:
    path.write_text(json.dumps({
        "protocol": "chat_completions_json",
        "endpoint": "https://vision.example/v1/chat/completions",
        "model": "vision-model-explicit",
        "api_key_env": "VISION_API_KEY",
    }), encoding="utf-8")
    return path.resolve()


def run_configure(monkeypatch, tmp_path, profile):
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    monkeypatch.setattr(configure_instant_mcp, "__file__", str(scripts / "configure_instant_mcp.py"))
    args = ["configure_instant_mcp.py", "--recognition-source", "external_api",
            "--api-profile", str(profile), "--python", sys.executable,
            "--data-dir", str(tmp_path / "data")]
    monkeypatch.setattr(sys, "argv", args)
    configure_instant_mcp.main()


def test_external_api_config_emits_profile_path_without_key(monkeypatch, tmp_path):
    profile = profile_file(tmp_path / "provider-profile.json")
    run_configure(monkeypatch, tmp_path, profile)
    config = json.loads((tmp_path / "mcp-config.local.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["agent-review-instant"]
    args = server["args"]
    assert args[args.index("--recognition-source") + 1] == "external_api"
    assert args[args.index("--api-profile") + 1] == str(profile)
    assert "VISION_API_KEY" not in json.dumps(config)
    assert "api_key_env" not in json.dumps(config)
    toml = tomllib.loads((tmp_path / "mcp-config.local.toml").read_text(encoding="utf-8"))
    toml_args = toml["mcp_servers"]["agent-review-instant"]["args"]
    assert toml_args[toml_args.index("--api-profile") + 1] == str(profile)


def test_external_api_config_rejects_invalid_profile(monkeypatch, tmp_path):
    profile = tmp_path / "bad.json"
    profile.write_text('{"endpoint":"http://remote.invalid"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        run_configure(monkeypatch, tmp_path, profile.resolve())


def test_external_api_admin_command_propagates_profile_path():
    profile = Path("C:/profiles/provider.json")
    ticket = {"data": "C:/data", "source": "external_api", "model": None,
              "delegate_profile": None, "api_profile": str(profile), "allow_input": False}
    command = server_command(ticket)
    assert command[command.index("--api-profile") + 1] == str(profile)
    assert "--model-directory" not in command


def test_external_api_smoke_arguments_propagate_profile_path():
    profile = Path("C:/profiles/provider.json")
    args = smoke_instant_mcp.server_arguments(Path("bundle"), None, Path("data"),
                                               False, "external_api", None, profile)
    assert args[args.index("--api-profile") + 1] == str(profile)
    assert "--model-directory" not in args


def test_external_api_smoke_requires_absolute_profile():
    with pytest.raises(ValueError, match="absolute api profile"):
        smoke_instant_mcp.server_arguments(Path("bundle"), None, Path("data"),
                                           False, "external_api", None, Path("relative.json"))
