"""真实原生协调器、Qt 值输入与 Controller 发布闭环，系统边界全部合成。"""
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from shiboken6 import isValid
from types import SimpleNamespace

from app.agent.reviewed_workflow_asset import content_sha256
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from test_text_local_publication import local, local_fixed
from app.desktop_review.host import DesktopReviewHost
from tests.test_desktop_single_step_dialog import _click, _idle, _wait


def _host(tmp_path):
    host = DesktopReviewHost(tmp_path / "host.sqlite", tmp_path / "review", "reviewer-token-native-roundtrip", port=0)
    host.start()
    return host


def _dispose_owned_dialog(dialog):
    # 测试直接拥有无父窗口；close 只隐藏，必须排空延迟销毁后才能进入下一项。
    assert not dialog._jobs
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    ensure_application().processEvents()
    assert not isValid(dialog)


def test_native_variable_entry_reaches_exact_local_preview_and_cancel_releases_owner(local, tmp_path):
    ensure_application()
    local.service.cancel_prepared_session(session_id=local.observation.session_id)
    asset = local.asset
    facade = SimpleNamespace(list_reviewed_assets=lambda: [{"asset_id": asset["asset_id"],
        "content_sha256": content_sha256(asset), "application": asset["application"], "display_name": "合成填写"}])
    def factory(**_kwargs):
        return local.service
    factory.window_manager = local.windows
    host = DesktopReviewHost(tmp_path / "host.sqlite", tmp_path / "review", "reviewer-token-native-roundtrip", port=0)
    host.start()
    coordinator = NativeSingleStepCoordinator(local.root, facade, host, runtime_factory=factory,
        thread_initializer=lambda: None, thread_finalizer=lambda: None, foreground_timeout=.1)
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        _click(dialog.refresh_button, dialog)
        dialog.asset_selector.setCurrentIndex(0)
        dialog.window_selector.setCurrentIndex(0)
        _click(dialog.prepare_button, dialog)
        assert dialog._phase == "observed", dialog.status_label.text()
        dialog.action_selector.setCurrentIndex(0)
        _click(dialog.review_button, dialog)
        _wait(lambda: getattr(dialog, "_text_input_dialog", None) is not None)
        editor = dialog._text_input_dialog
        assert local.claims.list_unresolved_claims() == ()
        editor.text_editor.setPlainText("本次真实控件值\n第二行")
        QTest.mouseClick(editor.continue_button, Qt.MouseButton.LeftButton)
        _idle(dialog)
        view = dialog.preview_widget.review
        assert view is not None, dialog.status_label.text()
        assert view["text_input_local"].text == "本次真实控件值\n第二行"
        assert dialog.preview_widget.text_value_editor.toPlainText() == "本次真实控件值\n第二行"
        assert dialog.preview_widget.text_value_editor.isReadOnly()
        assert not dialog.execute_button.isEnabled()
        assert local.backend.attempt_count == 0
        _click(dialog.approve_button, dialog)
        assert dialog.execute_button.isEnabled()
        assert dialog.preview_widget.review["phase"] == "approved"
        assert local.backend.attempt_count == 0
        _click(dialog.cancel_button, dialog)
        assert coordinator._runtime is None
    finally:
        dialog.close()
        _idle(dialog)
        coordinator.shutdown()
        host.close()
        _dispose_owned_dialog(dialog)



def test_native_cancel_before_value_has_no_claim_and_does_not_reuse_stale_input(local, tmp_path):
    ensure_application()
    local.service.cancel_prepared_session(session_id=local.observation.session_id)
    asset = local.asset
    facade = SimpleNamespace(list_reviewed_assets=lambda: [{"asset_id": asset["asset_id"],
        "content_sha256": content_sha256(asset), "application": asset["application"], "display_name": "合成填写"}])
    def factory(**_kwargs):
        return local.service
    factory.window_manager = local.windows
    host = _host(tmp_path)
    coordinator = NativeSingleStepCoordinator(local.root, facade, host, runtime_factory=factory,
        thread_initializer=lambda: None, thread_finalizer=lambda: None, foreground_timeout=.1)
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        _click(dialog.refresh_button, dialog)
        dialog.asset_selector.setCurrentIndex(0)
        dialog.window_selector.setCurrentIndex(0)
        _click(dialog.prepare_button, dialog)
        dialog.action_selector.setCurrentIndex(0)
        _click(dialog.review_button, dialog)
        _wait(lambda: getattr(dialog, "_text_input_dialog", None) is not None)
        editor = dialog._text_input_dialog
        editor.text_editor.setPlainText("被取消的旧值")
        editor.reject()
        _idle(dialog)
        assert local.claims.list_unresolved_claims() == ()
        assert local.backend.attempt_count == 0
        _click(dialog.review_button, dialog)
        _wait(lambda: getattr(dialog, "_text_input_dialog", None) is not None)
        editor = dialog._text_input_dialog
        assert editor.text_editor.toPlainText() == ""
        editor.text_editor.setPlainText("取消后新值")
        QTest.mouseClick(editor.continue_button, Qt.MouseButton.LeftButton)
        _idle(dialog)
        assert dialog.preview_widget.review["text_input_local"].text == "取消后新值"
        assert local.backend.attempt_count == 0
    finally:
        dialog.close()
        _idle(dialog)
        coordinator.shutdown()
        host.close()
        _dispose_owned_dialog(dialog)


def test_native_fixed_source_reaches_exact_local_preview(local_fixed, tmp_path):
    ensure_application()
    local_fixed.service.cancel_prepared_session(session_id=local_fixed.observation.session_id)
    asset = local_fixed.asset
    facade = SimpleNamespace(list_reviewed_assets=lambda: [{"asset_id": asset["asset_id"],
        "content_sha256": content_sha256(asset), "application": asset["application"], "display_name": "固定来源"}])
    def factory(**_kwargs):
        return local_fixed.service
    factory.window_manager = local_fixed.windows
    host = _host(tmp_path)
    coordinator = NativeSingleStepCoordinator(local_fixed.root, facade, host, runtime_factory=factory,
        thread_initializer=lambda: None, thread_finalizer=lambda: None, foreground_timeout=.1)
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        _click(dialog.refresh_button, dialog)
        dialog.asset_selector.setCurrentIndex(0)
        dialog.window_selector.setCurrentIndex(0)
        _click(dialog.prepare_button, dialog)
        dialog.action_selector.setCurrentIndex(0)
        _click(dialog.review_button, dialog)
        _wait(lambda: getattr(dialog, "_text_input_dialog", None) is not None)
        editor = dialog._text_input_dialog
        assert editor.text_editor.toPlainText() == "原始中文\n固定来源"
        assert editor.text_editor.isReadOnly()
        QTest.mouseClick(editor.continue_button, Qt.MouseButton.LeftButton)
        _idle(dialog)
        view = dialog.preview_widget.review
        assert view["text_input_local"].text == "原始中文\r\n固定来源"
        assert dialog.preview_widget.text_value_editor.toPlainText() == "原始中文\n固定来源"
        assert not dialog.execute_button.isEnabled()
        _click(dialog.approve_button, dialog)
        assert dialog.preview_widget.review["phase"] == "approved"
        assert dialog.preview_widget.review["text_input_local"].text == "原始中文\r\n固定来源"
        assert dialog.execute_button.isEnabled()
        assert local_fixed.backend.attempt_count == 0
        _click(dialog.cancel_button, dialog)
        assert coordinator._runtime is None
    finally:
        dialog.close()
        _idle(dialog)
        coordinator.shutdown()
        host.close()
        _dispose_owned_dialog(dialog)
