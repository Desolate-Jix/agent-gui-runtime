"""首次学习真实 owner 经原生 coordinator 的生命周期与清理边界。"""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from app.desktop_review.host import DesktopHostError
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from app.desktop_review.fresh_runtime_callsite import FreshRuntimeSelection
from tests.test_fresh_runtime_callsite import _callsite
from tests.test_fresh_dispatch_graph import _close


class _ForegroundWindows:
    def __init__(self):
        self.bound = SimpleNamespace(handle=4242, process_id=9001, is_active=True)
        self.binds = []

    def bind_window_by_handle(self, handle):
        self.binds.append(handle)
        return self.bound if handle == 4242 else None

    def get_bound_window(self):
        return self.bound


def _coordinator(tmp_path):
    host, owner, controller, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    windows = _ForegroundWindows()
    calls = []

    def factory(*, project_root, selection, window_manager, learning_binding, **kwargs):
        calls.append((project_root, selection, window_manager, learning_binding, kwargs))
        assert isinstance(selection, FreshRuntimeSelection)
        assert window_manager is windows
        assert learning_binding is binding
        return callsite

    factory.window_manager = windows
    binding = LearningRuntimeBinding(host.learning_segments, **scope)
    coordinator = NativeSingleStepCoordinator(
        host.fresh_learning.archive.project_root, host.facade, host,
        runtime_factory=factory, enable_agent_learning=False,
        thread_initializer=lambda: None, thread_finalizer=lambda: None,
    )
    host.start()
    return host, controller, backend, callsite, scope, intent, binding, coordinator, calls


def _request(prepared, intent):
    observation = prepared["observation"]
    return {**intent.to_dict(), "session_id": prepared["session_id"],
            "observation_id": observation["observation_id"]}


def test_fresh_prepare_review_approve_and_execute_use_same_owner_and_canonical_host(tmp_path):
    host, controller, backend, callsite, _scope, intent, binding, coordinator, calls = _coordinator(tmp_path)
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        assert prepared["phase"] == "observed" and prepared["actions"] == []
        assert len(calls) == 1 and calls[0][1].source is callsite._selection.source
        pending = coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        assert pending["source_kind"] == "fresh_learning"
        assert coordinator.current_fresh_review() == pending
        approved = coordinator.approve(confirmation_id=pending["confirmation_id"],
                                       preview_sha256=pending["preview"]["preview_sha256"])
        assert approved["phase"] == "approved" and approved["preview"] == pending["preview"]
        result = coordinator.execute(confirmation_id=pending["confirmation_id"])
        assert result["kind"] == "receipt" and len(backend.commands) == 1
        coordinator.cancel(expected_learning_binding=binding)
        snapshot = coordinator.fresh_runtime_status(expected_learning_binding=binding)
        assert snapshot["claim_phase"] == "terminal" and snapshot["receipt"] == result["payload"]
        with pytest.raises(NativeSingleStepCoordinatorError):
            coordinator.execute(confirmation_id=pending["confirmation_id"])
    finally:
        try:
            coordinator.shutdown()
        finally:
            _close(host, controller)


def test_fresh_delayed_cleanup_retains_owner_and_blocks_new_prepare_until_verified(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    host, controller, backend, callsite, _scope, intent, binding, coordinator, _calls = _coordinator(tmp_path)
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        entered, release = Event(), Event()
        original = callsite.cancel_grounded_review

        def delayed(*, session_id):
            entered.set()
            assert release.wait(10)
            return original(session_id=session_id)

        monkeypatch.setattr(callsite, "cancel_grounded_review", delayed)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(coordinator.cancel, expected_learning_binding=binding)
            assert entered.wait(10)
            other = LearningRuntimeBinding(host.learning_segments, binding.connection_id, binding.task_id, binding.segment_id)
            with pytest.raises(NativeSingleStepCoordinatorError) as blocked:
                coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=other)
            assert blocked.value.code == "lifecycle_busy"
            assert backend.commands == []
            release.set()
            assert future.result(timeout=15) == {"phase": "idle", "cleanup_verified": True}
    finally:
        try:
            coordinator.shutdown()
        finally:
            _close(host, controller)


def test_native_dialog_reads_persisted_agent_preview_and_denies_without_input(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from app.desktop_review.window import ensure_application
    import time

    host, controller, backend, callsite, _scope, intent, binding, coordinator, _calls = _coordinator(tmp_path)
    dialog = None
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        pending = coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        ensure_application()
        dialog = SingleStepDialog(coordinator)
        dialog.show()
        assert dialog.fresh_review_button.isEnabled()
        QTest.mouseClick(dialog.fresh_review_button, Qt.MouseButton.LeftButton)
        deadline = time.monotonic() + 10
        while dialog._jobs:
            assert time.monotonic() < deadline
            ensure_application().processEvents()
            time.sleep(.005)
        assert dialog.preview_widget.review == pending
        assert dialog.grab().save(str(tmp_path / "native-fresh-preview.png"))
        for operation in ("approve", "execute"):
            handoff = dialog._handoff_message(operation)
            assert "Alt+Tab" in handoff and "HWND 4242 / PID 9001" in handoff
            assert ("批准校验中" if operation == "approve" else "执行准备中") in handoff
        assert dialog.deny_button.isEnabled() and dialog.approve_button.isEnabled()
        QTest.mouseClick(dialog.deny_button, Qt.MouseButton.LeftButton)
        deadline = time.monotonic() + 35
        while dialog._jobs:
            assert time.monotonic() < deadline
            ensure_application().processEvents()
            time.sleep(.005)
        assert backend.commands == []
        assert "拒绝" in dialog.status_label.text()
    finally:
        if dialog is not None:
            dialog.close()
            # closeEvent 为当前 fresh owner 启动实际异步清理；必须耗尽其回调后才关闭 owner。
            assert dialog._jobs
            deadline = time.monotonic() + 35
            while dialog._jobs:
                assert time.monotonic() < deadline
                ensure_application().processEvents()
                time.sleep(.005)
            assert dialog._closing_verified and not dialog.isVisible()
            # finished 信号先于线程对象销毁；验证没有存活 QThread 后显式处理 DeferredDelete。
            from PySide6.QtCore import QCoreApplication, QEvent, QThread
            jobs = dialog.findChildren(QThread)
            assert all(not job.isRunning() and job.wait(0) for job in jobs)
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            ensure_application().processEvents()
        assert coordinator.learning_runtime_state()["phase"] == "idle"
        coordinator.shutdown()
        _close(host, controller)


def test_actual_host_timeout_cannot_replace_retained_owner(tmp_path, monkeypatch):
    from threading import Event

    host, controller, backend, callsite, _scope, intent, binding, coordinator, calls = _coordinator(tmp_path)
    entered, release = Event(), Event()
    original_cancel = callsite.cancel_grounded_review
    original_release = host.release_grounded_runtime
    def delayed(*, session_id):
        entered.set()
        assert release.wait(15)
        return original_cancel(session_id=session_id)
    def short_release(*, confirmation_id, timeout=5):
        return original_release(confirmation_id=confirmation_id, timeout=.05)
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        monkeypatch.setattr(callsite, "cancel_grounded_review", delayed)
        monkeypatch.setattr(host, "release_grounded_runtime", short_release)
        with pytest.raises(NativeSingleStepCoordinatorError) as timed_out:
            coordinator.cancel(expected_learning_binding=binding)
        assert timed_out.value.code == "shutdown_timeout"
        assert entered.wait(2)
        assert coordinator._runtime is callsite and coordinator._learning_binding is binding
        assert coordinator.learning_runtime_state()["busy"] is False
        with pytest.raises(NativeSingleStepCoordinatorError):
            coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        assert len(calls) == 1 and backend.commands == []
        release.set()
        monkeypatch.setattr(host, "release_grounded_runtime", original_release)
        assert coordinator.cancel(expected_learning_binding=binding)["cleanup_verified"] is True
        assert controller._sessions == {} and backend.commands == []
    finally:
        release.set()
        monkeypatch.setattr(host, "release_grounded_runtime", original_release)
        coordinator.shutdown()
        _close(host, controller)


def test_revoked_source_cannot_block_trusted_native_cleanup(tmp_path):
    host, controller, backend, callsite, scope, intent, binding, coordinator, calls = _coordinator(tmp_path)
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        host._service.reviewer_call("fresh-graph-reviewer", "revoke_connection", {
            "connection_id": scope["connection_id"], "idempotency_key": "revoke.native"})
        assert coordinator.cancel(expected_learning_binding=binding)["cleanup_verified"] is True
        assert controller._sessions == {} and backend.commands == []
        state = coordinator.fresh_runtime_status(expected_learning_binding=binding)
        assert state["status"] == "snapshot_unavailable" and "screenshot" not in state
    finally:
        coordinator.shutdown()
        _close(host, controller)


@pytest.mark.parametrize("failure", ["image", "publication_response"])
def test_fresh_publication_failure_retains_session_cleanup_path(tmp_path, monkeypatch, failure):
    host, controller, backend, callsite, scope, intent, binding, coordinator, calls = _coordinator(tmp_path)
    prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
    original = callsite.request_grounded_confirmation
    def lost(*args, **kwargs):
        if failure == "publication_response":
            original(*args, **kwargs)
        raise OSError("isolated loss after durable publication")
    monkeypatch.setattr(callsite, "get_local_grounded_image" if failure == "image" else "request_grounded_confirmation", lost)
    try:
        with pytest.raises(Exception):
            coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        assert controller._intent_claim_store.find_for_observation(session_id=prepared["session_id"],
            observation_id=prepared["observation"]["observation_id"]).phase == "grounded_confirmation_pending"
        assert coordinator.cancel(expected_learning_binding=binding)["cleanup_verified"] is True
        assert controller._sessions == {} and backend.commands == []
    finally:
        # 失败用例的模拟 owner 仍须释放，不能把租约留给下一项测试。
        if controller._sessions:
            controller.cancel_grounded_review(session_id=prepared["session_id"])
            coordinator._clear()
        coordinator.shutdown()
        _close(host, controller)
