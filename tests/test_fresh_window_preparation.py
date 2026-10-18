"""首次学习的窗口准备不依赖旧资产，系统输入和取图边界全部隔离。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.core.screenshot import CaptureVisibilityError, ScreenshotService
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from tests.test_desktop_window_preparation import _Coordinator, _wait
from tests.test_screenshot_passive_capture import _install_capture_fakes
from tests.test_window_preparation_authority import scene


@pytest.fixture
def fresh_host(tmp_path, monkeypatch, scene):
    manager, state, identity, _reader = scene
    monkeypatch.setattr("psutil.Process", lambda _pid: SimpleNamespace(
        exe=lambda: identity["executable_path"], create_time=lambda: identity["process_create_time"]))
    monkeypatch.setattr(manager, "list_visible_windows", lambda: [
        dict(handle=321, process_id=12, title="Synthetic editor", process_name="editor.exe")])
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "reviews", "fresh-window-preparation-test-token")
    host.start()
    co = NativeSingleStepCoordinator(tmp_path / "reviews", host.facade, host,
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    co._window_manager = manager
    try:
        yield co, manager, state, identity
    finally:
        co.shutdown()


def _preview(co):
    return co.preview_selected_window_preparation(target_window_handle=321, target_process_id=12)


def test_first_learning_focus_requires_no_asset_and_grants_no_input(fresh_host):
    co, _manager, state, identity = fresh_host
    preview = _preview(co)
    assert preview["source"] == "selected_window" and preview["mode"] == "focus"
    assert preview["identity"] == identity and preview["title"] == "Synthetic editor"
    assert "asset_id" not in preview and "asset_content_sha256" not in preview
    assert state.mutations == [] and co._runtime is None
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "focused" and result["window"]["handle"] == 321
    assert state.active == 321 and state.blocked == []
    assert co._runtime is None and co._prepared_window_identities == {}
    mutations = list(state.mutations)
    with pytest.raises(NativeSingleStepCoordinatorError, match="absent or consumed"):
        co.confirm_window_preparation(preview["preparation_id"])
    assert state.mutations == mutations


@pytest.mark.parametrize("change", ["expiry", "clear", "replace", "pid", "creation", "executable"])
def test_invalidated_fresh_preview_never_focuses(fresh_host, change):
    co, _manager, state, identity = fresh_host
    preview = _preview(co)
    if change == "expiry": co._window_preparations[preview["preparation_id"]]["expires_at"] = 0
    elif change == "clear": co.clear_window_preparation()
    elif change == "replace": _preview(co)
    elif change == "pid": co._window_preparations[preview["preparation_id"]]["identity"]["process_id"] = 99
    elif change == "creation": identity["process_create_time"] += 1
    else: identity["executable_path"] = "c:\\other\\app.exe"
    with pytest.raises(NativeSingleStepCoordinatorError):
        co.confirm_window_preparation(preview["preparation_id"])
    assert state.mutations == [] and co._runtime is None


@pytest.mark.parametrize("hwnd,pid", [(True, 12), (0, 12), (321, False), (321, 0), (321, 99)])
def test_invalid_selected_window_is_rejected_before_focus(fresh_host, hwnd, pid):
    co, _manager, state, _identity = fresh_host
    with pytest.raises(NativeSingleStepCoordinatorError) as error:
        co.preview_selected_window_preparation(target_window_handle=hwnd, target_process_id=pid)
    assert error.value.code == "window_preparation_identity_invalid"
    assert state.mutations == []


def test_failed_focus_has_no_capture_or_input_authority(fresh_host):
    co, manager, state, _identity = fresh_host
    state.fail = True
    preview = _preview(co)
    with pytest.raises(NativeSingleStepCoordinatorError) as error:
        co.confirm_window_preparation(preview["preparation_id"])
    assert error.value.code == "window_focus_unverified" and error.value.result_unknown
    assert state.active == 0 and state.blocked == [] and co._runtime is None
    with pytest.raises(PermissionError): manager.focus_bound_window()


def test_confirmed_fresh_focus_then_passive_capture_keeps_occlusion_guard(fresh_host, monkeypatch):
    from app.core import window_manager as wm
    co, manager, state, _identity = fresh_host
    # 模拟上层遮挡窗口；只在本地确认完成后改变 Z 序。
    monkeypatch.setattr(wm.win32gui, "GetTopWindow", lambda _: state.active or 999, raising=False)
    monkeypatch.setattr(wm.win32gui, "GetWindow", lambda *_: 321, raising=False)
    monitors = _install_capture_fakes(monkeypatch, manager=manager)
    service = ScreenshotService(window_manager=manager)
    with pytest.raises(CaptureVisibilityError, match="capture_window_occluded"):
        service.capture_window(save_image=False, focus_window=False)
    assert monitors == [] and state.mutations == []
    co.confirm_window_preparation(_preview(co)["preparation_id"])
    mutations = list(state.mutations)
    result = service.capture_window(save_image=False, focus_window=False)
    assert result["image_width"] == 800 and len(monitors) == 1
    assert state.mutations == mutations
    state.active = 0
    with pytest.raises(CaptureVisibilityError, match="capture_window_occluded"):
        service.capture_window(save_image=False, focus_window=False)
    assert len(monitors) == 1 and state.blocked == []


class _FreshCoordinator(_Coordinator):
    def preview_selected_window_preparation(self, **kwargs):
        self.calls.append(("fresh_preview", deepcopy(kwargs)))
        return {"contract_version": "native_window_preparation_v1", "source": "selected_window",
                "preparation_id": "fresh-1", "mode": "focus", "title": "Synthetic editor",
                "executable_path": r"C:\fixture\editor.exe", "expires_in_seconds": 60,
                "identity": {"target_window_handle": kwargs["target_window_handle"],
                             "process_id": kwargs["target_process_id"], "process_create_time": 123.5}}

    def confirm_window_preparation(self, preparation_id):
        self.calls.append(("confirm", preparation_id))
        return {"status": "focused", "window": {"handle": 321, "process_id": 12, "title": "Synthetic editor"}}


def _dispose_dialog(dialog):
    # 对齐正式 open_single_step 的主线程延迟销毁，不把无父窗口留给后续测试。
    _wait(lambda: not dialog._jobs)
    dialog.close()
    _wait(lambda: not dialog._jobs)
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("approved", [False, True])
def test_empty_workbench_can_preview_and_explicitly_confirm_fresh_focus(monkeypatch, approved):
    ensure_application()
    coordinator = _FreshCoordinator()
    dialog = SingleStepDialog(coordinator)
    seen = []
    def answer(box):
        seen.append(box.text())
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
        return QMessageBox.StandardButton.Yes if approved else QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "exec", answer)
    try:
        dialog._load_inventory({"assets": [], "windows": [
            dict(handle=321, process_id=12, title="Synthetic editor", process_name="editor.exe")]})
        assert not dialog.focus_window_button.isEnabled()
        dialog.window_selector.setCurrentIndex(0)
        assert dialog.focus_window_button.isEnabled()
        assert not dialog.prepare_button.isEnabled() and not dialog.launch_window_button.isEnabled()
        QTest.mouseClick(dialog.focus_window_button, Qt.MouseButton.LeftButton)
        _wait(lambda: bool(seen) and not dialog._jobs and dialog._queued_followup is None)
        assert ("fresh_preview", {"target_window_handle": 321, "target_process_id": 12}) in coordinator.calls
        assert [c for c in coordinator.calls if isinstance(c, tuple) and c[0] == "confirm"] == (
            [("confirm", "fresh-1")] if approved else [])
        assert "首次学习" in seen[0] and "None" not in seen[0]
        assert "Synthetic editor" in seen[0] and "321" in seen[0]
        assert not dialog._has_owner
        if approved:
            assert "重新截图学习" in dialog.status_label.text()
    finally:
        _dispose_dialog(dialog)


def test_ordinary_empty_panel_reaches_real_coordinator_with_only_os_boundary_faked(fresh_host, monkeypatch):
    co, _manager, state, _identity = fresh_host
    ensure_application()
    # 本测试只跳过依赖元数据探测；空资产库、宿主、串行协调器和 Qt 任务均为正式实现。
    monkeypatch.setattr(co, "_check_runtime_environment", lambda: None)
    monkeypatch.setattr(QMessageBox, "exec", lambda _: QMessageBox.StandardButton.Yes)
    dialog = SingleStepDialog(co)
    try:
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.window_selector.count() == 1 and not dialog._jobs)
        assert dialog.asset_selector.count() == 0
        dialog.window_selector.setCurrentIndex(0)
        QTest.mouseClick(dialog.focus_window_button, Qt.MouseButton.LeftButton)
        _wait(lambda: state.active == 321 and not dialog._jobs and dialog._queued_followup is None)
        assert "重新截图学习" in dialog.status_label.text()
        assert co._runtime is None and co._prepared_window_identities == {} and state.blocked == []
    finally:
        _dispose_dialog(dialog)
