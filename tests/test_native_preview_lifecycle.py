"""实机测试启动器的过期界面回归；合成数据和替代协调器，无外部输入。"""
from datetime import datetime, timedelta, timezone
import threading
from pathlib import Path

from tests.test_desktop_single_step_dialog import _prepared_dialog, _idle, _wait


def test_live_runner_does_not_connect_expiry_to_close():
    import ast
    path = Path(__file__).resolve().parents[1] / ".superpowers/sdd/2026-09-11-preview-delivery/run_live_navigation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Call) and ast.unparse(node.func) == "timeout.timeout.connect"
                   and any(ast.unparse(arg) == "dialog.close" for arg in node.args) for node in ast.walk(tree))


def _expired(dialog):
    expires = datetime.now(timezone.utc) - timedelta(seconds=1)
    dialog.preview_widget._review["requested_at"] = (expires - timedelta(seconds=300)).isoformat()
    dialog.preview_widget._review["expires_at"] = expires.isoformat()
    return expires


def test_expiry_releases_once_but_keeps_window_and_reason_visible():
    from tests.native_preview_lifecycle_support import PreviewExpiryNotice
    dialog, coordinator = _prepared_dialog()
    try:
        notice = PreviewExpiryNotice(dialog, _expired(dialog))
        _idle(dialog)
        notice.tick()
        notice.tick()
        assert dialog.isVisible() and not dialog._has_owner
        assert coordinator.calls.count("cancel") == 1
        assert "已过期" in notice.label.text() and "已释放" in notice.label.text()
        assert not dialog.approve_button.isEnabled() and not dialog.execute_button.isEnabled()
        assert not any(isinstance(call, tuple) and call[0] == "execute" for call in coordinator.calls)
        dialog.close()
        assert not dialog.isVisible()
    finally:
        dialog.close()
        _idle(dialog)


def test_cleanup_failure_remains_visible_and_is_not_retried():
    from tests.native_preview_lifecycle_support import PreviewExpiryNotice
    dialog, coordinator = _prepared_dialog()
    coordinator.fail_cancel = True
    try:
        notice = PreviewExpiryNotice(dialog, _expired(dialog))
        _idle(dialog)
        notice.tick()
        notice.tick()
        assert dialog.isVisible() and dialog._has_owner
        assert coordinator.calls.count("cancel") == 1
        assert "未完成" in notice.label.text() and "操作失败" in dialog.status_label.text()
    finally:
        coordinator.fail_cancel = False
        dialog.close()
        _idle(dialog)


def test_expiry_waits_for_inflight_job_and_keeps_its_result():
    from tests.native_preview_lifecycle_support import PreviewExpiryNotice
    dialog, coordinator = _prepared_dialog()
    released, entered = threading.Event(), threading.Event()
    def inflight():
        entered.set()
        assert released.wait(5)
        return {"contract_version": "native_single_step_response_v1",
                "confirmation_id": coordinator.view["confirmation_id"], "artifact_is_authorization": False,
                "kind": "decision", "payload": {"status": "REJECTED", "reason_code": "grounded_confirmation_stale",
                                                "confirmation_id": coordinator.view["confirmation_id"]}}
    try:
        dialog._launch("execute", inflight)
        _wait(entered.is_set)
        notice = PreviewExpiryNotice(dialog, _expired(dialog))
        assert "等待当前操作" in notice.label.text()
        assert "cancel" not in coordinator.calls and "cancel_waiting" not in coordinator.calls
        released.set()
        _idle(dialog)
        notice.tick()
        assert "REJECTED" in dialog.receipt_text.toPlainText()
        assert "本次操作已返回" in notice.label.text()
        assert dialog.isVisible() and "cancel" not in coordinator.calls
    finally:
        released.set()
        _idle(dialog)
        dialog.close()
        _idle(dialog)


def test_unexpired_countdown_does_not_release_or_change_authority():
    from tests.native_preview_lifecycle_support import PreviewExpiryNotice
    dialog, coordinator = _prepared_dialog()
    try:
        before = dialog.preview_widget.review
        now = datetime.now(timezone.utc)
        notice = PreviewExpiryNotice(dialog, now + timedelta(seconds=60), clock=lambda: now)
        assert "01:00" in notice.label.text()
        assert "到期不会自动关窗" in notice.label.text()
        assert coordinator.calls.count("cancel") == 0
        assert dialog.preview_widget.review == before and dialog.approve_button.isEnabled()
        assert not dialog.execute_button.isEnabled()
    finally:
        dialog.close()
        _idle(dialog)


def test_expiry_uses_real_fresh_owner_cleanup_without_closing_native_panel(tmp_path):
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from app.desktop_review.theme import apply_review_theme
    from app.desktop_review.window import ensure_application
    from tests.test_native_fresh_coordinator import _coordinator, _request
    from tests.test_fresh_dispatch_graph import _close
    from tests.native_preview_lifecycle_support import PreviewExpiryNotice
    host, controller, backend, callsite, _scope, intent, binding, coordinator, _calls = _coordinator(tmp_path)
    dialog = None
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        pending = coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        ensure_application()
        dialog = SingleStepDialog(coordinator)
        apply_review_theme(dialog)
        dialog.show()
        dialog._read_fresh_review()
        _idle(dialog)
        expires = datetime.fromisoformat(pending["expires_at"].replace("Z", "+00:00"))
        notice = PreviewExpiryNotice(dialog, expires, clock=lambda: expires + timedelta(seconds=1))
        _idle(dialog)
        notice.tick()
        state = coordinator.fresh_runtime_status(expected_learning_binding=binding)
        assert state["claim_phase"] == "grounded_confirmation_closed"
        assert coordinator.learning_runtime_state()["phase"] == "idle" and state.get("receipt") is None
        assert backend.commands == [] and dialog.isVisible() and not dialog._has_owner
        assert notice.snapshot()["state"] == "expired_released"
        assert dialog.grab().save(str(tmp_path / "expired-fresh-panel.png"))
        print(f"expiry_screenshot={tmp_path / 'expired-fresh-panel.png'}")
    finally:
        if dialog is not None:
            dialog.close()
            _idle(dialog)
        coordinator.shutdown()
        _close(host, controller)
