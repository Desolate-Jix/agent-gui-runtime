from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import start_test_panel as launcher
from scripts.start_test_panel import (
    PortProbe,
    choose_runtime_port,
    is_agent_runtime_health,
)


def test_health_payload_must_identify_agent_gui_runtime() -> None:
    assert is_agent_runtime_health(
        {
            "success": True,
            "data": {"status": "ok", "service": "agent-gui-runtime"},
        }
    )
    assert not is_agent_runtime_health({"success": True, "data": {"service": "other-app"}})
    assert not is_agent_runtime_health({"detail": "Not Found"})


def test_choose_runtime_port_reuses_agent_runtime_after_foreign_service() -> None:
    probes = [
        PortProbe(port=8000, status="foreign_service", detail="HTTP 404"),
        PortProbe(port=8765, status="agent_runtime", detail="healthy"),
    ]

    selection = choose_runtime_port(probes)

    assert selection.port == 8765
    assert selection.should_start is False


def test_choose_runtime_port_skips_foreign_service_and_uses_free_port() -> None:
    probes = [
        PortProbe(port=8000, status="foreign_service", detail="unexpected service"),
        PortProbe(port=8765, status="free", detail="connection refused"),
    ]

    selection = choose_runtime_port(probes)

    assert selection.port == 8765
    assert selection.should_start is True


def test_choose_runtime_port_prefers_existing_runtime_over_earlier_free_port() -> None:
    probes = [
        PortProbe(port=8000, status="free", detail="connection refused"),
        PortProbe(port=8765, status="agent_runtime", detail="healthy"),
    ]

    selection = choose_runtime_port(probes)

    assert selection.port == 8765
    assert selection.should_start is False


def test_choose_runtime_port_rejects_when_all_ports_are_foreign() -> None:
    probes = [
        PortProbe(port=8000, status="foreign_service", detail="unexpected service"),
        PortProbe(port=8765, status="foreign_service", detail="unexpected service"),
    ]

    try:
        choose_runtime_port(probes)
    except RuntimeError as exc:
        assert "No available panel port" in str(exc)
        assert "8000" in str(exc)
        assert "8765" in str(exc)
    else:
        raise AssertionError("choose_runtime_port should reject fully occupied ports")


def test_config_paths_are_relative_to_config_file_not_working_directory(tmp_path, monkeypatch):
    config_dir = tmp_path / "\u5f00\u53d1\u914d\u7f6e"
    config_dir.mkdir()
    config_path = config_dir / "panel.json"
    config_path.write_text(json.dumps({"ports": [9001, 9002], "log_path": "logs/runtime.log", "startup_timeout_seconds": 12}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    config = launcher.load_launcher_config(config_path)

    assert config.ports == (9001, 9002)
    assert config.log_path == config_dir / "logs" / "runtime.log"
    assert config.startup_timeout_seconds == 12
    assert not config.log_path.parent.exists()


@pytest.mark.parametrize("payload", [
    {"ports": []}, {"ports": [True]}, {"ports": [0]}, {"ports": [65536]},
    {"ports": [8000, 8000]}, {"ports": "8000"}, {"host": "0.0.0.0"},
    {"log_path": ""}, {"log_path": 7}, {"startup_timeout_seconds": True},
    {"startup_timeout_seconds": 0}, {"startup_timeout_seconds": float("nan")},
    {"startup_timeout_seconds": 301}, {"startup_timeout_seconds": 10 ** 400}, [],
])
def test_invalid_config_fails_closed(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="config"):
        launcher.load_launcher_config(path)


def test_missing_malformed_or_oversized_config_does_not_fall_back(tmp_path):
    path = tmp_path / "panel.json"
    with pytest.raises(RuntimeError, match="config"):
        launcher.load_launcher_config(path)
    for data in (b"{bad", b"\xff", b" " * 65537):
        path.write_bytes(data)
        with pytest.raises(RuntimeError, match="config"):
            launcher.load_launcher_config(path)


def test_offline_check_never_launches_probes_imports_app_or_writes_logs(tmp_path, monkeypatch, capsys):
    path = tmp_path / "panel.json"
    path.write_text('{"log_path": "not-created/runtime.log"}', encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("offline check attempted runtime side effects")
    monkeypatch.setattr(launcher, "launch_panel", forbidden)
    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(launcher.socket, "socket", forbidden)
    monkeypatch.setattr(launcher.webbrowser, "open", forbidden)
    checked = []
    def find_spec(name):
        checked.append(name)
        assert name in launcher.LAUNCHER_DEPENDENCIES
        return object()
    monkeypatch.setattr(launcher.importlib.util, "find_spec", find_spec)
    assert launcher.main(["--check", "--json", "--config", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "metadata_present_runtime_not_run"
    assert report["runtime"] == {key: "not_run" for key in ("service", "model", "ocr", "gpu", "gui", "network")}
    assert checked == list(launcher.LAUNCHER_DEPENDENCIES)
    assert not (tmp_path / "not-created").exists()


def test_missing_dependency_check_returns_nonzero_and_actionable_json(monkeypatch, capsys):
    monkeypatch.setattr(launcher.importlib.util, "find_spec", lambda name: None if name == "uvicorn" else object())
    assert launcher.main(["--check", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["missing_dependencies"] == ["uvicorn"]
    assert "uv sync" in report["setup_hint"]


def test_json_requires_check_and_bad_config_returns_structured_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        launcher.main(["--json"])
    assert exc.value.code == 2
    capsys.readouterr()
    assert launcher.main(["--check", "--json", "--config", str(tmp_path / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_runtime_uses_current_python_single_worker_and_configured_log(tmp_path, monkeypatch):
    config = launcher.LauncherConfig(ports=(9001,), log_path=tmp_path / "logs/runtime.log", startup_timeout_seconds=9)
    calls = []
    sentinel = object()
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        assert not kwargs["stdout"].closed
        return sentinel
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher.start_runtime(9001, config=config) is sentinel
    command, kwargs = calls[0]
    assert command == [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "9001", "--workers", "1"]
    assert kwargs["cwd"] == launcher.REPO_ROOT
    assert kwargs["stdout"].closed
    assert config.log_path.is_file()


def test_config_reaches_probe_start_and_wait_without_browser(tmp_path, monkeypatch):
    config = launcher.LauncherConfig(ports=(9001,), log_path=tmp_path / "runtime.log", startup_timeout_seconds=9)
    calls = []
    monkeypatch.setattr(launcher, "probe_port", lambda port: (calls.append(("probe", port)) or launcher.PortProbe(port, "free", "free")))
    monkeypatch.setattr(launcher, "start_runtime", lambda port, *, config: (calls.append(("start", port, config)) or "process"))
    monkeypatch.setattr(launcher, "wait_for_runtime", lambda process, port, *, config: calls.append(("wait", process, port, config)))
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args: pytest.fail("browser must stay closed"))
    assert launcher.launch_panel(open_browser=False, config=config) == "http://127.0.0.1:9001/panel"
    assert calls == [("probe", 9001), ("start", 9001, config), ("wait", "process", 9001, config)]


def test_batch_launcher_uses_existing_environment_without_implicit_sync():
    source = (Path(launcher.REPO_ROOT) / "start_test_panel.bat").read_text(encoding="utf-8")
    assert '".venv\\Scripts\\python.exe" scripts\\start_test_panel.py %*' in source
    assert "uv run" not in source
    assert "where uv" not in source


def test_check_from_fresh_process_outside_repository(tmp_path):
    config = tmp_path / "\u5f00\u53d1.json"
    config.write_text('{"ports": [9010], "log_path": "missing/log.txt"}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(launcher.REPO_ROOT / "scripts/start_test_panel.py"), "--check", "--json", "--config", str(config)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["config"]["ports"] == [9010]
    assert report["config"]["log_path"] == str(tmp_path / "missing/log.txt")
    assert report["runtime"]["service"] == "not_run"
    assert not (tmp_path / "missing").exists()


def test_wait_failure_uses_configured_timeout_and_log(tmp_path, monkeypatch):
    config = launcher.LauncherConfig(log_path=tmp_path / "runtime.log", startup_timeout_seconds=9)
    config.log_path.write_text("specific failure", encoding="utf-8")
    times = iter([0.0, 10.0])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="within 9 seconds") as exc:
        launcher.wait_for_runtime(object(), 9001, config=config)
    assert str(config.log_path) in str(exc.value)
    assert "specific failure" in str(exc.value)
