"""原生准备、取消、关闭到模型拥有者的隔离接线。"""

import json
from threading import Event, Thread, get_ident

import pytest

from tests.test_formal_model_service import _configuration, backend
from tests.test_native_single_step_coordinator import _Facade, _Host, _Runtime, _Windows


def _coordinator(tmp_path, monkeypatch, *, runtime=None):
    from app.desktop_review import single_step_coordinator as module

    snapshot, _ = _configuration(tmp_path)
    windows = _Windows()
    runtime = runtime or _Runtime()
    calls = []

    def factory(**kwargs):
        calls.append(("factory", get_ident()))
        return runtime

    factory.window_manager = windows
    monkeypatch.setattr(module, "_production_runtime_factory", factory)
    co = module.NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(),
        vision_config_path=snapshot.path, thread_initializer=lambda: None, thread_finalizer=lambda: None)
    monkeypatch.setattr(co, "_check_runtime_environment", lambda: None)
    return co, windows, calls


def _prepare(co):
    return co.prepare(asset_id="asset-1", asset_content_sha256="a" * 64,
                      target_window_handle=41, target_process_id=7)


def test_native_prepare_waits_for_model_and_cancel_releases_same_owner(tmp_path, monkeypatch, backend):
    co, windows, calls = _coordinator(tmp_path, monkeypatch)
    backend.check_hook = lambda: calls.append(("model-check", get_ident()))
    try:
        assert _prepare(co)["phase"] == "observed"
        assert backend.starts
        assert calls[-1][0] == "factory"
        assert len({thread_id for _, thread_id in calls + windows.calls}) == 1
        assert sum(kind == "get" for kind, _ in windows.calls) >= 2
        assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
        assert len(backend.cleanups) == 1 and backend.scopes[0].closed
        assert co._model_service is None
    finally:
        co.shutdown()


def test_native_shutdown_closes_model_after_session_cleanup(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    _prepare(co)
    co.shutdown()
    assert len(backend.cleanups) == 1 and backend.scopes[0].closed


def test_native_cancel_loading_leaves_no_runtime_factory_or_unowned_service(tmp_path, monkeypatch, backend):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError

    co, _, calls = _coordinator(tmp_path, monkeypatch)
    backend.statuses = ["unreachable", "loading"]
    backend.check_hook = lambda: co.cancel_waiting() if backend.starts else None
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            _prepare(co)
        assert error.value.code == "model_service_cancelled"
        assert calls == []
        assert backend.scopes[0].closed and co._runtime is None
        assert not co._factory_outcome_unknown
        assert co.cancel()["cleanup_verified"] is True
    finally:
        co.shutdown()


def test_native_retains_model_cleanup_failure_and_retries_exact_owner(tmp_path, monkeypatch, backend):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError

    co, _, _ = _coordinator(tmp_path, monkeypatch)
    try:
        _prepare(co)
        owner = co._model_service
        backend.cleanup_status = "indeterminate"
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.cancel()
        assert error.value.code == "model_service_cleanup_pending"
        assert co._model_service is owner and not backend.scopes[0].closed
        backend.cleanup_status = "verified"
        assert co.cancel()["cleanup_verified"] is True
        assert backend.cleanups[0][0] == backend.cleanups[1][0]
    finally:
        backend.cleanup_status = "verified"
        co.shutdown()


def test_profile_failure_happens_before_window_binding(tmp_path, monkeypatch, backend):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError

    co, windows, _ = _coordinator(tmp_path, monkeypatch)
    (tmp_path / "profile.json").write_text("{}", encoding="utf-8")
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            _prepare(co)
        assert error.value.code == "model_service_profile_invalid"
        assert windows.calls == [] and backend.starts == []
        assert co._phase == "idle"
    finally:
        co.shutdown()


def test_loading_cannot_silently_bind_a_changed_target(tmp_path, monkeypatch, backend):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError

    co, windows, calls = _coordinator(tmp_path, monkeypatch)
    backend.check_hook = lambda: setattr(windows.window, "process_id", 8) if backend.starts else None
    try:
        with pytest.raises(NativeSingleStepCoordinatorError):
            _prepare(co)
        assert calls == [] and co._runtime is None
        assert co.cancel()["cleanup_verified"] is True
        assert backend.scopes[0].closed
    finally:
        co.shutdown()


def test_stop_wait_hint_distinguishes_request_cancellation_from_compute_stop(tmp_path, monkeypatch):
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from app.desktop_review.window import ensure_application

    application = ensure_application()
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    dialog = SingleStepDialog(co)
    try:
        assert "模型就绪" in dialog.stop_wait_button.toolTip()
        assert "服务端计算未确认停止" in dialog.stop_wait_button.toolTip()
        assert "受管本地模型" in dialog.stop_wait_button.toolTip()
    finally:
        dialog.deleteLater()
        co.shutdown()


def test_cancellation_after_admission_is_not_cleared_by_preparation(tmp_path, monkeypatch, backend):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError

    co, _, calls = _coordinator(tmp_path, monkeypatch)
    original = co._require_host_ready

    def admitted(**kwargs):
        original(**kwargs)
        co.cancel_waiting()

    monkeypatch.setattr(co, "_require_host_ready", admitted)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            _prepare(co)
        assert error.value.code == "foreground_wait_cancelled"
        assert backend.starts == [] and calls == []
    finally:
        co.shutdown()


def test_pending_model_cleanup_blocks_non_prepare_operations(tmp_path, monkeypatch, backend):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError

    co, _, _ = _coordinator(tmp_path, monkeypatch)
    try:
        _prepare(co)
        backend.cleanup_status = "indeterminate"
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.cancel()
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co._begin("observed")
        assert error.value.code == "model_service_cleanup_pending"
    finally:
        co._end()
        backend.cleanup_status = "verified"
        co.shutdown()
