"""实际 callsite／控制器／lease 的预检恢复；证据与 backend 均为被动替代。"""
from threading import get_ident

import pytest

from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from tests.test_native_grounded_image_material import grounded_image_runtime
from tests.test_live_runtime_composition_w3b import _WindowManager, _bound


def _coordinator(tmp_path, runtime):
    original_windows = runtime.service._window_manager
    factories = []

    class Windows:
        def list_visible_windows(self):
            return [{"handle": 4242, "process_id": 9001, "title": "Synthetic", "process_name": "fixture.exe"}]
        def bind_window_by_handle(self, handle):
            assert handle == 4242
            return self.get_bound_window()
        def get_bound_window(self):
            return original_windows.get_bound_window()

    windows = Windows()
    def factory(*, project_root, selection, window_manager):
        assert project_root == tmp_path.resolve() and selection == runtime.service._selection
        assert window_manager is windows
        factories.append(get_ident())
        return runtime.service
    factory.window_manager = windows
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path, "synthetic-recovery-reviewer", port=0)
    coordinator = NativeSingleStepCoordinator(tmp_path, host.facade, host, runtime_factory=factory,
                                              thread_initializer=lambda: None, thread_finalizer=lambda: None)
    host.start()
    asset = coordinator.inventory()["assets"][0]
    selection = {"asset_id": asset["asset_id"], "asset_content_sha256": asset["content_sha256"],
                 "target_window_handle": 4242, "target_process_id": 9001}
    return coordinator, host, factories, selection


def _finalize_test(coordinator, host):
    try:
        coordinator.shutdown()
    except Exception:
        # 仅清理失败回归留下的测试线程；不将它计为生产清理成功。
        host.close()
        coordinator._owner.close()


@pytest.mark.parametrize("next_action", ["cancel", "retry"])
def test_actual_failed_capture_can_release_or_explicitly_retry_without_new_runtime_owner(
    tmp_path, grounded_image_runtime, monkeypatch, next_action,
):
    runtime = grounded_image_runtime
    runtime.evidence._window_manager = _WindowManager(*[_bound() for _ in range(64)])
    original = runtime.evidence.create_initial
    calls = []
    def fail_once(**kwargs):
        calls.append(kwargs["session_id"])
        if len(calls) == 1:
            raise RuntimeError("synthetic capture failure before observation")
        return original(**kwargs)
    monkeypatch.setattr(runtime.evidence, "create_initial", fail_once)
    coordinator, host, factories, selection = _coordinator(tmp_path, runtime)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as failed:
            coordinator.prepare(**selection)
        assert failed.value.retry_preparation is True
        assert coordinator._runtime is runtime.service
        assert host.status()["phase"] == "ready" and len(calls) == 1
        assert all(backend.attempt_count == 0 for backend in runtime.backends)
        if next_action == "cancel":
            assert coordinator.cancel() == {"phase": "idle", "cleanup_verified": True}
            assert len(calls) == 1
            assert all(not controller._sessions for controller in runtime.controllers)
            assert coordinator._runtime is None and host.status()["phase"] == "ready"
        else:
            observed = coordinator.prepare(**selection)
            assert observed["phase"] == "observed" and len(calls) == 2
            assert len(factories) == 1 and factories[0] == coordinator._owner.thread_id
            assert coordinator._runtime is runtime.service
            assert coordinator.cancel() == {"phase": "idle", "cleanup_verified": True}
            assert len(calls) == 2
        # 释放后同一 HWND/PID 能再次真实创建准备会话，证明没有遗留阻塞 lease。
        prepared = coordinator.prepare(**selection)
        assert prepared["phase"] == "observed"
        assert coordinator.cancel() == {"phase": "idle", "cleanup_verified": True}
        assert all(backend.attempt_count == 0 for backend in runtime.backends)
        assert all(not controller._sessions for controller in runtime.controllers)
    finally:
        _finalize_test(coordinator, host)


def test_actual_unattached_cleanup_failure_keeps_host_ready_until_verified_shutdown(
    tmp_path, grounded_image_runtime, monkeypatch,
):
    runtime = grounded_image_runtime
    attempts = []
    def fail_capture(**kwargs):
        attempts.append(kwargs["session_id"])
        raise RuntimeError("synthetic capture failure")
    monkeypatch.setattr(runtime.evidence, "create_initial", fail_capture)
    coordinator, host, _factories, selection = _coordinator(tmp_path, runtime)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError):
            coordinator.prepare(**selection)
        real_cancel = runtime.service.cancel_local_preparation
        def unavailable():
            raise RuntimeError("synthetic cleanup verification unavailable")
        monkeypatch.setattr(runtime.service, "cancel_local_preparation", unavailable)
        with pytest.raises(NativeSingleStepCoordinatorError):
            coordinator.shutdown()
        assert host.status()["phase"] == "ready"
        assert coordinator._runtime is runtime.service and coordinator._owner._thread.is_alive()
        assert len(attempts) == 1
        monkeypatch.setattr(runtime.service, "cancel_local_preparation", real_cancel)
        coordinator.shutdown()
        assert host.status()["phase"] == "stopped"
        assert not coordinator._owner._thread.is_alive()
        assert len(attempts) == 1
        assert all(backend.attempt_count == 0 for backend in runtime.backends)
    finally:
        _finalize_test(coordinator, host)
