import argparse
from pathlib import Path

import pytest

from scripts.update_runtime import _confirm, health_check


def test_noninteractive_install_requires_exact_target(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    digest = "a" * 64
    with pytest.raises(ValueError, match="confirmation"):
        _confirm(argparse.Namespace(confirm_target=None), digest, "install")
    assert _confirm(argparse.Namespace(confirm_target=digest), digest, "install") == digest
    with pytest.raises(ValueError, match="does_not_match"):
        _confirm(argparse.Namespace(confirm_target="b" * 64), digest, "install")


def test_health_probe_is_fixed_and_does_not_take_release_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-api-key")
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", "private-mcp-token")
    monkeypatch.setenv("AGENT_GUI_DECISION_PROFILE", "private-profile")
    calls = []
    def run(arguments, **options):
        calls.append((arguments, options))
        report = Path(arguments[arguments.index("--report") + 1])
        report.write_text('{"passed":true,"input_executed":false,"host_started":false}')
        return argparse.Namespace(returncode=0)
    monkeypatch.setattr("scripts.update_runtime.subprocess.run", run)
    assert health_check(tmp_path) is True
    args, options = calls[0]
    assert args[1:4] == ["-I", "-B", "-X"]
    assert str(tmp_path / "scripts/check_execution_component.py") in args
    assert options["timeout"] == 120
    assert not {"OPENAI_API_KEY", "AGENT_GUI_MCP_TOKEN", "AGENT_GUI_DECISION_PROFILE"}.intersection(options["env"])


def test_incomplete_health_evidence_is_failure(tmp_path, monkeypatch):
    def run(arguments, **_):
        Path(arguments[arguments.index("--report") + 1]).write_text('{"passed":true,"host_started":true}')
        return argparse.Namespace(returncode=0)
    monkeypatch.setattr("scripts.update_runtime.subprocess.run", run)
    assert health_check(tmp_path) is False


@pytest.mark.parametrize("status,exit_code", [("applied", 0), ("rolled_back", 1), ("failed", 1)])
def test_apply_exit_code_reports_new_version_success_only(tmp_path, monkeypatch, capsys, status, exit_code):
    from scripts.update_runtime import main
    digest = "a" * 64
    class Updater:
        def __init__(self, *_):
            pass
        def status(self):
            return {"version": "1.2.3", "target_digest": digest}
        def apply(self, confirmed, *, health_check):
            assert confirmed == digest and callable(health_check)
            return {"status": status}
    monkeypatch.setattr("app.runtime_update.RuntimeUpdater", Updater)
    assert main(["--root", str(tmp_path), "apply", "--confirm-target", digest]) == exit_code
    assert '"status": "' + status + '"' in capsys.readouterr().out
