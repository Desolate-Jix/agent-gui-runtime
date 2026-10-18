"""原生单步窗口离屏行为；仅使用明确标注的合成截图和替代 coordinator。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPixmapItem, QGraphicsRectItem, QMessageBox

from app.desktop_review.window import ensure_application


FIXTURES = Path(__file__).parent / "fixtures"


def _review():
    now = datetime.now(timezone.utc)
    return {
        "phase": "pending_review", "confirmation_id": "grounded-confirmation." + "a" * 64,
        "preview": json.loads((FIXTURES / "native_grounded_preview.json").read_text(encoding="utf-8")),
        "requested_at": now.isoformat(), "expires_at": (now + timedelta(seconds=300)).isoformat(),
        "owner_is_current": True, "png_bytes": (FIXTURES / "native_grounded_preview.png").read_bytes(),
    }


def _scroll_review():
    """从完整 preview 合约生成已审核滚动快照，不绕过 widget 校验。"""
    from app.agent.grounded_action_preview import _content_sha
    from app.agent.reviewed_workflow_replay import _review_selection_hash, _semantic_hash

    view = _review()
    preview = view["preview"]
    parameters = {
        "contract_version": "reviewed_scroll_parameters_v1",
        "target_container_id": "scroll-pane",
        "axis": "vertical",
        "direction": "down",
        "wheel_clicks": 2,
        "unit": "wheel_detent",
    }
    action = preview["current_observation"]["available_actions"][0]
    action.update(
        action_id="scroll_region",
        semantic_action="scroll_region",
        requires_user_confirmation=True,
        risk_level="medium",
        scroll_parameters=deepcopy(parameters),
    )
    selection = preview["review_selection"]
    selection.update(
        transition_id="scroll_region",
        semantic_action="scroll_region",
        requires_user_confirmation=True,
        scroll_parameters=deepcopy(parameters),
    )
    selection_hash = _review_selection_hash(selection)
    selection["review_selection_sha256"] = selection_hash
    selection["selection_sha256"] = selection_hash
    ground = preview["grounding_preview"]
    ground.update(
        transition_id="scroll_region",
        semantic_action="scroll_region",
        scroll_parameters=deepcopy(parameters),
        review_selection_sha256=selection_hash,
        gate_selection_sha256=selection_hash,
    )
    ground["preview_sha256"] = _semantic_hash(ground, excluded={"preview_sha256"})
    preview["intent_id"] = "intent.scroll-region"
    preview["content_sha256"] = _content_sha(preview)
    return view


class _Coordinator:
    def __init__(self):
        self.view = _review()
        self.calls = []
        self.fail_cancel = False
        self.hold = None
        self.entered = threading.Event()

    def inventory(self):
        self.calls.append("inventory")
        preview = self.view["preview"]
        return {"assets": [{"asset_id": preview["workflow"]["asset_id"],
                            "content_sha256": preview["workflow"]["asset_content_sha256"],
                            "application": "synthetic", "display_name": "合成测试流程"}],
                "windows": [{"handle": preview["target_window_handle"], "process_id": preview["target_process_id"],
                             "title": "<b>合成目标窗口</b>", "process_name": "fixture.exe"}]}

    def prepare(self, **selection):
        self.calls.append(("prepare", selection))
        self.entered.set()
        if self.hold is not None:
            assert self.hold.wait(5)
        action = self.view["preview"]["grounding_preview"]
        return {"phase": "observed", "session_id": self.view["preview"]["session_id"],
                "actions": [{"action_id": action["transition_id"], "semantic_action": action["semantic_action"], "target": action["element_ref"]}]}

    def request_review(self, *, action_id):
        self.calls.append(("review", action_id))
        return deepcopy(self.view)

    def approve(self, **identity):
        self.calls.append(("approve", identity))
        result = deepcopy(self.view)
        result["phase"] = "approved"
        return result

    def execute(self, *, confirmation_id):
        self.calls.append(("execute", confirmation_id))
        return {"contract_version": "native_single_step_response_v1", "confirmation_id": confirmation_id,
                "artifact_is_authorization": False, "kind": "decision",
                "payload": {"status": "REJECTED", "reason_code": "grounded_confirmation_stale", "confirmation_id": confirmation_id}}

    def cancel(self):
        self.calls.append("cancel")
        if self.fail_cancel:
            raise RuntimeError("synthetic-private-secret")
        return {"phase": "idle", "cleanup_verified": True}

    def cancel_waiting(self):
        self.calls.append("cancel_waiting")
        if self.hold is not None:
            self.hold.set()


def _wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    app = ensure_application()
    while not predicate():
        assert time.monotonic() < deadline, "Qt operation timed out"
        app.processEvents()
        time.sleep(.005)
    app.processEvents()


def _idle(dialog):
    _wait(lambda: not dialog._jobs)


def _click(button, dialog):
    assert button.isEnabled()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    _idle(dialog)


def _prepared_dialog(coordinator=None):
    from app.desktop_review.single_step_dialog import SingleStepDialog
    ensure_application()
    coordinator = coordinator or _Coordinator()
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    _click(dialog.refresh_button, dialog)
    assert dialog.asset_selector.currentIndex() == -1
    assert dialog.window_selector.currentIndex() == -1
    dialog.asset_selector.setCurrentIndex(0)
    dialog.window_selector.setCurrentIndex(0)
    _click(dialog.prepare_button, dialog)
    dialog.action_selector.setCurrentIndex(0)
    _click(dialog.review_button, dialog)
    return dialog, coordinator


def test_verified_png_bbox_and_crosshair_are_readonly_original_pixels():
    from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
    ensure_application()
    widget = GroundedPreviewWidget()
    view = _review()
    widget.set_review(view)
    items = widget.view.scene().items()
    pixmap = next(item for item in items if isinstance(item, QGraphicsPixmapItem))
    assert (pixmap.pixmap().width(), pixmap.pixmap().height()) == (1440, 900)
    bbox = next(item for item in items if isinstance(item, QGraphicsRectItem))
    expected = deepcopy(view["preview"]["grounding_preview"]["bbox"])
    assert (bbox.pos().x(), bbox.pos().y(), bbox.rect().width(), bbox.rect().height()) == tuple(expected[key] for key in ("x", "y", "w", "h"))
    assert not bbox.flags() & QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
    assert not widget.view.isInteractive()
    cross = [item.line() for item in items if isinstance(item, QGraphicsLineItem)]
    assert len(cross) == 2
    point = view["preview"]["grounding_preview"]["click_point"]
    assert all((line.x1()+line.x2())/2 == point["x"] and (line.y1()+line.y2())/2 == point["y"] for line in cross)
    text = widget.metadata_text.toPlainText()
    for value in (view["confirmation_id"], str(view["preview"]["target_window_handle"]), view["preview"]["workflow"]["asset_content_sha256"], "Gate", "capture", "confidence", "score_margin"):
        assert value in text
    assert widget.review == view
    view["preview"]["grounding_preview"]["bbox"]["x"] = 0
    assert widget.review["preview"]["grounding_preview"]["bbox"] == expected
    widget.close()


def test_scroll_preview_shows_reviewed_container_direction_detents_and_unit():
    from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget

    ensure_application()
    widget = GroundedPreviewWidget()
    widget.set_review(_scroll_review())
    try:
        text = widget.metadata_text.toPlainText()
        for value in ("scroll-pane", "向下", "2", "wheel_detent", "滚动位置"):
            assert value in text
    finally:
        widget.close()


@pytest.mark.parametrize("damage", ["pixels", "identity", "owner", "authority", "geometry", "ttl", "truncated"])
def test_bad_review_clears_old_image_and_never_leaves_actionable_overlay(damage):
    from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
    ensure_application()
    widget = GroundedPreviewWidget()
    view = _review()
    widget.set_review(view)
    if damage == "pixels": view["png_bytes"] += b"tampered"
    elif damage == "identity": view["confirmation_id"] = "foreign"
    elif damage == "owner": view["owner_is_current"] = False
    elif damage == "authority": view["preview"]["grants_action_authority"] = True
    elif damage == "geometry": view["preview"]["grounding_preview"]["bbox"]["x"] = 999999
    elif damage == "ttl": view["expires_at"] = view["requested_at"]
    else: view["png_bytes"] = view["png_bytes"][:24]
    with pytest.raises(ValueError):
        widget.set_review(view)
    assert widget.review is None
    assert not widget.view.scene().items()
    widget.close()


def test_native_workflow_separates_approval_and_one_explicit_execution(monkeypatch):
    dialog, coordinator = _prepared_dialog()
    assert dialog.approve_button.isEnabled()
    assert not dialog.execute_button.isEnabled()
    assert not dialog.asset_selector.isEnabled()
    _click(dialog.approve_button, dialog)
    assert not any(isinstance(call, tuple) and call[0] == "execute" for call in coordinator.calls)
    assert dialog.execute_button.isEnabled()
    assert not dialog.execute_button.autoDefault()
    defaults = []
    def confirm(*args):
        defaults.append(args[-1])
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", confirm)
    _click(dialog.execute_button, dialog)
    assert defaults == [QMessageBox.StandardButton.Cancel]
    assert sum(isinstance(call, tuple) and call[0] == "execute" for call in coordinator.calls) == 1
    assert not dialog.execute_button.isEnabled() and not dialog.approve_button.isEnabled()
    assert "REJECTED" in dialog.receipt_text.toPlainText()
    assert not dialog.prepare_button.isEnabled()
    _click(dialog.cancel_button, dialog)
    assert dialog.preview_widget.review is None
    dialog.close()


def test_cancelled_final_prompt_does_not_execute(monkeypatch):
    dialog, coordinator = _prepared_dialog()
    _click(dialog.approve_button, dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    _click(dialog.execute_button, dialog)
    assert dialog.execute_button.isEnabled()
    assert not any(isinstance(call, tuple) and call[0] == "execute" for call in coordinator.calls)
    _click(dialog.cancel_button, dialog)
    dialog.close()


@pytest.mark.parametrize("operation", ["approve", "execute"])
def test_foreground_handoff_is_prominent_and_cannot_double_dispatch(monkeypatch, tmp_path, operation):
    dialog, coordinator = _prepared_dialog()
    from app.desktop_review.theme import apply_review_theme
    apply_review_theme(dialog)
    released, entered = threading.Event(), threading.Event()
    original = getattr(coordinator, operation)
    def waiting(**kwargs):
        entered.set()
        assert released.wait(5)
        return original(**kwargs)
    if operation == "execute":
        _click(dialog.approve_button, dialog)
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(coordinator, operation, waiting)
    button = dialog.approve_button if operation == "approve" else dialog.execute_button
    try:
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        _wait(entered.is_set)
        assert dialog.status_label.geometry().bottom() < dialog.preview_widget.parentWidget().geometry().top()
        assert "Alt+Tab" in dialog.status_label.text()
        assert "合成目标窗口" in dialog.status_label.text()
        assert ("批准校验中" if operation == "approve" else "执行准备中") in button.text()
        assert not dialog.execute_button.isEnabled() and not dialog.approve_button.isEnabled()
        assert dialog.stop_wait_button.isEnabled()
        assert dialog.window_selector.height() >= dialog.window_selector.minimumSizeHint().height()
        screenshot = tmp_path / f"handoff-{operation}.png"
        assert dialog.grab().save(str(screenshot))
        print(f"handoff_screenshot={screenshot}")
        dialog._execute()
        dialog._approve()
        assert not any(isinstance(call, tuple) and call[0] == operation for call in coordinator.calls)
        released.set()
        _idle(dialog)
        assert sum(isinstance(call, tuple) and call[0] == operation for call in coordinator.calls) == 1
        if operation == "approve":
            assert dialog.execute_button.isEnabled()
            assert dialog.approve_button.text() == "批准本次预检"
    finally:
        released.set()
        _idle(dialog)
        dialog.close()
        _idle(dialog)


def test_cleanup_failure_retains_dialog_and_sanitizes_private_exception():
    dialog, coordinator = _prepared_dialog()
    coordinator.fail_cancel = True
    dialog.close()
    _idle(dialog)
    assert dialog.isVisible()
    assert "synthetic-private-secret" not in dialog.status_label.text()
    assert dialog.preview_widget.review is not None
    assert not dialog.execute_button.isEnabled()
    coordinator.fail_cancel = False
    dialog.close()
    _idle(dialog)
    assert not dialog.isVisible()


def test_busy_close_keeps_job_alive_and_wait_cancel_is_out_of_band():
    from app.desktop_review.single_step_dialog import SingleStepDialog
    ensure_application()
    coordinator = _Coordinator()
    coordinator.hold = threading.Event()
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    _click(dialog.refresh_button, dialog)
    dialog.asset_selector.setCurrentIndex(0)
    dialog.window_selector.setCurrentIndex(0)
    QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(coordinator.entered.is_set)
    dialog.close()
    assert dialog.isVisible() and dialog._jobs
    QTest.mouseClick(dialog.stop_wait_button, Qt.MouseButton.LeftButton)
    _idle(dialog)
    assert "cancel_waiting" in coordinator.calls
    _click(dialog.cancel_button, dialog)
    dialog.close()


def test_old_response_and_wrong_approval_identity_fail_closed():
    dialog, coordinator = _prepared_dialog()
    current = dialog.preview_widget.review
    dialog._job_result(dialog._request_id - 1, {"garbage": True})
    assert dialog.preview_widget.review == current
    coordinator.view["confirmation_id"] = "grounded-confirmation." + "b" * 64
    _click(dialog.approve_button, dialog)
    assert not dialog.execute_button.isEnabled()
    assert dialog.preview_widget.review == current
    _click(dialog.cancel_button, dialog)
    dialog.close()


def test_expired_preview_is_visible_but_not_approvable():
    coordinator = _Coordinator()
    now = datetime.now(timezone.utc)
    coordinator.view["requested_at"] = (now - timedelta(seconds=400)).isoformat()
    coordinator.view["expires_at"] = (now - timedelta(seconds=100)).isoformat()
    dialog, coordinator = _prepared_dialog(coordinator)
    assert dialog.preview_widget.review is not None
    assert not dialog.approve_button.isEnabled() and not dialog.execute_button.isEnabled()
    assert "过期" in dialog.status_label.text()
    _click(dialog.cancel_button, dialog)
    dialog.close()


def test_malformed_execution_result_is_unknown_and_cannot_reenable_execute(monkeypatch):
    class InvalidResult(_Coordinator):
        def execute(self, **kwargs):
            super().execute(**kwargs)
            return {"kind": "receipt", "payload": {"pretend": "success"}}
    dialog, coordinator = _prepared_dialog(InvalidResult())
    _click(dialog.approve_button, dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    _click(dialog.execute_button, dialog)
    try:
        assert not dialog.execute_button.isEnabled()
        assert "未知" in dialog.status_label.text()
    finally:
        _click(dialog.cancel_button, dialog)
        dialog.close()


def test_toolbar_requires_injected_coordinator_and_respects_busy_state(monkeypatch):
    import app.desktop_review.window as window_module
    class Facade:
        def list_batches(self): return []
        def close(self): pass
    ensure_application()
    offline = window_module.ReviewMainWindow(Facade())
    assert hasattr(offline, "single_step_action")
    assert not offline.single_step_action.isEnabled()
    offline.close()
    coordinator = _Coordinator()
    window = window_module.ReviewMainWindow(Facade(), single_step=coordinator)
    assert window.single_step_action.isEnabled()
    window._set_busy(True)
    assert not window.single_step_action.isEnabled()
    window._set_busy(False)
    opened = []
    class Dialog:
        def __init__(self, received, parent): opened.append((received, parent))
        def setObjectName(self, name): pass
        def exec(self): return 0
        def deleteLater(self): pass
    monkeypatch.setattr(window_module, "SingleStepDialog", Dialog)
    window.single_step_action.trigger()
    assert opened == [(coordinator, window)]
    window.close()


def test_preview_layout_prioritizes_image_over_hash_metadata():
    from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
    ensure_application()
    widget = GroundedPreviewWidget()
    widget.resize(1050, 550)
    widget.set_review(_review())
    widget.show()
    ensure_application().processEvents()
    try:
        assert widget.view.width() > widget.metadata_text.width()
        assert widget.view.width() >= 600
    finally:
        widget.close()
