from copy import deepcopy

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest

from app.desktop_review.graph_review_pane import GraphReviewPane
from test_formal_graph_review_pane import _node, _runtime, _wait, qapp


def _loaded(pane, snapshot, qapp):
    pane.resize(1280, 800)
    pane.show()
    pane.set_revision(snapshot)
    _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
    pane._node_selected(_node(snapshot, "state-a")["node_id"])
    _wait(qapp, lambda: not pane.is_busy and not pane._jobs)


def _close(pane, facade, store, qapp):
    _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
    pane.close()
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    facade.close()
    store.close()


def test_one_save_persists_multiple_fields_as_one_revision(tmp_path, qapp):
    store, _, facade, original = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    try:
        _loaded(pane, original, qapp)
        pane.node_meaning_edit.setText("新的界面说明")
        pane.node_region_bbox_edit.setText("5, 7, 25, 16")
        assert pane.save_all_button.isEnabled()
        QTest.mouseClick(pane.save_all_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        saved = facade.load_graph_revision(original["logical_workflow_id"])
        assert saved["revision"] == original["revision"] + 1
        assert _node(saved, "state-a")["display_name"] == "新的界面说明"
        assert _node(saved, "state-a")["regions"][0]["bbox"] == [5, 7, 25, 16]
        assert not pane.is_dirty
        assert not pane.save_all_button.isEnabled()
        assert pane.review_graph_button.isEnabled()
    finally:
        _close(pane, facade, store, qapp)


def test_invalid_advanced_conditions_cannot_be_silently_replaced(tmp_path, qapp):
    store, _, facade, original = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    try:
        _loaded(pane, original, qapp)
        pane._edge_selected(original["graph"]["edges"][0]["edge_id"])
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        pane.edge_advanced.toggle.setChecked(True)
        pane.edge_prerequisites_edit.setPlainText('["unfinished"')
        assert not pane.edge_conditions_plain.isEnabled()
        pane.save_all_button.click()
        assert pane.is_dirty
        assert facade.load_graph_revision(original["logical_workflow_id"]) == original
        pane.edge_prerequisites_edit.setPlainText('["已加载"]')
        assert pane.edge_conditions_plain.isEnabled()
        assert pane.edge_conditions_plain.toPlainText() == "已加载"
    finally:
        _close(pane, facade, store, qapp)


def test_ctrl_s_in_focused_field_saves_latest_input_once(tmp_path, qapp):
    from app.desktop_review.window import ReviewMainWindow

    store, _, facade, original = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.show()
        window.open_graph_review(original["logical_workflow_id"])
        _wait(qapp, lambda: not window._jobs and window._operation == "idle"
              and window._graph_pane is not None and not window._graph_pane.is_busy
              and not window._graph_pane._jobs)
        pane = window._graph_pane
        pane._node_selected(_node(original, "state-a")["node_id"])
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        pane.node_advanced.toggle.setChecked(True)
        pane.node_region_bbox_edit.setText("5, 7, 25, 16")
        pane.node_meaning_edit.setText("最新输入")
        pane.node_meaning_edit.setFocus()
        QTest.keyClicks(pane.node_meaning_edit, "-last")
        assert pane.node_meaning_edit.hasFocus()
        assert window.save_action.isEnabled()
        QTest.keyClick(pane.node_meaning_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        saved = facade.load_graph_revision(original["logical_workflow_id"])
        assert saved["revision"] == original["revision"] + 1
        assert _node(saved, "state-a")["display_name"] == "最新输入-last"
        assert _node(saved, "state-a")["regions"][0]["bbox"] == [5, 7, 25, 16]
        assert not pane.is_dirty
    finally:
        _wait(qapp, lambda: not window._jobs and not window._graph_pane.is_busy
              and not window._graph_pane._jobs)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        facade.close()
        store.close()


def test_native_help_has_learning_review_and_reuse_steps(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel
    from app.desktop_review.friendly_controls import ReviewHelpDialog

    dialog = ReviewHelpDialog()
    try:
        dialog.show()
        qapp.processEvents()
        text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        assert "Agent 学习与决策" in text
        assert "Ctrl+S" in text and "不用另行审核" in text
        assert "＋ 添加已有界面" in text and "不会自动补跳转" in text
        assert "交给 Agent 修正" in text
        assert "确切预览和独立确认" in text
        assert dialog.grab().save(str(tmp_path / "native-help.png"))
    finally:
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_invalid_later_field_keeps_all_inputs_and_revision(tmp_path, qapp):
    store, _, facade, original = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    try:
        _loaded(pane, original, qapp)
        pane.node_meaning_edit.setText("不要部分保存")
        pane.node_region_bbox_edit.setText("5, 7, -1, 16")
        pane.save_all_button.click()
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        assert pane.node_meaning_edit.text() == "不要部分保存"
        assert pane.node_region_bbox_edit.text() == "5, 7, -1, 16"
        assert pane.is_dirty
        assert facade.load_graph_revision(original["logical_workflow_id"]) == original
    finally:
        _close(pane, facade, store, qapp)


def test_advanced_fields_collapsed_and_plain_conditions_save(tmp_path, qapp):
    store, _, facade, original = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    try:
        _loaded(pane, original, qapp)
        assert not pane.node_advanced.body.isVisible()
        assert not pane.node_recognition_section.body.isVisible()
        pane._edge_selected(original["graph"]["edges"][0]["edge_id"])
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        assert not pane.edge_advanced.body.isVisible()
        pane.edge_conditions_plain.setPlainText("列表已加载\n目标按钮可见")
        pane.edge_expected_result_edit.setText("详情已打开")
        pane.save_all_button.click()
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        saved = facade.load_graph_revision(original["logical_workflow_id"])
        edge = saved["graph"]["edges"][0]
        assert edge["preconditions"] == ["列表已加载", "目标按钮可见"]
        assert saved["revision"] == original["revision"] + 1
    finally:
        _close(pane, facade, store, qapp)


def test_published_pane_read_only_still_views_evidence_but_cannot_write(tmp_path, qapp):
    store, _, facade, original = _runtime(tmp_path)
    pane = GraphReviewPane(facade, read_only=True)
    review = QSignalSpy(pane.reviewRequested)
    try:
        _loaded(pane, original, qapp)
        assert pane.before_canvas._pixmap_item is not None
        assert pane.before_canvas.isEnabled()
        assert not pane.before_canvas.isInteractive()
        assert not pane.node_meaning_edit.isEnabled()
        assert not pane.save_all_button.isVisible()
        assert not pane.review_graph_button.isVisible()
        assert not pane.graph_relearn_button.isVisible()
        pane.node_meaning_edit.setText("不可写入")
        pane.save_all_changes()
        pane.save_node_meaning()
        pane.request_review()
        pane.open_graph_relearn()
        assert review.count() == 0
        assert pane._relearn_dialog is None
        assert facade.load_graph_revision(original["logical_workflow_id"]) == original
    finally:
        _close(pane, facade, store, qapp)
