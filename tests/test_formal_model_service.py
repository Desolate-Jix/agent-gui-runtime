"""模型准备使用真实管理代码，进程、健康探测及窗口边界全部隔离。"""

import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from app.vision.configuration import load_formal_vision_configuration


def _configuration(tmp_path, **service_overrides):
    model = tmp_path / "model"
    model.mkdir(exist_ok=True)
    script = tmp_path / "start.ps1"
    script.write_text("exit 0", encoding="utf-8")
    profile = {"profile_id": "fixture", "model_name": "fixture-model", "launchable": True,
               "endpoint": "http://127.0.0.1:17321/v1/chat/completions", "port": 17321,
               "model_path": "model", "start_script": "start.ps1", "pid_file": "legacy.pid"}
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    service = {"mode": "managed", "profile_path": "profile.json", "readiness_timeout_seconds": 0.1}
    service.update(service_overrides)
    config = tmp_path / "vision.json"
    config.write_text(json.dumps({"vision": {"mode": "local", "local": {
        "endpoint": profile["endpoint"], "model_name": profile["model_name"],
        "model_path": "model", "model_service": service}}}), encoding="utf-8")
    return load_formal_vision_configuration(config), profile_path


@pytest.fixture
def backend(monkeypatch):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scope_module

    state = SimpleNamespace(statuses=["unreachable", "running"], starts=[], cleanups=[], scopes=[],
                            cleanup_status="verified", model_id="fixture-model", listeners=[],
                            owned_listeners=True, check_hook=None, conflicts=[], fail_start=False,
                            members=[431], last_status=None, original_start=model_server.start_model_server,
                            original_check=model_server.check_model_server)

    class Scope:
        def __init__(self, name, *, create):
            assert create is True
            self.name, self.closed = name, False
            state.scopes.append(self)

        def pids(self):
            return state.members if state.starts else []

        def close(self):
            self.closed = True

    def check(profile, *, timeout=1.0):
        assert timeout <= 1.0
        if state.check_hook:
            state.check_hook()
        status = state.statuses.pop(0) if len(state.statuses) > 1 else state.statuses[0]
        state.last_status = status
        return {"status": status, "model_id": state.model_id}

    def launch(profile, **kwargs):
        state.starts.append((profile, kwargs))
        if state.fail_start:
            raise OSError("private launch details")
        return {"pid": 431, "pid_path": str(kwargs["output_root"] / "fixture-server.pid")}

    def cleanup(name, **kwargs):
        state.cleanups.append((name, kwargs))
        return {"cleanup_status": state.cleanup_status, "member_pids_after": [],
                "active_listeners_after": [], "pid_file_after": None}

    monkeypatch.setattr(model_server, "start_model_server", launch)
    monkeypatch.setattr(model_server, "check_model_server", check)
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: state.conflicts)
    monkeypatch.setattr(model_server, "stop_model_server", lambda *a, **k: pytest.fail("shared stop forbidden"))
    monkeypatch.setattr(model_server, "_stop_exclusive_resource_conflicts", lambda *a, **k: pytest.fail("global stop forbidden"))
    monkeypatch.setattr(scope_module, "WindowsProcessScope", Scope)
    monkeypatch.setattr(scope_module, "scoped_process_launch_ready", lambda: True)
    monkeypatch.setattr(scope_module, "observe_process_scope_cleanup", cleanup)
    monkeypatch.setattr(scope_module, "_listeners", lambda ports: (
        [{"pid": 431 if state.owned_listeners else 999, "port": ports[0]}]
        if state.starts or (state.last_status == "running" and not state.listeners) else state.listeners))
    monkeypatch.setattr(scope_module, "_identities_for_pids", lambda pids:
                        [{"pid": pid, "create_time_ns": 1000} for pid in pids])
    return state


def _owner(tmp_path, **kwargs):
    from app.vision.model_service import FormalModelService, freeze_model_service

    snapshot, _ = _configuration(tmp_path)
    frozen = freeze_model_service(snapshot)
    return FormalModelService(frozen, output_root=tmp_path / "output", **kwargs)


def test_managed_profile_is_frozen_and_paths_do_not_follow_cwd(tmp_path, monkeypatch):
    from app.vision.model_service import freeze_model_service

    snapshot, profile_path = _configuration(tmp_path)
    frozen = freeze_model_service(snapshot)
    profile_path.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    assert frozen.profile()["model_name"] == "fixture-model"
    assert frozen.profile()["model_path"] == str(tmp_path / "model")
    assert frozen.profile()["start_script"] == str(tmp_path / "start.ps1")
    changed = frozen.profile()
    changed["model_name"] = "wrong"
    assert frozen.profile()["model_name"] == "fixture-model"
    assert "endpoint" not in repr(frozen)


@pytest.mark.parametrize("field,value", [("model_name", "wrong"), ("endpoint", "http://127.0.0.1:7/v1/chat/completions"),
                                         ("model_path", "other"), ("launchable", False), ("port", 7)])
def test_profile_mismatch_fails_before_external_work(tmp_path, field, value):
    from app.vision.model_service import freeze_model_service, ModelServiceError

    snapshot, path = _configuration(tmp_path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile[field] = value
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ModelServiceError):
        freeze_model_service(snapshot)


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf")])
def test_readiness_timeout_is_validated(tmp_path, timeout):
    from app.vision.model_service import freeze_model_service, ModelServiceError

    snapshot, _ = _configuration(tmp_path, readiness_timeout_seconds=timeout)
    with pytest.raises(ModelServiceError):
        freeze_model_service(snapshot)


def test_default_external_configuration_does_not_adopt_or_launch(tmp_path):
    from app.vision.model_service import freeze_model_service
    from tests.test_native_vision_configuration import _config

    assert freeze_model_service(load_formal_vision_configuration(_config(tmp_path / "vision.json"))) is None


def test_existing_matching_service_is_never_stopped(tmp_path, backend):
    backend.statuses = ["running"]
    owner = _owner(tmp_path)
    assert owner.prepare(Event())["ownership"] == "external"
    assert owner.close()["cleanup_verified"] is True
    assert backend.starts == backend.scopes == backend.cleanups == []


def test_owned_launch_readiness_and_repeated_close_use_only_exact_job(tmp_path, backend):
    owner = _owner(tmp_path)
    original_env = dict(os.environ)
    assert owner.prepare(Event())["ownership"] == "owned"
    launch = backend.starts[0][1]
    assert launch["scope_name"] == backend.scopes[0].name
    assert launch["output_root"].is_relative_to(tmp_path / "output")
    assert dict(os.environ) == original_env
    assert owner.close()["cleanup_verified"] is True
    assert owner.close()["cleanup_verified"] is True
    assert len(backend.cleanups) == 1 and backend.scopes[0].closed
    assert backend.cleanups[0][0] == launch["scope_name"]
    assert backend.cleanups[0][1]["terminate"] is True


def test_wrong_model_and_busy_service_do_not_start_replacement(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    backend.statuses = ["running"]
    backend.model_id = "wrong-model"
    with pytest.raises(ModelServiceError, match="model_service_identity_mismatch"):
        _owner(tmp_path).prepare(Event())
    assert not backend.starts and not backend.cleanups


def test_endpoint_listener_outside_owned_job_is_not_accepted(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    backend.owned_listeners = False
    with pytest.raises(ModelServiceError, match="model_service_owner_mismatch"):
        _owner(tmp_path).prepare(Event())
    assert len(backend.cleanups) == 1
    assert backend.cleanups[0][1]["listener_ports"] == []


def test_occupied_unhealthy_endpoint_is_not_launched_or_stopped(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    backend.listeners = [{"pid": 999, "port": 17321}]
    with pytest.raises(ModelServiceError, match="model_service_endpoint_in_use"):
        _owner(tmp_path).prepare(Event())
    assert backend.starts == backend.cleanups == []


def test_cancelled_loading_cleans_owned_job_before_returning(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    cancel = Event()
    backend.check_hook = lambda: cancel.set() if backend.starts else None
    backend.statuses = ["unreachable", "loading"]
    with pytest.raises(ModelServiceError, match="model_service_cancelled"):
        _owner(tmp_path).prepare(cancel)
    assert len(backend.cleanups) == 1 and backend.scopes[0].closed


def test_cleanup_failure_retains_exact_owner_for_retry(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    owner = _owner(tmp_path)
    owner.prepare(Event())
    backend.cleanup_status = "indeterminate"
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.close()
    assert not backend.scopes[0].closed
    backend.cleanup_status = "verified"
    assert owner.close()["cleanup_verified"] is True
    assert backend.cleanups[0][0] == backend.cleanups[1][0]


def test_launch_exception_is_sanitized_and_cleans_retained_job(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    backend.fail_start = True
    with pytest.raises(ModelServiceError) as error:
        _owner(tmp_path).prepare(Event())
    assert "private launch details" not in str(error.value)
    assert backend.scopes[0].closed and len(backend.cleanups) == 1


def test_native_job_name_is_accepted_without_relaxing_hybrid_name_validation():
    from app.learn.hybrid import windows_process_scope as scope

    native = "Local\\AgentGuiNativeModel-" + "a" * 64
    assert scope._owned_scope_name(native) == native
    with pytest.raises(ValueError):
        scope.validate_process_scope_name(native)
    with pytest.raises(ValueError):
        scope._owned_scope_name("Local\\UnrelatedJob")


def test_dead_owned_instance_cannot_be_replaced_by_successful_health(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    backend.members = []
    with pytest.raises(ModelServiceError, match="model_service_owner_mismatch"):
        _owner(tmp_path).prepare(Event())
    assert len(backend.cleanups) == 1


def test_external_loading_timeout_and_cancellation_do_not_touch_processes(tmp_path, backend):
    from app.vision.model_service import ModelServiceError

    backend.statuses = ["loading"]
    with pytest.raises(ModelServiceError, match="model_service_readiness_timeout"):
        _owner(tmp_path).prepare(Event())
    cancel = Event()
    backend.check_hook = cancel.set
    with pytest.raises(ModelServiceError, match="model_service_cancelled"):
        _owner(tmp_path).prepare(cancel)
    assert backend.starts == backend.scopes == backend.cleanups == []


def test_resource_conflict_blocks_without_stopping_existing_service(tmp_path, backend):
    from app.vision.model_service import FormalModelService, freeze_model_service, ModelServiceError

    snapshot, path = _configuration(tmp_path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["exclusive_resource_group"] = "fixture-gpu"
    path.write_text(json.dumps(profile), encoding="utf-8")
    backend.conflicts = [{"profile_id": "other", "exclusive_resource_group": "fixture-gpu",
                          "endpoint": "http://127.0.0.1:9/other"}]
    with pytest.raises(ModelServiceError, match="model_service_resource_conflict"):
        FormalModelService(freeze_model_service(snapshot), output_root=tmp_path / "output").prepare(Event())
    assert backend.starts == backend.scopes == backend.cleanups == []


def test_ready_arriving_after_deadline_is_not_accepted(tmp_path, monkeypatch, backend):
    from app.vision import model_service

    now = [0.0]
    monkeypatch.setattr(model_service, "time", SimpleNamespace(monotonic=lambda: now[0]))
    backend.check_hook = lambda: now.__setitem__(0, 2.0) if backend.starts else None
    with pytest.raises(model_service.ModelServiceError, match="model_service_readiness_timeout"):
        _owner(tmp_path).prepare(Event())
    assert backend.scopes[0].closed


def test_health_probe_receives_remaining_budget(tmp_path, monkeypatch, backend):
    from app.core import model_server

    budgets = []
    backend.listeners = [{"pid": 431, "port": 17321}]
    monkeypatch.setattr(model_server, "check_model_server", lambda profile, *, timeout:
                        budgets.append(timeout) or {"status": "running", "model_id": "fixture-model"})
    _owner(tmp_path).prepare(Event())
    assert len(budgets) == 2 and all(0 < value <= 0.050001 for value in budgets)


def test_actual_launcher_and_localhost_health_reach_owned_ready_and_pid_handoff(tmp_path, monkeypatch, backend):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes
    from app.vision.model_service import FormalModelService, freeze_model_service

    requested = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            payload = json.dumps({"data": [{"id": "fixture-model"}]}).encode("utf-8")
            self.send_response(200 if backend.starts else 503)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    snapshot, path = _configuration(tmp_path, readiness_timeout_seconds=3)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile.update(port=server.server_port, endpoint=f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
    path.write_text(json.dumps(profile), encoding="utf-8")
    config = snapshot.to_dict()
    config["vision"]["local"]["endpoint"] = profile["endpoint"]
    snapshot.path.write_text(json.dumps(config), encoding="utf-8")
    owner = FormalModelService(freeze_model_service(load_formal_vision_configuration(snapshot.path)),
                               output_root=tmp_path / "output")

    class Process:
        pid = 431
        def poll(self): return None
        def close(self): pass

    monkeypatch.setattr(model_server, "start_model_server", backend.original_start)
    monkeypatch.setattr(model_server, "check_model_server", backend.original_check)
    monkeypatch.setattr(scopes, "spawn_process_in_scope", lambda command, **kwargs: backend.starts.append((command, kwargs)) or Process())
    try:
        assert owner.prepare(Event()) == {"status": "ready", "ownership": "owned"}
        assert requested == ["/v1/models", "/v1/models", "/v1/models"]
        assert owner._pid_path.read_text(encoding="utf-8").strip() == "431"
        assert list(owner._output_root.glob("logs/*.log"))
        assert not (tmp_path / "legacy.pid").exists()
        assert owner.close()["cleanup_verified"] is True
        assert backend.cleanups[0][1]["pid_file"] == owner._pid_path
    finally:
        owner.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
