import json
from pathlib import Path

from app.runtime_lifecycle import InstallationLease, update_state_path
from app.runtime_update_schedule import (CHECK_INTERVAL_SECONDS, cached_check, check_and_cache,
                                          schedule_check, set_automatic_checks)


def test_daily_checks_are_metadata_only_even_during_task(tmp_path):
    root = tmp_path / "runtime"
    calls = []
    class Updater:
        def __init__(self, supplied):
            assert supplied == root
        def check(self):
            calls.append("metadata")
            return {"version": "1.2.3", "files": ["do not expose large manifest via MCP"]}
    with InstallationLease(root):
        first = check_and_cache(root, scheduled=True, updater_factory=Updater, now=100000)
        second = check_and_cache(root, scheduled=True, updater_factory=Updater, now=100001)
    assert first["status"] == "available"
    assert second["cached"] is True and calls == ["metadata"]
    assert cached_check(root)["available_version"] == "1.2.3"
    assert "target" not in cached_check(root)
    assert "files" not in (update_state_path(root) / "last-check.json").read_text(encoding="utf-8")
    check_and_cache(root, scheduled=True, updater_factory=Updater, now=100000 + CHECK_INTERVAL_SECONDS)
    assert calls == ["metadata", "metadata"]


def test_optout_prevents_scheduled_network_and_has_no_install(tmp_path):
    root = tmp_path / "runtime"
    set_automatic_checks(root, False)
    def forbidden(*_):
        raise AssertionError("network must not run")
    assert check_and_cache(root, scheduled=True, updater_factory=forbidden)["status"] == "disabled"
    assert cached_check(root)["automatic_install"] is False


def test_offline_check_does_not_leak_error_or_block_tasks(tmp_path):
    root = tmp_path / "runtime"
    class Offline:
        def __init__(self, *_):
            pass
        def check(self):
            raise OSError("secret provider key and response body")
    result = check_and_cache(root, updater_factory=Offline)
    assert result["status"] == "check_failed"
    assert "secret" not in json.dumps(result)
    with InstallationLease(root):
        pass


def test_launcher_uses_background_process_without_provider_keys(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / ".component-install.json").write_text("{}")
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", "private-mcp-token")
    monkeypatch.setenv("OPENAI_API_KEY", "private-api-key")
    calls = []
    monkeypatch.setattr("app.runtime_update_schedule.subprocess.Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    schedule_check(root)
    assert len(calls) == 1
    arguments, options = calls[0]
    assert "--scheduled" in arguments[0]
    assert "private" not in json.dumps(options["env"])
    assert options["stdout"] == options["stderr"]


def test_source_checkout_does_not_start_auto_check(tmp_path, monkeypatch):
    monkeypatch.setattr("app.runtime_update_schedule.subprocess.Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    schedule_check(tmp_path)
    assert not update_state_path(tmp_path).exists()
