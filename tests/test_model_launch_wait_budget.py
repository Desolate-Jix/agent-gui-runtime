"""启动等待的取消和剩余预算，不创建真实进程。"""
from threading import Event
from types import SimpleNamespace

import pytest


def test_expired_launch_budget_fails_before_files_or_process(tmp_path, monkeypatch):
    from app.core import model_server

    monkeypatch.setattr(model_server, "_resolve_path", lambda value: pytest.fail("budget first"))
    with pytest.raises(RuntimeError) as error:
        model_server.start_model_server({}, deadline=0.0, cancelled=Event(), output_root=tmp_path)
    assert error.value.code == "model_service_readiness_timeout"
    assert not list(tmp_path.iterdir())


def test_cancel_during_startup_wait_closes_owned_process_scope(tmp_path, monkeypatch):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes

    event = Event()
    closed, cleanup = [], []

    def spawn(*args, **kwargs):
        event.set()
        return SimpleNamespace(pid=432, poll=lambda: None, close=lambda: closed.append(True))

    monkeypatch.setattr(scopes, "spawn_process_in_scope", spawn)
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda name, **kwargs:
                        cleanup.append(name) or {"cleanup_status": "verified"})
    monkeypatch.setattr(model_server, "time", SimpleNamespace(monotonic=lambda: 10.0,
                        sleep=lambda value: pytest.fail("cancel must not sleep")))
    name = "Local\\AgentGuiNativeModel-" + "b" * 64
    with pytest.raises(RuntimeError) as error:
        model_server._launch_model_server_process(profile={"pid_file": str(tmp_path / "pid"), "startup_exit_check_seconds": 30},
            log_path=tmp_path / "launch.log", command=["synthetic"], scope_name=name, cancelled=event, deadline=11.0)
    assert error.value.code == "model_service_cancelled"
    assert cleanup == [name] and closed == [True]


def test_startup_wait_is_clipped_to_remaining_deadline(tmp_path, monkeypatch):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes

    now, waits = [10.0], []

    class Cancel:
        def is_set(self): return False
        def wait(self, seconds):
            waits.append(seconds)
            now[0] += seconds
            return False

    monkeypatch.setattr(model_server, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(scopes, "spawn_process_in_scope", lambda *a, **k: SimpleNamespace(pid=432, poll=lambda: None, close=lambda: None))
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda *a, **k: {"cleanup_status": "verified"})
    with pytest.raises(RuntimeError) as error:
        model_server._launch_model_server_process(profile={"pid_file": str(tmp_path / "pid"), "startup_exit_check_seconds": 30},
            log_path=tmp_path / "launch.log", command=["synthetic"], scope_name="Local\\AgentGuiNativeModel-" + "b" * 64,
            cancelled=Cancel(), deadline=10.1)
    assert error.value.code == "model_service_readiness_timeout"
    assert len(waits) == 1 and waits[0] == pytest.approx(0.1)


@pytest.mark.parametrize("phase", ["before-spawn", "poll", "health"])
def test_late_cancellation_prevents_next_side_effect(tmp_path, monkeypatch, phase):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes

    event, spawned, written, synced = Event(), [], [], []

    def pid_path(profile):
        if phase == "before-spawn": event.set()
        return tmp_path / "pid"

    def poll():
        if phase == "poll": event.set()
        return None

    def check(profile, *, timeout):
        event.set()
        return {"status": "running", "health": {"pid": 432}}

    monkeypatch.setattr(model_server, "model_profile_pid_path", pid_path)
    monkeypatch.setattr(model_server, "time", SimpleNamespace(monotonic=lambda: 10.0))
    monkeypatch.setattr(event, "wait", lambda seconds: False)
    monkeypatch.setattr(scopes, "spawn_process_in_scope", lambda *a, **k:
                        spawned.append(True) or SimpleNamespace(pid=432, poll=poll, close=lambda: None))
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda *a, **k: {"cleanup_status": "verified"})
    monkeypatch.setattr(model_server, "_write_model_profile_pid", lambda *a: written.append(True))
    monkeypatch.setattr(model_server, "_profile_supports_health_status", lambda profile: phase == "health")
    monkeypatch.setattr(model_server, "check_model_server", check)
    monkeypatch.setattr(model_server, "_sync_pid_file_from_health", lambda *a, **k: synced.append(True))
    with pytest.raises(RuntimeError) as error:
        model_server._launch_model_server_process(profile={"profile_id": "fixture"}, log_path=tmp_path / "log",
            command=["synthetic"], scope_name="Local\\AgentGuiNativeModel-" + "b" * 64, cancelled=event, deadline=11.0)
    assert error.value.code == "model_service_cancelled"
    assert spawned == ([] if phase == "before-spawn" else [True])
    assert written == ([True] if phase == "health" else [])
    assert synced == []
