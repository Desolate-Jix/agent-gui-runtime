from __future__ import annotations

from pathlib import Path
import time as stdtime

import pytest


def test_explicit_launch_scope_env_and_paths_are_owner_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import model_server

    script = tmp_path / "start.ps1"
    weights = tmp_path / "weights.bin"
    script.write_text("# synthetic", encoding="utf-8")
    weights.write_bytes(b"synthetic")
    captured: dict[str, object] = {}
    monkeypatch.setattr(model_server, "_resolve_path", lambda value: {"start.ps1": script, "weights.bin": weights}[value])
    monkeypatch.setattr(
        model_server,
        "_launch_model_server_process",
        lambda **kwargs: captured.update(kwargs) or {"pid": 7},
    )
    profile = {"profile_id": "vista/test", "start_script": "start.ps1", "model_path": "weights.bin", "pid_file": "legacy.pid"}
    root = (tmp_path / "owner-a").resolve()

    assert model_server.start_model_server(
        profile, scope_name="Local\\AgentGuiHybrid-vista-" + "a" * 64,
        child_env={"OWNER_TOKEN": "only-child"}, output_root=root,
    ) == {"pid": 7}

    assert captured["scope_name"] == "Local\\AgentGuiHybrid-vista-" + "a" * 64
    assert captured["child_env"] == {"OWNER_TOKEN": "only-child"}
    assert Path(captured["log_path"]).is_relative_to(root)
    assert Path(captured["profile"]["pid_file"]).is_relative_to(root)
    assert profile["pid_file"] == "legacy.pid"


def test_explicit_launch_keeps_env_scopes_and_owner_paths_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import model_server

    class Process:
        pid = 9
        def poll(self): return None
        def close(self): return None

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(model_server, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None)}))
    monkeypatch.setattr(model_server, "model_profile_pid_path", lambda _profile: tmp_path / "legacy.pid")
    monkeypatch.setattr(model_server, "_write_model_profile_pid", lambda *_args: None)
    monkeypatch.setattr(model_server, "_profile_supports_health_status", lambda _profile: False)
    monkeypatch.setattr(model_server, "spawn_process_in_scope", lambda *args, **kwargs: calls.append(kwargs) or Process(), raising=False)
    import app.learn.hybrid.windows_process_scope as scope_module
    monkeypatch.setattr(scope_module, "spawn_process_in_scope", lambda *args, **kwargs: calls.append(kwargs) or Process())

    for marker, root in (("one", (tmp_path / "one").resolve()), ("two", (tmp_path / "two").resolve())):
        (root / "logs").mkdir(parents=True)
        model_server._launch_model_server_process(
            profile={"profile_id": marker, "startup_exit_check_seconds": 0},
            log_path=root / "logs" / f"{marker}.log", command=["synthetic"],
            scope_name="Local\\AgentGuiHybrid-vista-" + marker[0] * 64,
            child_env={"OWNER": marker},
        )
    assert [call["env"] for call in calls] == [{"OWNER": "one"}, {"OWNER": "two"}]


@pytest.mark.parametrize("kwargs", [
    {"scope_name": "   "},
    {"output_root": Path("relative")},
])
def test_explicit_launch_rejects_invalid_owner_inputs_before_launch(kwargs: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import model_server

    monkeypatch.setattr(model_server, "_launch_model_server_process", lambda **_kwargs: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        model_server.start_model_server({"profile_id": "vista"}, **kwargs)


def test_legacy_launch_uses_existing_environment_and_does_not_pass_new_keywords(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import model_server

    captured: dict[str, object] = {}
    monkeypatch.setattr(model_server, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(model_server, "_resolve_path", lambda _value: Path(__file__).resolve())
    monkeypatch.setattr(model_server, "_launch_model_server_process", lambda *, profile, log_path, command: captured.update(profile=profile, log_path=log_path, command=command) or {"pid": 4})
    assert model_server.start_model_server({"profile_id": "legacy"}) == {"pid": 4}
    assert captured["profile"]["profile_id"] == "legacy"


def test_explicit_scope_immediate_failure_cleans_the_chosen_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope

    class FailedProcess:
        pid = 41
        def poll(self): return 2
        def close(self): return None

    scope_name = "Local\\AgentGuiHybrid-vista-" + "c" * 64
    pid_path = tmp_path / "owner" / "model-server-pids" / "vista.pid"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(model_server, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None)}))
    monkeypatch.setattr(model_server, "model_profile_pid_path", lambda _profile: pid_path)
    monkeypatch.setattr(windows_process_scope, "spawn_process_in_scope", lambda *_args, **_kwargs: FailedProcess())
    monkeypatch.setattr(
        windows_process_scope, "observe_process_scope_cleanup",
        lambda name, **kwargs: calls.append({"name": name, **kwargs}) or {"cleanup_status": "verified"},
    )
    log_path = tmp_path / "owner" / "logs" / "vista.log"
    log_path.parent.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="exited immediately"):
        model_server._launch_model_server_process(
            profile={"profile_id": "vista", "port": 44, "startup_exit_check_seconds": 0},
            log_path=log_path, command=["synthetic"], scope_name=scope_name,
        )
    assert calls == [{
        "name": scope_name, "terminate": True, "listener_ports": [44],
        "pid_file": pid_path, "remove_owned_pid_file": True, "stable_zero_observations": 3,
    }]


def test_explicit_output_root_uses_safe_direct_log_and_pid_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope

    class Process:
        pid = 73
        def poll(self): return None
        def close(self): return None

    script = tmp_path / "start.ps1"
    weights = tmp_path / "weights.bin"
    script.write_text("# synthetic", encoding="utf-8")
    weights.write_bytes(b"synthetic")
    root = (tmp_path / "owner").resolve()
    profile = {
        "profile_id": "vista/test", "start_script": str(script), "model_path": str(weights),
        "pid_file": "legacy.pid", "startup_exit_check_seconds": 0,
    }
    monkeypatch.setattr(model_server, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None), "strftime": staticmethod(stdtime.strftime)}))
    monkeypatch.setattr(model_server, "_profile_supports_health_status", lambda _profile: False)
    monkeypatch.setattr(windows_process_scope, "spawn_process_in_scope", lambda *_args, **_kwargs: Process())

    model_server.start_model_server(
        profile, scope_name="Local\\AgentGuiHybrid-vista-" + "d" * 64, output_root=root,
    )

    logs = list((root / "logs").glob("local-vision-server-vista-test-*.log"))
    assert logs and all(path.parent == root / "logs" for path in logs)
    assert (root / "model-server-pids" / "vista-test.pid").read_text(encoding="utf-8") == "73"
    assert profile["pid_file"] == "legacy.pid"
