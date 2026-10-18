"""冻结模型使用同版伴随入口及原进程拥有者，不加载实际权重。"""
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from tests.test_formal_model_service import _configuration, backend


def _packaged(tmp_path, monkeypatch, *, companion=True, python_path=None):
    from app.vision import model_service

    install = tmp_path / "installed app"
    install.mkdir()
    gui = install / "AgentReview.exe"
    gui.write_bytes(b"fixture-not-executable")
    bridge = install / "AgentReviewBridge.exe"
    if companion:
        bridge.write_bytes(b"fixture-not-executable")
    monkeypatch.setattr(model_service, "sys", SimpleNamespace(frozen=True, executable=str(gui)))
    snapshot, path = _configuration(tmp_path, readiness_timeout_seconds=3)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile.update(runtime="transformers", output_contract="vista_point_v1", host="127.0.0.1",
                   device="cpu", dtype="float32", max_new_tokens=7)
    if python_path:
        profile["python_path"] = str(python_path)
    else:
        profile.pop("start_script")
    path.write_text(json.dumps(profile), encoding="utf-8")
    return snapshot, bridge, path


def test_packaged_vista_freezes_installed_companion_without_source_script_or_python(tmp_path, monkeypatch):
    from app.vision.model_service import freeze_model_service

    snapshot, bridge, path = _packaged(tmp_path, monkeypatch)
    frozen = freeze_model_service(snapshot)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    assert frozen.worker_executable == bridge
    assert "python_path" not in frozen.profile()
    assert "start_script" not in frozen.profile()
    assert frozen.profile()["model_path"] == str(tmp_path / "model")


def test_missing_companion_is_an_install_error_without_interpreter_fallback(tmp_path, monkeypatch):
    from app.vision.model_service import freeze_model_service, ModelServiceError

    snapshot, _, _ = _packaged(tmp_path, monkeypatch, companion=False)
    with pytest.raises(ModelServiceError, match="model_service_worker_missing"):
        freeze_model_service(snapshot)


def test_explicit_external_python_keeps_existing_script_route(tmp_path, monkeypatch):
    from app.vision.model_service import freeze_model_service

    python = tmp_path / "python.exe"
    python.write_bytes(b"fixture-not-executable")
    snapshot, _, _ = _packaged(tmp_path, monkeypatch, python_path=python)
    frozen = freeze_model_service(snapshot)
    assert frozen.worker_executable is None
    assert frozen.profile()["python_path"] == str(python)
    assert frozen.profile()["start_script"] == str(tmp_path / "start.ps1")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "::1"])
def test_managed_listener_cannot_escape_or_differ_from_validated_endpoint(tmp_path, monkeypatch, host):
    from app.vision.model_service import freeze_model_service, ModelServiceError

    snapshot, _, path = _packaged(tmp_path, monkeypatch)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["host"] = host
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ModelServiceError, match="model_service_profile_mismatch"):
        freeze_model_service(snapshot)


def test_frozen_owner_reuses_actual_launcher_scope_pid_and_cleanup(tmp_path, monkeypatch, backend):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes
    from app.vision.model_service import freeze_model_service, FormalModelService

    snapshot, bridge, _ = _packaged(tmp_path, monkeypatch)
    owner = FormalModelService(freeze_model_service(snapshot), output_root=tmp_path / "output")

    class Process:
        pid = 431
        def poll(self): return None
        def close(self): pass

    monkeypatch.setattr(model_server, "start_model_server", backend.original_start)
    monkeypatch.setattr(scopes, "spawn_process_in_scope", lambda command, **kwargs:
                        backend.starts.append((command, kwargs)) or Process())
    try:
        assert owner.prepare(Event()) == {"status": "ready", "ownership": "owned"}
        command, launch = backend.starts[0]
        assert command == [str(bridge), "--model-worker", "vista", "--model-path", str(tmp_path / "model"),
                           "--model-name", "fixture-model", "--host", "127.0.0.1", "--port", "17321",
                           "--device", "cpu", "--dtype", "float32", "--max-new-tokens", "7"]
        assert launch["scope_name"] == backend.scopes[0].name
        assert owner._pid_path.read_text(encoding="utf-8") == "431"
        assert owner.close()["cleanup_verified"] is True
        assert backend.cleanups[0][1]["pid_file"] == owner._pid_path
    finally:
        owner.close()


@pytest.mark.parametrize("fault", ["unknown_model", "relative_worker", "missing_worker", "missing_weights"])
def test_invalid_worker_launch_fails_before_creating_a_process(tmp_path, monkeypatch, fault):
    from app.core import model_server
    from app.vision.model_service import freeze_model_service

    snapshot, bridge, _ = _packaged(tmp_path, monkeypatch)
    profile = freeze_model_service(snapshot).profile()
    worker = bridge
    if fault == "unknown_model":
        profile["output_contract"] = "unknown"
    elif fault == "relative_worker":
        worker = Path("AgentReviewBridge.exe")
    elif fault == "missing_worker":
        worker = bridge.parent / "missing.exe"
    else:
        profile["model_path"] = str(tmp_path / "missing-model")
    monkeypatch.setattr(model_server, "_launch_model_server_process", lambda **kwargs: pytest.fail("must not spawn"))
    with pytest.raises((ValueError, FileNotFoundError)):
        model_server.start_model_server(profile, worker_executable=worker, output_root=tmp_path / "output")
