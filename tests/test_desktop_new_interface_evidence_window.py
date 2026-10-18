"""新截图原生审核只读取候选证据，实机输入不在本测试范围。"""
from copy import deepcopy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QMessageBox

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.window import ensure_application, ReviewMainWindow
from app.desktop_review.workspace import NativeReviewFacade
from test_agent_link_flow_candidates import REVIEWER_TOKEN
from test_desktop_flow_candidates import _setup
from test_desktop_new_interface_evidence import _candidate
from test_desktop_missing_flow_entities import _artifacts
from tests.test_desktop_relearn_window import _wait
from tests.test_desktop_review_window import _wait_loaded, _wait_workers


def test_native_new_interface_preview_is_proposed_only_and_readonly(tmp_path):
    from app.desktop_review.interface_comparison import InterfaceComparisonWidget
    application = ensure_application()
    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    widget = None
    try:
        _, _, comparison = _candidate(service, grant, facade)
        before, original = _artifacts(facade), deepcopy(comparison)
        widget = InterfaceComparisonWidget(saved, comparison)
        widget.resize(1000, 700); widget.show(); application.processEvents()
        assert widget.interface_selector.count() == 1
        assert "不存在" in widget.absent_label.text()
        assert "320 × 200" in widget.metadata_label.text()
        assert "shot-new" in widget.metadata_label.text()
        rectangles = [item for item in widget.proposed_view.scene().items() if isinstance(item, QGraphicsRectItem)]
        assert len(rectangles) == 1
        assert not rectangles[0].flags() & QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
        assert not rectangles[0].flags() & QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        assert rectangles[0].acceptedMouseButtons() == Qt.MouseButton.NoButton
        assert len([item for item in widget.proposed_view.scene().items() if isinstance(item, QGraphicsPixmapItem)]) == 1
        assert not widget.proposed_view.isInteractive()
        transform = widget.proposed_view.transform().m11()
        QTest.mouseClick(widget.zoom_in_button, Qt.MouseButton.LeftButton)
        assert widget.proposed_view.transform().m11() > transform
        QTest.mouseClick(widget.fit_button, Qt.MouseButton.LeftButton)
        assert _artifacts(facade) == before and comparison == original
    finally:
        if widget is not None: widget.close()
        application.processEvents(); facade.close(); store.close()


@pytest.mark.parametrize("case", ["hash", "binding", "bbox", "bytes", "authority", "metadata", "workspace", "orphan"])
def test_native_new_interface_preview_rejects_mismatched_evidence(tmp_path, case):
    from app.desktop_review.interface_comparison import InterfaceComparisonWidget
    application = ensure_application()
    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        _, _, comparison = _candidate(service, grant, facade)
        shot = next(diff for diff in comparison["diffs"] if diff["target_type"] == "screenshot")
        interface = next(diff for diff in comparison["diffs"] if diff["target_type"] == "interface")
        if case == "hash": shot["proposed"]["sha256"] = "0" * 64
        elif case == "binding": interface["proposed"]["interface"]["screenshot_id"] = "screen"
        elif case == "bbox": interface["proposed"]["interface"]["regions"][0]["bbox"][2] = 1000.
        elif case == "bytes": shot["proposed"]["png_base64"] = "AA=="
        elif case == "authority": interface["proposed"]["interface"]["execute_binding_enabled"] = True
        elif case == "metadata": shot["proposed"]["width"] = 321
        elif case == "workspace": comparison["workspace_revision"] += 1
        else: comparison["diffs"].remove(shot)
        before = _artifacts(facade)
        with pytest.raises(ValueError): InterfaceComparisonWidget(saved, comparison)
        assert _artifacts(facade) == before
    finally:
        application.processEvents(); facade.close(); store.close()


def test_real_native_new_interface_compare_preview_cancel_adopt_edit_save_reopen(tmp_path):
    from app.desktop_review.relearn_dialog import RelearnReviewDialog
    application = ensure_application()
    path, root, store, service, grant, facade, saved = _setup(tmp_path)
    dialog = window = None
    output = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
    output.mkdir(parents=True, exist_ok=True)
    try:
        _, _, comparison = _candidate(service, grant, facade)
        dialog = RelearnReviewDialog(facade, saved)
        dialog.resize(1500, 1100); dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        dialog.tabs.setCurrentIndex(1); dialog.candidate_table.selectRow(0)
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.comparison == comparison
        assert dialog.interface_button.isEnabled()
        labels = [dialog.diff_table.item(row, 1).text() for row in range(dialog.diff_table.rowCount())]
        assert "新增截图 · SHA-256" in labels and "新增界面 · 关联既有界面" in labels
        png = next(diff["proposed"]["png_base64"] for diff in comparison["diffs"] if diff["target_type"] == "screenshot")
        assert png not in dialog.detail.toPlainText()
        assert all(png not in dialog.diff_table.item(row, 4).text() for row in range(dialog.diff_table.rowCount()))
        row = labels.index("新增界面 · 关联既有界面")
        dialog.diff_table.setCurrentCell(row, 4); dialog.diff_table.scrollToItem(dialog.diff_table.item(row, 4))
        application.processEvents()
        assert dialog.grab().save(str(output / "native-new-interface-comparison.png"))
        inspected = []
        before = _artifacts(facade)
        def inspect():
            preview = application.activeModalWidget()
            inspected.append(preview.objectName() == "interfaceComparisonDialog")
            assert preview.grab().save(str(output / "native-new-interface-preview.png"))
            preview.reject()
        QTimer.singleShot(0, inspect)
        QTest.mouseClick(dialog.interface_button, Qt.MouseButton.LeftButton)
        assert inspected == [True] and _artifacts(facade) == before
        answers = []
        def answer(button):
            prompt = application.activeModalWidget()
            answers.append(isinstance(prompt, QMessageBox) and prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.Cancel))
            QTest.mouseClick(prompt.button(button), Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        assert facade.load_batch("task-flow", "flow-batch") == saved
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert answers == [True, True] and dialog.adoption_receipt is not None, dialog.status.text()
        dialog.close(); application.processEvents()
        window = ReviewMainWindow(facade)
        window.resize(1500, 1100); window.show(); application.processEvents()
        item = window.batch_tree.topLevelItem(0)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton, pos=window.batch_tree.visualItemRect(item).center())
        _wait_loaded(window); _wait_workers(window)
        item = window.batch_tree.topLevelItem(0).child(3)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton, pos=window.batch_tree.visualItemRect(item).center())
        application.processEvents()
        assert window._selected_interface_id == "i-new"
        window.interface_meaning.setText("人工确认的新增详情界面")
        window.save_action.trigger(); _wait_workers(window)
        assert window.workspace["revision"] == 3, window.status.currentMessage()
        assert window.workspace["batch"]["interfaces"][-1]["meaning"] == "人工确认的新增详情界面"
        assert window.grab().save(str(output / "native-new-interface-edited.png"))
        assert facade.list_reviewed_assets() == []
        final = deepcopy(window.workspace)
    finally:
        if dialog is not None:
            _wait(lambda: not dialog._jobs); dialog.close()
        if window is not None:
            _wait_workers(window); window._dirty = False; window.close()
        application.processEvents(); facade.close(); store.close()
    store = AgentLinkStore(path)
    facade = NativeReviewFacade(AgentLinkService(store, REVIEWER_TOKEN), REVIEWER_TOKEN, root)
    try:
        assert facade.load_batch("task-flow", "flow-batch") == final
    finally:
        facade.close(); store.close()
