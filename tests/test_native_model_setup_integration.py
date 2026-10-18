"""首次配置必须接回实际托管配置加载器，并保持真实 Qt 作业生命周期。"""
import threading
from pathlib import Path

import pytest
from PySide6.QtTest import QTest

from app.desktop_review.model_setup_dialog import ModelSetupDialog
from app.desktop_review.window import ensure_application
from app.vision.configuration import load_formal_vision_configuration
from app.vision.model_service import freeze_model_service
from tests.test_native_model_setup import _weights
from tests.test_native_model_setup_coordinator import _coordinator


def _drain(dialog):
    for _ in range(200):
        QTest.qWait(5)
        if dialog._job is None:
            break


def test_real_qt_save_reopens_as_managed_model_with_exact_profile(tmp_path):
    app = ensure_application()
    coordinator = _coordinator(tmp_path)
    weights = _weights(tmp_path / "weights")
    (weights / "tokenizer.json").write_text("{}", encoding="utf-8")
    dialog = ModelSetupDialog(coordinator)
    try:
        dialog.path.setText(str(weights)); dialog.port.setValue(15443)
        assert not (tmp_path / "vision.json").exists()
        dialog.save.click()
        _drain(dialog)
        assert dialog._job is None
        snapshot = load_formal_vision_configuration(tmp_path / "vision.json")
        managed = freeze_model_service(snapshot)
        assert managed is not None, "saved config must reference its managed profile"
        assert managed.profile()["model_path"] == str(weights.resolve())
        assert managed.profile()["port"] == 15443
        assert coordinator._runtime is None and coordinator._model_service is None
    finally:
        _drain(dialog); dialog.close(); coordinator.shutdown()


class _Delayed:
    def __init__(self, path):
        self.path = path
        self.started = threading.Event()
        self.release = threading.Event()

    def model_setup_status(self):
        return {"config_path": str(self.path), "config_exists": False, "default_port": 13244}

    def configure_vista_model(self, **kwargs):
        self.started.set()
        assert self.release.wait(2)
        return {"status": "configured_unverified"}


def test_thread_finished_before_gui_delivery_still_releases_job(tmp_path):
    app = ensure_application(); coordinator = _Delayed(tmp_path / "vision.json")
    dialog = ModelSetupDialog(coordinator)
    try:
        dialog.path.setText(str(tmp_path)); dialog.save.click()
        assert coordinator.started.wait(1)
        job = dialog._job
        coordinator.release.set()
        assert job.wait(2000)
        _drain(dialog)
        assert dialog._job is None
    finally:
        coordinator.release.set(); _drain(dialog); dialog.close()


def test_modal_reject_cannot_close_while_configuration_is_writing(tmp_path):
    app = ensure_application(); coordinator = _Delayed(tmp_path / "vision.json")
    dialog = ModelSetupDialog(coordinator); dialog.show()
    try:
        dialog.path.setText(str(tmp_path)); dialog.save.click()
        assert coordinator.started.wait(1)
        dialog.reject()
        assert dialog.isVisible(), "Escape/reject must not destroy a running worker"
    finally:
        coordinator.release.set(); _drain(dialog); dialog.close()


def test_missing_tokenizer_payload_rejects_without_publishing(tmp_path):
    from app.desktop_review.model_setup import initialize_vista_configuration, ModelSetupError
    weights = _weights(tmp_path / "weights")
    (weights / "tokenizer.json").unlink()
    with pytest.raises(ModelSetupError, match="model_setup_model_metadata_invalid"):
        initialize_vista_configuration(tmp_path / "vision.json", weights)
    assert not (tmp_path / "vision.json").exists()


def test_first_use_existing_symlink_does_not_create_referent(tmp_path):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from tests.test_native_model_setup_coordinator import _Facade, _Host
    target = tmp_path / "absent.json"; link = tmp_path / "vision.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Windows symlink creation permission unavailable")
    coordinator = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), vision_config_path=link)
    try:
        assert coordinator.model_setup_status()["config_exists"] is True
        with pytest.raises(Exception, match="model_setup_config_exists"):
            coordinator.configure_vista_model(model_directory=str(tmp_path))
        assert not target.exists()
    finally:
        coordinator.shutdown()


def test_typed_setup_error_has_safe_actionable_message():
    from app.desktop_review.model_setup import ModelSetupError
    error = ModelSetupError("model_setup_port_invalid", "端口无效")
    assert error.message == "端口无效"


def test_stage_cleanup_failure_is_reported_not_silent_success(tmp_path, monkeypatch):
    from app.desktop_review import model_setup as setup
    original = Path.unlink
    def locked(path, *args, **kwargs):
        if path.suffix == ".stage":
            raise PermissionError("synthetic cleanup lock")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(setup.ModelSetupError, match="model_setup_cleanup_pending"):
        setup._publish_exclusive(tmp_path / "config.json", b"{}")


def test_committed_config_keeps_profile_when_its_stage_cleanup_fails(tmp_path, monkeypatch):
    from app.desktop_review import model_setup as setup
    original = Path.unlink
    def locked(path, *args, **kwargs):
        if path.name.startswith(".vision.json.") and path.suffix == ".stage":
            raise PermissionError("synthetic config stage lock")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    config = tmp_path / "vision.json"
    with pytest.raises(setup.ModelSetupError, match="model_setup_cleanup_pending"):
        setup.initialize_vista_configuration(config, _weights(tmp_path / "weights"))
    snapshot = load_formal_vision_configuration(config)
    assert freeze_model_service(snapshot) is not None


def test_uncommitted_profile_cleanup_failure_is_explicit(tmp_path, monkeypatch):
    from app.desktop_review import model_setup as setup
    original_link, original_unlink = setup.os.link, Path.unlink
    config = tmp_path / "vision.json"
    def denied(stage, destination):
        if destination == config:
            raise PermissionError("synthetic config write denial")
        return original_link(stage, destination)
    def locked(path, *args, **kwargs):
        if path.parent.name == "model_profiles" and path.suffix == ".json":
            raise PermissionError("synthetic profile lock")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(setup.os, "link", denied)
    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(setup.ModelSetupError, match="model_setup_cleanup_pending"):
        setup.initialize_vista_configuration(config, _weights(tmp_path / "weights"))
    assert not config.exists()
    assert len(list((tmp_path / "model_profiles").glob("*.json"))) == 1


def test_stage_name_collision_does_not_delete_preexisting_file(tmp_path, monkeypatch):
    from app.desktop_review import model_setup as setup
    monkeypatch.setattr(setup.secrets, "token_hex", lambda _size: "collision")
    stage = tmp_path / ".config.json.collision.stage"
    stage.write_bytes(b"preexisting-content")
    with pytest.raises(setup.ModelSetupError):
        setup._publish_exclusive(tmp_path / "config.json", b"{}")
    assert stage.read_bytes() == b"preexisting-content"
    assert not (tmp_path / "config.json").exists()


def test_cleanup_pending_disables_repeat_save(tmp_path):
    from app.desktop_review.model_setup import ModelSetupError
    from tests.test_native_model_setup_dialog import C
    class Pending(C):
        def configure_vista_model(self, **kwargs):
            raise ModelSetupError("model_setup_cleanup_pending", "清理未完成")
    app = ensure_application(); dialog = ModelSetupDialog(Pending())
    try:
        dialog.path.setText(str(tmp_path)); dialog.save.click(); _drain(dialog)
        assert not dialog.save.isEnabled()
        assert dialog.close_button.isEnabled()
    finally:
        _drain(dialog); dialog.close()


def test_unknown_worker_error_is_sanitized_and_manual_retry_works(tmp_path):
    from tests.test_native_model_setup_dialog import C
    class Failing(C):
        def configure_vista_model(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("secret-test-value should not be displayed")
            return {"status": "configured_unverified"}
    app = ensure_application(); coordinator = Failing(); dialog = ModelSetupDialog(coordinator)
    try:
        dialog.path.setText(str(tmp_path)); dialog.save.click(); _drain(dialog)
        assert "secret-test-value" not in dialog.status.text()
        assert "traceback" not in dialog.status.text().lower()
        assert dialog.save.isEnabled()
        dialog.save.click(); _drain(dialog)
        assert len(coordinator.calls) == 2 and not dialog.save.isEnabled()
    finally:
        _drain(dialog); dialog.close()
