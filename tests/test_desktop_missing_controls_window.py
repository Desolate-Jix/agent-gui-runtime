"""新增控件的原生只读对照；只使用合成截图和临时审核数据。"""
from copy import deepcopy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QGraphicsPixmapItem, QGraphicsRectItem, QMessageBox

from app.desktop_review.geometry_comparison import GeometryComparisonWidget
from tests.test_desktop_geometry_comparison import _comparison, _pump, _workspace
from tests.test_desktop_relearn_adoption_window import _compared


def _addition(identifier="missing-one", interface="screen-one", bbox=None):
    return {
        "target_type": "region", "target_id": identifier, "field": "entity",
        "baseline": None, "current": None,
        "proposed": {"interface_id": interface, "region": {
            "region_id": identifier, "bbox": bbox or [15.0, 18.0, 24.0, 16.0],
            "name": "遗漏按钮", "label": None, "type": "button", "kind": None,
            "meaning": "打开尚未审核的详情",
        }},
    }


def _rects(view):
    return [item for item in view.scene().items() if isinstance(item, QGraphicsRectItem)]


def test_added_region_draws_only_proposal_on_same_saved_png_and_switches_parent():
    workspace = _workspace()
    before = deepcopy(workspace)
    comparison = _comparison(workspace, [_addition(), _addition("missing-two", "screen-two")])
    widget = GeometryComparisonWidget(workspace, comparison)
    try:
        widget.resize(1100, 520)
        widget.show()
        _pump()
        assert widget.region_selector.count() == 2
        assert "新增" in widget.region_selector.currentText()
        for index, width in ((0, 120), (1, 200)):
            widget.region_selector.setCurrentIndex(index)
            _pump()
            assert "不存在" in widget.baseline_bbox_label.text()
            assert "不存在" in widget.current_bbox_label.text()
            assert _rects(widget.baseline_view) == _rects(widget.current_view) == []
            proposed = _rects(widget.proposed_view)
            assert len(proposed) == 1
            rect = proposed[0]
            assert [rect.x(), rect.y(), rect.rect().width(), rect.rect().height()] == [15, 18, 24, 16]
            assert not rect.flags() & QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            for view in (widget.baseline_view, widget.current_view, widget.proposed_view):
                pixmap = next(item for item in view.scene().items() if isinstance(item, QGraphicsPixmapItem))
                assert pixmap.pixmap().width() == width
        assert workspace == before and len(workspace["batch"]["interfaces"][0]["regions"]) == 1
    finally:
        widget.close()


@pytest.mark.parametrize("invalid", [
    "existing_id", "wrong_id", "unknown_parent", "baseline_present", "current_present",
    "wrapper_extra", "region_authority", "bbox_outside", "bbox_bool", "bbox_nan",
    "duplicate", "bad_png", "region_limit", "diff_extra",
])
def test_invalid_added_region_evidence_is_rejected_without_fabricating_frame(invalid):
    workspace = _workspace()
    diff = _addition()
    comparison = _comparison(workspace, [diff])
    if invalid == "existing_id":
        diff["target_id"] = diff["proposed"]["region"]["region_id"] = "region-one"
    elif invalid == "wrong_id":
        diff["proposed"]["region"]["region_id"] = "another"
    elif invalid == "unknown_parent":
        diff["proposed"]["interface_id"] = "foreign-interface"
    elif invalid == "baseline_present":
        diff["baseline"] = {}
    elif invalid == "current_present":
        diff["current"] = False
    elif invalid == "wrapper_extra":
        diff["proposed"]["authorization"] = True
    elif invalid == "region_authority":
        diff["proposed"]["region"]["reviewed_by_human"] = True
    elif invalid == "bbox_outside":
        diff["proposed"]["region"]["bbox"] = [115, 1, 20, 10]
    elif invalid == "bbox_bool":
        diff["proposed"]["region"]["bbox"][0] = True
    elif invalid == "bbox_nan":
        diff["proposed"]["region"]["bbox"][0] = float("nan")
    elif invalid == "duplicate":
        comparison["diffs"].append(deepcopy(diff))
    elif invalid == "bad_png":
        workspace["batch"]["screenshots"][0]["sha256"] = "0" * 64
    elif invalid == "region_limit":
        template = workspace["batch"]["interfaces"][0]["regions"][0]
        workspace["batch"]["interfaces"][0]["regions"] = [
            {**deepcopy(template), "region_id": f"existing-{index}"} for index in range(128)
        ]
    else:
        diff["execute_binding_enabled"] = True
    with pytest.raises(ValueError):
        GeometryComparisonWidget(workspace, comparison)


def test_native_added_control_geometry_entry_is_readonly_and_explicit():
    application, facade, dialog = _compared()
    before = deepcopy(dialog.workspace)
    comparison = deepcopy(dialog.comparison)
    comparison["diffs"] = [_addition("new-control", "one", [1.0, 1.0, 2.0, 2.0])]
    dialog._pending = ("compare", comparison["candidate_id"])
    dialog._succeeded(dialog._request_id, comparison)
    seen = []

    def inspect():
        modal = application.activeModalWidget()
        if isinstance(modal, QDialog):
            widget = modal.findChild(GeometryComparisonWidget)
            seen.append(bool(widget and len(_rects(widget.proposed_view)) == 1
                             and not _rects(widget.current_view)))
            modal.close()

    try:
        dialog._controls()
        assert dialog.geometry_button.isEnabled()
        assert dialog.diff_table.item(0, 1).text() == "新增控件"
        assert dialog.diff_table.item(0, 2).text() == dialog.diff_table.item(0, 3).text() == "不存在"
        QTimer.singleShot(0, inspect)
        QTest.mouseClick(dialog.geometry_button, Qt.MouseButton.LeftButton)
        assert seen == [True]
        assert dialog.workspace == before and not facade.requests
        assert dialog.adoption_receipt is None
    finally:
        dialog.close()
        application.processEvents()


def test_real_native_missing_control_compare_adopt_edit_and_reopen(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.relearn_dialog import RelearnReviewDialog
    from app.desktop_review.window import ReviewMainWindow, ensure_application
    from app.desktop_review.workspace import NativeReviewFacade
    from tests.test_desktop_review_integration import _synthetic_batch
    from tests.test_desktop_relearn_window import _wait
    from tests.test_desktop_review_window import _wait_loaded, _wait_workers

    application = ensure_application()
    raw_batch = _synthetic_batch(application)
    missing = raw_batch["interfaces"][0]["regions"].pop()
    state, root = tmp_path / "inbox.json", tmp_path / "review-data"
    token = "synthetic-missing-controls-reviewer"
    store = AgentLinkStore(state)
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成漏识别候选"})
    service.agent_call(grant["token"], "submit_batch", raw_batch)
    facade = NativeReviewFacade(service, token, root)
    dialog = window = None
    output = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
    output.mkdir(parents=True, exist_ok=True)
    try:
        loaded = facade.load_batch("qa-task", "native-qa-batch")
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, loaded["batch"])
        dialog = RelearnReviewDialog(facade, saved)
        dialog.resize(1300, 820)
        dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        dialog.scope_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.message.setPlainText("截图中的查看详情按钮漏识别，请补充并关联步骤")
        QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert not dialog.message.toPlainText(), dialog.status.text()
        issue = service.agent_call(grant["token"], "read_feedback", {"batch_id": "native-qa-batch"})["issues"][0]
        step = deepcopy(saved["batch"]["steps"][0])
        step.update(change_type="step_flow", target_region_id=missing["region_id"], action_type="open_detail")
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "batch_id": "native-qa-batch", "idempotency_key": "native-add-control",
            "issue_id": issue["issue_id"], "baseline_revision": issue["baseline_revision"], "scope": issue["scope"],
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "changes": [step, {"change_type": "regions_add", "interface_id": "file-list", "regions": [missing]}],
        })
        original = service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"]
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        dialog.tabs.setCurrentIndex(1)
        dialog.candidate_table.selectRow(0)
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.comparison is not None and dialog.comparison["status"] == "current", dialog.status.text()
        assert dialog.diff_table.rowCount() == 8
        assert dialog.diff_table.item(7, 1).text() == "新增控件"
        assert dialog.diff_table.item(7, 2).text() == dialog.diff_table.item(7, 3).text() == "不存在"
        assert dialog.grab().save(str(output / "native-missing-control-comparison.png"))
        geometry_seen = []

        def inspect_geometry():
            modal = application.activeModalWidget()
            if isinstance(modal, QDialog):
                widget = modal.findChild(GeometryComparisonWidget)
                geometry_seen.append(bool(widget and not _rects(widget.current_view)
                                          and len(_rects(widget.proposed_view)) == 1
                                          and modal.grab().save(str(output / "native-missing-control-geometry.png"))))
                modal.close()

        QTimer.singleShot(0, inspect_geometry)
        QTest.mouseClick(dialog.geometry_button, Qt.MouseButton.LeftButton)
        assert geometry_seen == [True]
        confirmations = []

        def answer(button):
            prompt = application.activeModalWidget()
            if isinstance(prompt, QMessageBox):
                confirmations.append(prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.Cancel))
                QTest.mouseClick(prompt.button(button), Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        assert facade.load_batch("qa-task", "native-qa-batch") == saved
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert confirmations == [True, True]
        assert dialog.adoption_receipt is not None and dialog.requires_workspace_reload, dialog.status.text()
        adopted = facade.load_batch("qa-task", "native-qa-batch")
        assert adopted["revision"] == 2 and adopted["review_status"] == "needs_human_review"
        assert adopted["batch"]["screenshots"] == saved["batch"]["screenshots"]
        assert adopted["relearn_adoption"]["candidate_id"] == candidate["candidate_id"]
        assert adopted["batch"]["interfaces"][0]["regions"][0]["region_id"] == missing["region_id"]
        assert facade.list_reviewed_assets() == []
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"] == original
        dialog.close()
        application.processEvents()
        window = ReviewMainWindow(facade)
        window.show()
        application.processEvents()
        item = window.batch_tree.topLevelItem(0)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.batch_tree.visualItemRect(item).center())
        _wait_loaded(window)
        _wait_workers(window)
        window._select_region(missing["region_id"])
        assert window.region_meaning.isEnabled()
        window.region_meaning.setPlainText("人工检查新增按钮：只用于打开详情")
        window.save_action.trigger()
        _wait_workers(window)
        assert window.workspace["revision"] == 3
        assert window.workspace["batch"]["interfaces"][0]["regions"][0]["meaning"] == "人工检查新增按钮：只用于打开详情"
        assert window.grab().save(str(output / "native-missing-control-adopted.png"))
        final = deepcopy(window.workspace)
    finally:
        if dialog is not None:
            _wait(lambda: not dialog._jobs)
            dialog.message.clear()
            for index in range(dialog.scope_list.count()):
                dialog.scope_list.item(index).setCheckState(Qt.CheckState.Unchecked)
            dialog.close()
        if window is not None:
            _wait_workers(window)
            window.close()
        application.processEvents()
        facade.close()
        store.close()
    reopened_store = AgentLinkStore(state)
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, token), token, root)
    try:
        assert reopened.load_batch("qa-task", "native-qa-batch") == final
    finally:
        reopened.close()
        reopened_store.close()
