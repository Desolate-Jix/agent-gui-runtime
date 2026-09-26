"""Agent 视觉来源的启动闭合，不启动真实桌面或模型。"""
from argparse import Namespace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.instant_mcp import InstantSession, InstantStartError


class _Child:
    pid = 12345

    def poll(self):
        return None


@pytest.mark.parametrize("source,profile", [
    ("agent_current", None),
    ("agent_delegate", "vision-luna"),
])
def test_agent_start_skips_missing_model_and_passes_route(tmp_path, monkeypatch, source, profile):
    import app.instant_mcp as instant

    launched = []

    def fake_popen(command, **kwargs):
        launched.append(command)
        return _Child()

    monkeypatch.setattr(instant.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(instant, "uuid4", lambda: type("U", (), {"hex": "a" * 32})())
    monkeypatch.setattr("psutil.Process", lambda pid: type("P", (), {"create_time": lambda self: 1.0})())
    session = InstantSession(tmp_path, tmp_path / "data", None, allow_local_input=True,
                             recognition_source=source, delegate_profile=profile)
    try:
        status = session.start()
        assert status["recognition_source"] == source
        assert status["delegate_profile"] == profile
        assert session.start()["recognition_source"] == source
        assert len(launched) == 1
        assert "--model-directory" not in launched[0]
        assert launched[0][launched[0].index("--recognition-source") + 1] == source
        if profile:
            assert launched[0][launched[0].index("--delegate-profile") + 1] == profile
    finally:
        if session.lock_file:
            session.lock_file.close()
        if session.log_file:
            session.log_file.close()


@pytest.mark.parametrize("source,profile,code", [
    ("agent_delegate", None, "invalid_recognition_configuration"),
    ("external_api", None, "external_api_not_implemented"),
])
def test_unsupported_source_rejected_before_launch(tmp_path, source, profile, code):
    session = InstantSession(tmp_path, tmp_path / "data", None, allow_local_input=True,
                             recognition_source=source, delegate_profile=profile)
    with pytest.raises(InstantStartError) as error:
        session.start()
    assert error.value.code == code
    assert session.process is None and session.lock_file is None


@pytest.mark.parametrize("source,profile", [
    ("agent_current", None), ("agent_delegate", "vision-luna")])
def test_runner_bootstrap_never_configures_local_model(source, profile):
    from scripts.run_local_step_session import configure_recognition_startup

    class Coordinator:
        def configure_vista_model(self, **kwargs):
            raise AssertionError("local model configuration must not run")

    args = Namespace(recognition_source=source, delegate_profile=profile, model_directory=None)
    report = {}
    configure_recognition_startup(Coordinator(), args, report)
    assert report["recognition_source"] == source
    assert report["delegate_profile"] == profile
    assert report["model_configuration"] is None


def test_runner_local_bootstrap_preserved(tmp_path):
    from scripts.run_local_step_session import configure_recognition_startup

    class Coordinator:
        def configure_vista_model(self, **kwargs):
            assert kwargs == {"model_directory": str(tmp_path.resolve())}
            return {"configured": True}

    report = {}
    configure_recognition_startup(Coordinator(), Namespace(recognition_source="local",
        delegate_profile=None, model_directory=tmp_path), report)
    assert report["model_configuration"] == {"configured": True}


def test_prepare_models_command_is_noop_for_agent_source():
    from scripts.run_local_step_session import prepare_models_for_source

    class Coordinator:
        def prepare_local_step_models(self, **kwargs):
            raise AssertionError("local model prewarm must not run")

    assert prepare_models_for_source(Coordinator(), "agent_current") == {
        "status": "model_not_required", "recognition_source": "agent_current"}


def test_runner_rejects_external_api_explicitly():
    from scripts.run_local_step_session import configure_recognition_startup

    with pytest.raises(ValueError, match="external_api.*not implemented"):
        configure_recognition_startup(object(), Namespace(recognition_source="external_api",
            delegate_profile=None, model_directory=None), {})


def test_admin_worker_passes_source_without_model():
    from scripts.instant_admin_worker import server_command

    command = server_command({"data": "C:\\data", "model": None, "source": "agent_delegate",
                              "delegate_profile": "vision-luna", "allow_input": True})
    assert "--model-directory" not in command
    assert command[command.index("--recognition-source") + 1] == "agent_delegate"
    assert command[command.index("--delegate-profile") + 1] == "vision-luna"
    assert "--allow-local-input" in command


def test_admin_ticket_transports_agent_route_without_model(tmp_path, monkeypatch):
    import scripts.start_instant_mcp_admin as admin
    from scripts.instant_admin_worker import server_command

    monkeypatch.setitem(sys.modules, "win32file", SimpleNamespace(
        CreateDirectory=lambda path, security: Path(path).mkdir()))
    monkeypatch.setattr(admin, "private_security", lambda sid: object())
    monkeypatch.setattr(admin.tempfile, "gettempdir", lambda: str(tmp_path))
    args = Namespace(connect_timeout=90, data_dir=tmp_path / "data", model_directory=None,
                     recognition_source="agent_current", delegate_profile=None,
                     allow_local_input=True)
    ticket, payload = admin.make_ticket(args, "sid", 1)
    try:
        assert json.loads(ticket.read_text(encoding="utf-8")) == payload
        assert payload["model"] is None
        command = server_command(payload)
        assert "--model-directory" not in command
        assert command[command.index("--recognition-source") + 1] == "agent_current"
    finally:
        ticket.unlink()
        ticket.parent.rmdir()


def test_generated_agent_config_omits_model_path(tmp_path, monkeypatch):
    import scripts.configure_instant_mcp as configure

    root = tmp_path / "bundle"
    (root / "scripts").mkdir(parents=True)
    entry = root / "scripts" / "configure_instant_mcp.py"
    entry.touch()
    monkeypatch.setattr(configure, "__file__", str(entry))
    monkeypatch.setattr(sys, "argv", [str(entry), "--python", sys.executable,
        "--data-dir", str(tmp_path / "data"), "--recognition-source", "agent_delegate",
        "--delegate-profile", "vision-luna", "--administrator"])
    configure.main()
    args = json.loads((root / "mcp-config.local.json").read_text(encoding="utf-8"))["mcpServers"][
        "agent-review-instant"]["args"]
    assert "--model-directory" not in args
    assert args[args.index("--recognition-source") + 1] == "agent_delegate"
    assert args[args.index("--delegate-profile") + 1] == "vision-luna"
    assert Path(args[0]).name == "start_instant_mcp_admin.py"
