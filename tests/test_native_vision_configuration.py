"""正式配置从启动入口到单步拥有者的隔离回归。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_native_single_step_coordinator import _Facade, _Host, _Windows


def _config(path, model="synthetic-model"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"vision": {"mode": "local", "timeout_seconds": 2,
        "local": {"endpoint": "http://127.0.0.1:9/inference", "model_name": model}}}), encoding="utf-8")
    return path


def test_default_native_config_is_in_user_data_not_review_or_launch_directory(tmp_path, monkeypatch):
    from app.desktop_review.entrypoint import gui_arguments

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    args = gui_arguments(None)
    assert "--vision-config" in args
    assert Path(args[args.index("--vision-config") + 1]) == tmp_path / "data/AgentGuiRuntime/configs/vision.json"
    assert not (tmp_path / "data").exists()


def test_native_entry_reaches_real_coordinator_with_explicit_config(tmp_path, monkeypatch):
    from app.desktop_review import entrypoint, host, window

    config = _config(tmp_path / "chosen/vision.json")
    observed = []
    fake_host = _Host()
    fake_host.facade, fake_host.connections = _Facade(), object()
    fake_host.start = lambda: None
    monkeypatch.setattr(host, "DesktopReviewHost", lambda *args, **kwargs: fake_host)
    monkeypatch.setattr(window, "ensure_application", lambda: SimpleNamespace(exec=lambda: 0))

    class Window:
        def __init__(self, facade, *, single_step, **kwargs):
            self.coordinator = single_step

        def show(self):
            report = self.coordinator.environment()
            observed.append(report["vision_configuration"])
            assert self.coordinator._owner.thread_id is None

    monkeypatch.setattr(window, "ReviewMainWindow", Window)
    monkeypatch.setattr(entrypoint, "_show_startup_error", lambda kind: pytest.fail(kind))
    monkeypatch.chdir(tmp_path)
    assert entrypoint.main(["--data-dir", str(tmp_path / "data"), "--vision-config", "chosen/vision.json"]) == 0
    assert observed[0]["config_path"] == str(config)
    assert observed[0]["status"] == "configured_unverified"
    assert observed[0]["runtime_verified"] is False
    assert "endpoint" not in json.dumps(observed)


@pytest.mark.parametrize("mode", ["--diagnostics", "--agent-link-mcp"])
def test_vision_config_flag_cannot_change_bridge_or_diagnostics(mode, monkeypatch):
    from app.desktop_review import entrypoint

    monkeypatch.setattr(entrypoint, "_launch_gui", lambda args: pytest.fail("unexpected GUI"))
    with pytest.raises(SystemExit) as error:
        entrypoint.main([mode, "--vision-config", "unused.json"])
    assert error.value.code == 2


def test_missing_formal_config_fails_before_target_binding_and_is_retryable(tmp_path, monkeypatch):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError

    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(),
        vision_config_path=tmp_path / "missing.json", thread_initializer=lambda: None, thread_finalizer=lambda: None)
    monkeypatch.setattr(co, "_windows", lambda: pytest.fail("configuration must be checked before any window access"))
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.prepare(asset_id="asset-1", asset_content_sha256="a" * 64, target_window_handle=41, target_process_id=7)
        assert error.value.code == "vision_config_missing"
        assert not error.value.result_unknown
        assert co._runtime is None and not co._factory_outcome_unknown
        assert co._phase == "idle"
        assert not (tmp_path / "missing.json").exists()
        assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
    finally:
        co.shutdown()


def test_configuration_snapshot_is_pinned_before_binding_can_change_disk(tmp_path, monkeypatch):
    from app.desktop_review import single_step_coordinator as module

    config = _config(tmp_path / "config/vision.json", "before-bind")
    seen = []
    windows = _Windows()
    old_bind = windows.bind_window_by_handle

    def bind(handle):
        _config(config, "changed-during-bind")
        return old_bind(handle)

    windows.bind_window_by_handle = bind

    class StopAfterBoundary(RuntimeError):
        pass

    def factory(**kwargs):
        snapshot = kwargs["vision_configuration"]
        seen.append(snapshot.to_dict()["vision"]["local"]["model_name"])
        raise StopAfterBoundary()

    factory.window_manager = windows
    monkeypatch.setattr(module, "_production_runtime_factory", factory)
    co = module.NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), vision_config_path=config,
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    try:
        with pytest.raises(module.NativeSingleStepCoordinatorError):
            co.prepare(asset_id="asset-1", asset_content_sha256="a" * 64, target_window_handle=41, target_process_id=7)
        assert seen == ["before-bind"]
    finally:
        co._owner.close()


def test_native_environment_renders_config_state_but_rejects_raw_config(tmp_path):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from app.desktop_review.window import ensure_application

    application = ensure_application()
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(),
        vision_config_path=tmp_path / "missing.json", thread_initializer=lambda: None, thread_finalizer=lambda: None)
    dialog = SingleStepDialog(co)
    try:
        report = co.environment()
        dialog._load_environment(report)
        assert "vision_config_missing" in dialog.environment_report.toPlainText()
        assert str(tmp_path / "missing.json") in dialog.environment_report.toPlainText().replace("\\\\", "\\")
        report["vision_configuration"]["endpoint"] = "private-config-must-not-render"
        with pytest.raises(ValueError):
            dialog._load_environment(report)
        assert "private-config-must-not-render" not in dialog.environment_report.toPlainText()
        assert co._owner.thread_id is None
    finally:
        dialog.deleteLater()
        co.shutdown()
