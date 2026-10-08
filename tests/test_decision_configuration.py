"""判断配置经过公开启动入口传到宿主，重复读回执不触发模型。"""
import json
from pathlib import Path
import sys
import subprocess
import tomllib

import pytest

from app.instant_mcp import InstantCommand, InstantSession
from app.instant_receipt import compact_receipt
from scripts import configure_instant_mcp
from scripts.instant_admin_worker import server_command
from scripts.run_local_step_session import run_step_command


def test_configure_emits_decision_profile_for_agent_recognition_without_key(monkeypatch, tmp_path):
    profile = tmp_path / "decision.json"
    profile.write_text(json.dumps({"contract_version": "decision_profile.v1", "mode": "shadow"}), encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(configure_instant_mcp, "__file__", str(scripts / "configure_instant_mcp.py"))
    monkeypatch.setattr(sys, "argv", ["configure", "--recognition-source", "agent_current",
        "--decision-profile", str(profile), "--python", sys.executable, "--data-dir", str(tmp_path / "data")])
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-must-never-be-serialized")
    configure_instant_mcp.main()
    raw = (tmp_path / "mcp-config.local.json").read_text(encoding="utf-8")
    assert "test-secret-must-never-be-serialized" not in raw
    args = json.loads(raw)["mcpServers"]["agent-review-instant"]["args"]
    assert args[args.index("--decision-profile") + 1] == str(profile)
    config = tomllib.loads((tmp_path / "mcp-config.local.toml").read_text(encoding="utf-8"))
    assert config["mcp_servers"]["agent-review-instant"]["args"] == args


def test_admin_worker_forwards_decision_profile_without_serializing_secret():
    ticket = {"data": "C:/data", "source": "agent_current", "model": None,
              "delegate_profile": None, "api_profile": None, "allow_input": False,
              "decision_profile": "C:/profiles/decision.json"}
    command = server_command(ticket)
    assert command[command.index("--decision-profile") + 1] == ticket["decision_profile"]


def test_public_step_preserves_explicit_decision_and_runner_binds_execution_id():
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Open detail"},
               "decision_check": {"phase": "after_action", "condition": "Detail for R-101 is open"}}
    checked = InstantCommand.model_validate(command).command()
    class Coordinator:
        def execute_local_step(self, **kwargs):
            assert kwargs["execution_request_id"] == "step-1"
            assert kwargs["decision_check"] == command["decision_check"]
            return {"phase": "verified_test_boundary"}
    result = run_step_command(Coordinator(), {"handle": 1, "process_id": 2}, checked, execution_request_id="step-1")
    assert result["phase"] == "verified_test_boundary"


@pytest.mark.parametrize("command", [
    {"kind": "capture"},
    {"kind": "step", "operation": "type_text", "request": {"text": "value", "x": 1, "y": 1, "click_before_typing": True}},
])
def test_before_decision_rejects_unsupported_route_at_admission(command):
    with pytest.raises(ValueError):
        InstantCommand.model_validate({**command, "decision_check": {"phase": "before_action", "condition": "Ready"}}).command()


def test_session_validates_decision_profile_before_host_launch(tmp_path):
    profile = tmp_path / "bad.json"
    profile.write_text('{"api_key":"must-not-be-in-profile"}', encoding="utf-8")
    session = InstantSession(tmp_path, tmp_path / "data", allow_local_input=True,
                             recognition_source="agent_current", decision_profile=profile)
    with pytest.raises(ValueError):
        session._startup_configuration()
    assert session.process is None
    assert not (tmp_path / "data").exists()


def test_compact_receipt_preserves_judgment_advice_and_input_status():
    advice = {"status": "completed", "verdict": "uncertain", "adopted": False,
              "authorizes_action": False, "automatic_retry_allowed": False}
    full = {"request_id": "step-1", "operation_succeeded": True, "task_effect_verified": False,
            "decision_judgment": advice, "result": {"status": "completed"}}
    compact = compact_receipt(full)
    assert compact["decision_judgment"] == advice
    assert compact["operation_succeeded"] is True
    assert compact["task_effect_verified"] is False


def test_isolated_admin_script_validates_profile_before_uac(tmp_path):
    profile = tmp_path / "invalid.json"
    profile.write_text('{"mode":"wrong"}', encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, "-I", str(root / "scripts/start_instant_mcp_admin.py"),
        "--recognition-source", "agent_current", "--data-dir", str(tmp_path / "data"),
        "--decision-profile", str(profile)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert completed.returncode == 2
    assert "--decision-profile has an invalid schema" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_active_session_cannot_silently_reload_changed_decision_policy(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text('{"contract_version":"decision_profile.v1","mode":"shadow"}', encoding="utf-8")
    session = InstantSession(tmp_path, tmp_path / "data", allow_local_input=True,
                             recognition_source="agent_current", decision_profile=profile)
    session._startup_configuration()
    session.session = session.data_root / ("session-" + "a" * 32)
    session.session.mkdir(parents=True)
    (session.data_root / "latest-session.json").write_text(json.dumps({
        "name": session.session.name, "decision_profile": session.decision_profile,
        "decision_profile_sha256": session.decision_profile_sha256, "recognition_source": "agent_current"}), encoding="utf-8")
    monkeypatch.setattr(session, "_lock", lambda: None)
    monkeypatch.setattr(session, "status", lambda: {"cleanup_verified": False, "pending_ids": []})
    profile.write_text('{"contract_version":"decision_profile.v1","mode":"auto"}', encoding="utf-8")
    with pytest.raises(ValueError, match="different decision profile"):
        session.start()


def test_provider_close_failure_is_recorded_without_stopping_remaining_cleanup(tmp_path):
    from app.core.decision_configuration import close_session_decision_service
    from app.judgment import DecisionService
    class BrokenProvider:
        def close(self):
            raise OSError("synthetic-close-failure")
    errors = []
    service = DecisionService(tmp_path, provider=BrokenProvider())
    close_session_decision_service(service, errors)
    assert errors == [{"operation": "decision_service_close", "error_type": "OSError"}]
