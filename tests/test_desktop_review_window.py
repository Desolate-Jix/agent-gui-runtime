from __future__ import annotations

import base64
import copy
import os
import threading
import time
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QRawFont
from PySide6.QtTest import QTest

from app.desktop_review.window import ReviewMainWindow, ensure_application


def _png() -> str:
    image = Image.new("RGB", (160, 100), "#e9f2ff")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _batch(batch_id: str = "batch-1") -> dict:
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "x", "batch_id": batch_id,
        "title": "中文审核样例", "learning_outcome": "completed", "outcome_reason": None,
        "screenshots": [{"screenshot_id": "shot-1", "png_base64": _png(), "width": 160, "height": 100}],
        "interfaces": [{"interface_id": "screen-1", "screenshot_id": "shot-1", "meaning": "职位详情页", "regions": [{"region_id": "apply", "bbox": [10.0, 20.0, 80.0, 25.0], "name": "申请按钮", "kind": "button", "meaning": "打开申请流程"}]}],
        "relationships": [],
        "steps": [{"step_id": "step-1", "action_type": "open_apply_flow", "target_region_id": "apply", "start_state": "screen-1", "arrival_state": "screen-1", "prerequisites": [], "expected_result": "显示申请步骤", "stop_condition": "出现最终提交时停止"}],
        "issues": [],
    }


class _Facade:
    def __init__(self, batches: list[dict] | None = None) -> None:
        source = [_batch()] if batches is None else batches
        self.batches = {item["batch_id"]: copy.deepcopy(item) for item in source}
        self.saved: list[dict] = []
        self.closed = False

    def list_batches(self) -> list[dict]:
        return [{"task_id": "task-1", "batch_id": key, "title": value["title"], "status": "needs_human_review"} for key, value in self.batches.items()]

    def load_batch(self, task_id: str, batch_id: str) -> dict:
        return {"contract_version": "desktop_review_workspace_v1", "task_id": task_id, "batch_id": batch_id, "revision": 0, "source_ref": "0" * 64, "source": "untrusted_external", "batch": copy.deepcopy(self.batches[batch_id]), "workflow_review_path": None, "review_status": "needs_human_review"}

    def save_revision(self, task_id: str, batch_id: str, expected_revision: int, batch: dict) -> dict:
        assert expected_revision == len(self.saved)
        self.saved.append(copy.deepcopy(batch))
        return {"contract_version": "desktop_review_workspace_v1", "task_id": task_id, "batch_id": batch_id, "revision": expected_revision + 1, "source_ref": "0" * 64, "source": "untrusted_external", "batch": copy.deepcopy(batch), "workflow_review_path": "review.json", "review_status": "needs_human_review"}

    def close(self) -> None:
        self.closed = True


class _BlockingFacade(_Facade):
    def __init__(self, batches: list[dict]) -> None:
        super().__init__(batches)
        self.block_load = False
        self.block_save = False
        self.fail_save = False
        self.bad_save_response = False
        self.load_started = threading.Event()
        self.save_started = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def load_batch(self, task_id: str, batch_id: str) -> dict:
        if self.block_load:
            self.load_started.set()
            self.release.wait(3)
        return super().load_batch(task_id, batch_id)

    def save_revision(self, task_id: str, batch_id: str, expected_revision: int, batch: dict) -> dict:
        if self.block_save:
            self.save_started.set()
            self.release.wait(3)
        if self.fail_save:
            raise RuntimeError("保存失败样例")
        result = super().save_revision(task_id, batch_id, expected_revision, batch)
        if self.bad_save_response:
            result["revision"] = expected_revision + 2
        return result


def _wait_loaded(window: ReviewMainWindow) -> None:
    deadline = time.monotonic() + 8
    application = ensure_application()
    while time.monotonic() < deadline:
        time.sleep(0.01)
        application.processEvents()
        QTest.qWait(1)
        if window.workspace is not None and window._operation == "idle" and not window._jobs:
            return
        if window.workspace is None and window.batch_tree.currentItem() is None and window.batch_tree.topLevelItemCount():
            window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    raise AssertionError("window did not bind the worker response")


def _wait_workers(window: ReviewMainWindow) -> None:
    deadline = time.monotonic() + 8
    application = ensure_application()
    while time.monotonic() < deadline:
        time.sleep(0.01)
        application.processEvents()
        QTest.qWait(1)
        if not window._jobs:
            return
    raise AssertionError("native worker did not tear down")


def test_native_window_edits_chinese_bbox_and_saves_new_revision(tmp_path: Path) -> None:
    del tmp_path
    application = ensure_application()
    facade = _Facade()
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    region = window.batch_tree.topLevelItem(0).child(0).child(0)
    window.batch_tree.setCurrentItem(region)
    QTest.qWait(20)
    assert window.region_meaning.toPlainText() == "打开申请流程"
    window.canvas.scale(1.25, 1.25)
    start = window.canvas.mapFromScene(QPointF(20.0, 30.0))
    end = window.canvas.mapFromScene(QPointF(28.0, 30.0))
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(window.canvas.viewport(), end, 20)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    QTest.qWait(20)
    assert window.workspace["batch"]["interfaces"][0]["regions"][0]["bbox"][0] > 10.0
    window.region_meaning.setPlainText("打开受控申请流程")
    window.bbox_spins[0].setValue(12.0)
    assert window.is_dirty
    window.save_current()
    for _ in range(30):
        QTest.qWait(25)
        if window.workspace and window.workspace["revision"] == 1:
            break
    assert window.workspace and window.workspace["revision"] == 1
    assert facade.saved[0]["interfaces"][0]["regions"][0]["meaning"] == "打开受控申请流程"
    assert facade.saved[0]["interfaces"][0]["regions"][0]["bbox"][0] == 12.0
    _wait_workers(window)
    window.close()
    application.processEvents()


def test_empty_and_dirty_navigation_are_honest() -> None:
    application = ensure_application()
    raw_font = QRawFont.fromFont(application.font())
    assert raw_font.isValid() and raw_font.supportsCharacter(0x4E2D)
    empty = ReviewMainWindow(_Facade([]))
    assert empty.empty_label.isVisible() or "暂无" in empty.empty_label.text()
    empty.close()
    facade = _Facade([_batch("batch-1"), _batch("batch-2")])
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    window._mark_dirty()
    window._confirm_discard = lambda _message: False  # type: ignore[method-assign]
    window.load_batch("task-1", "batch-2")
    QTest.qWait(50)
    assert window.workspace and window.workspace["batch_id"] == "batch-1"
    window._dirty = False
    _wait_workers(window)
    window.close()
    application.processEvents()


def test_native_window_uses_real_facade_save_contract(tmp_path: Path) -> None:
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.workspace import NativeReviewFacade

    application = ensure_application()
    store = AgentLinkStore(tmp_path / "inbox.json")
    token = "reviewer-secret-value-123"
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "task-1", "agent_name": "native-ui-test"})
    proposal = _batch()
    region_source = proposal["interfaces"][0]["regions"][0]
    region_source["label"] = region_source.pop("name")
    region_source.pop("kind")
    for screenshot in proposal["screenshots"]:
        screenshot.pop("width"); screenshot.pop("height")
    service.agent_call(grant["token"], "submit_batch", proposal)
    stored_region = service.reviewer_call(token, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"})["batch"]["interfaces"][0]["regions"][0]
    assert stored_region["name"] is None and stored_region["label"] == "申请按钮" and stored_region["kind"] is None
    facade = NativeReviewFacade(service, token, tmp_path / "review-root")
    try:
        window = ReviewMainWindow(facade)
        window.show()
        window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
        _wait_loaded(window)
        region = window.batch_tree.topLevelItem(0).child(0).child(0)
        window.batch_tree.setCurrentItem(region)
        QTest.qWait(25)
        window.interface_meaning.setText("人工审核后的界面含义")
        window.interface_meaning.editingFinished.emit()
        window.region_meaning.setPlainText("人工审核后的区域含义")
        assert window.is_dirty
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        for _ in range(800):
            QTest.qWait(25)
            if window.workspace and window.workspace["revision"] == 1:
                break
        assert window.workspace and window.workspace["revision"] == 1, window.status.currentMessage()
        saved_region = window.workspace["batch"]["interfaces"][0]["regions"][0]
        assert saved_region["name"] == "申请按钮"
        assert saved_region["kind"] is None and saved_region["type"] is None
        _wait_workers(window)
        window.close()
        application.processEvents()
        reopened = NativeReviewFacade(service, token, tmp_path / "review-root")
        try:
            reloaded = reopened.load_batch("task-1", "batch-1")
            assert reloaded["batch"]["interfaces"][0]["meaning"] == "人工审核后的界面含义"
            assert reloaded["batch"]["interfaces"][0]["regions"][0]["meaning"] == "人工审核后的区域含义"
        finally:
            reopened.close()
    finally:
        facade.close()
        store.close()


def test_step_multichar_and_ctrl_s_keep_target_and_commit_focused_fields() -> None:
    application = ensure_application()
    facade = _Facade()
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    window.step_table.selectRow(0)
    QTest.qWait(20)
    assert window.step_target.currentData() == "apply"
    window.step_expected.setFocus()
    QTest.keyClick(window.step_expected, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(window.step_expected, "multi result")
    assert window.step_target.currentData() == "apply"
    assert window.workspace["batch"]["steps"][0]["target_region_id"] == "apply"
    window.interface_meaning.setFocus()
    QTest.keyClick(window.interface_meaning, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(window.interface_meaning, "reviewed interface")
    QTest.keyClick(window.interface_meaning, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    for _ in range(30):
        QTest.qWait(25)
        if window.workspace and window.workspace["revision"] == 1:
            break
    assert window.workspace and window.workspace["revision"] == 1
    assert facade.saved[0]["interfaces"][0]["meaning"] == "reviewed interface"
    assert facade.saved[0]["steps"][0]["target_region_id"] == "apply"
    _wait_workers(window)
    window._dirty = False
    window.close()
    application.processEvents()


def test_safe_stop_keeps_existing_cross_interface_optional_target() -> None:
    application = ensure_application()
    batch = _batch()
    batch["interfaces"].append({"interface_id": "screen-2", "screenshot_id": "shot-1", "meaning": "停止界面", "regions": [{"region_id": "cross-target", "bbox": [100.0, 20.0, 40.0, 25.0], "name": "跨界面提示", "kind": "text", "meaning": "停止时观察"}]})
    batch["steps"].append({"step_id": "stop-1", "action_type": "safe_stop", "target_region_id": "cross-target", "start_state": "screen-1", "arrival_state": "screen-2", "prerequisites": [], "expected_result": "保留跨界面提示", "stop_condition": "停止"})
    facade = _Facade([batch])
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    window.step_table.selectRow(1)
    QTest.qWait(20)
    assert window.step_target.currentData() == "cross-target"
    window.step_expected.setFocus()
    QTest.keyClick(window.step_expected, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(window.step_expected, "keep cross target")
    assert window.step_target.currentData() == "cross-target"
    assert window.workspace["batch"]["steps"][1]["target_region_id"] == "cross-target"
    _wait_workers(window)
    window._dirty = False
    window.close()
    application.processEvents()


def test_step_start_change_requires_a_new_target_from_new_interface() -> None:
    application = ensure_application()
    batch = _batch()
    batch["interfaces"].append({"interface_id": "screen-2", "screenshot_id": "shot-1", "meaning": "第二界面", "regions": [{"region_id": "next-target", "bbox": [100.0, 20.0, 40.0, 25.0], "name": "第二按钮", "kind": "button", "meaning": "第二目标"}]})
    facade = _Facade([batch])
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    window.step_table.selectRow(0)
    QTest.qWait(20)
    assert window.step_target.currentData() == "apply"
    window.step_start.setText("screen-2")
    window.step_start.editingFinished.emit()
    assert window.step_target.currentData() is None
    target_index = window.step_target.findData("next-target")
    assert target_index > 0
    window.step_target.setCurrentIndex(target_index)
    step = window.workspace["batch"]["steps"][0]
    assert step["start_state"] == "screen-2"
    assert step["target_region_id"] == "next-target"
    _wait_workers(window)
    window._dirty = False
    window.close()
    application.processEvents()


def test_load_and_save_races_do_not_enable_or_replace_current_draft() -> None:
    application = ensure_application()
    second = _batch("batch-2")
    second["interfaces"][0]["meaning"] = "第二批次界面"
    facade = _BlockingFacade([_batch("batch-1"), second])
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    facade.block_load = True
    facade.release.clear()
    window.load_batch("task-1", "batch-2")
    assert facade.load_started.wait(1)
    QTest.qWait(20)
    assert not window.region_meaning.isEnabled()
    assert not window.interface_meaning.isEnabled()
    assert not window.save_button.isEnabled()
    assert not window.reload_button.isEnabled()
    window.save_current()
    assert window._operation == "loading"
    facade.release.set()
    for _ in range(40):
        QTest.qWait(25)
        if window.workspace and window.workspace["batch_id"] == "batch-2":
            break
    assert window.workspace and window.workspace["batch_id"] == "batch-2"
    assert window._selected_step_id is None
    assert window.step_target.count() == 0

    region = window.batch_tree.topLevelItem(0).child(0).child(0)
    window.batch_tree.setCurrentItem(region)
    window.region_meaning.setPlainText("保存中旧批次草稿")
    facade.block_load = False
    facade.block_save = True
    facade.release.clear()
    window.save_current()
    assert facade.save_started.wait(1)
    replacement = facade.load_batch("task-1", "batch-1")
    window._workspace = replacement
    facade.release.set()
    for _ in range(40):
        QTest.qWait(25)
        if window._operation == "idle":
            break
    assert window.workspace and window.workspace["batch_id"] == "batch-1"
    _wait_workers(window)
    window._dirty = False
    window.close()
    application.processEvents()


def test_save_failure_keeps_pending_invalid_text_and_draft() -> None:
    application = ensure_application()
    facade = _BlockingFacade([_batch()])
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    region = window.batch_tree.topLevelItem(0).child(0).child(0)
    window.batch_tree.setCurrentItem(region)
    window.region_meaning.setFocus()
    QTest.keyClick(window.region_meaning, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window.region_meaning, Qt.Key.Key_Delete)
    window.save_current()
    assert window.is_dirty
    assert window.region_meaning.toPlainText() == ""
    assert "无法保存" in window.status.currentMessage()
    window.region_meaning.setPlainText("保存失败也保留草稿")
    facade.fail_save = True
    window.save_current()
    for _ in range(40):
        QTest.qWait(25)
        if window._operation == "idle":
            break
    assert window.is_dirty
    assert window.region_meaning.toPlainText() == "保存失败也保留草稿"
    assert "草稿未丢失" in window.status.currentMessage()
    _wait_workers(window)
    window._dirty = False
    window.close()
    application.processEvents()


def test_mismatched_save_response_preserves_current_draft() -> None:
    application = ensure_application()
    facade = _BlockingFacade([_batch()])
    facade.bad_save_response = True
    window = ReviewMainWindow(facade)
    window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
    _wait_loaded(window)
    region = window.batch_tree.topLevelItem(0).child(0).child(0)
    window.batch_tree.setCurrentItem(region)
    window.region_meaning.setPlainText("等待可信保存响应")
    window.save_current()
    for _ in range(40):
        QTest.qWait(25)
        if window._operation == "idle":
            break
    assert window.workspace and window.workspace["revision"] == 0
    assert window.is_dirty
    assert "修订不匹配" in window.status.currentMessage()
    _wait_workers(window)
    window._dirty = False
    window.close()
    application.processEvents()
