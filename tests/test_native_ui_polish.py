from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QSplitter

from app.desktop_review.graph_review_pane import GraphReviewPane
from app.desktop_review.theme import (
    ACCENT,
    BACKGROUND,
    BORDER,
    MUTED_TEXT,
    TEXT,
    WHITE,
    apply_review_theme,
)
from test_formal_graph_review_pane import _click_edge, _node, _runtime, _wait, qapp


def test_review_theme_exposes_clean_light_palette_and_accessible_states(qapp) -> None:
    pane = GraphReviewPane(object())
    try:
        apply_review_theme(pane)
        stylesheet = pane.styleSheet().lower()
        assert pane.property("reviewTheme") == "light-blue"
        for colour in (WHITE, BACKGROUND, ACCENT, TEXT, MUTED_TEXT, BORDER):
            assert colour in stylesheet
        assert 'qpushbutton[role="primary"]' in stylesheet
        assert "qpushbutton:disabled" in stylesheet
        assert "qtoolbar#reviewnavigation" in stylesheet
        assert "qtoolbutton:checked" in stylesheet
        assert "qwidget#reviewheader" in stylesheet
        assert "qlabel#reviewheadertitle" in stylesheet
        assert "qlabel#reviewbrand" in stylesheet
        assert "qwidget#navspacer" in stylesheet
        assert "qpushbutton:focus" in stylesheet
        assert "qtoolbutton:focus" in stylesheet
    finally:
        pane.close()


def test_graph_is_above_large_evidence_and_inspector_is_scrollable(qapp) -> None:
    pane = GraphReviewPane(object())
    pane.resize(1280, 760)
    pane.show()
    qapp.processEvents()
    try:
        outer = pane.findChild(QSplitter, "graphWorkspaceSplitter")
        center = pane.findChild(QSplitter, "graphCenterSplitter")
        evidence = pane.findChild(QSplitter, "graphEvidenceSplitter")
        inspector = pane.findChild(QScrollArea, "graphInspectorScroll")
        assert outer is not None and outer.orientation() == Qt.Orientation.Horizontal
        assert center is not None and center.orientation() == Qt.Orientation.Vertical
        assert evidence is not None and evidence.orientation() == Qt.Orientation.Horizontal
        assert inspector is not None and inspector.widgetResizable()
        assert 300 <= inspector.width() <= 430
        assert pane.graph_view.minimumHeight() >= 140
        assert pane.before_canvas.minimumHeight() >= 220
        assert not pane.after_canvas.isVisible()
        graph_fit = pane.findChild(QPushButton, "fitGraphButton")
        before_actual = pane.findChild(QPushButton, "beforeCanvasActualSizeButton")
        before_fit = pane.findChild(QPushButton, "beforeCanvasFitButton")
        assert graph_fit is not None and graph_fit.maximumWidth() <= 90
        assert before_actual is not None and before_actual.minimumWidth() >= 64
        assert before_fit is not None and before_fit.minimumWidth() >= 52
        assert before_actual.width() >= before_actual.fontMetrics().horizontalAdvance("100%") + 20
        assert before_fit.mapTo(pane.before_box, QPoint()).y() < pane.before_canvas.y()
    finally:
        pane.close()


def test_node_uses_one_original_and_edge_uses_before_after(tmp_path, qapp) -> None:
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.resize(1280, 760)
    pane.show()
    try:
        pane.set_revision(created)
        _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None)
        assert pane.before_canvas.isVisible()
        assert not pane.after_canvas.isVisible()
        assert pane.before_title_label.text() == "原始截图"
        assert "原始" in pane.before_title_label.toolTip()
        edge = created["graph"]["edges"][0]
        _click_edge(pane, edge["edge_id"])
        _wait(qapp, lambda: not pane.is_busy and pane.after_canvas._pixmap_item is not None)
        assert pane.before_canvas.isVisible() and pane.after_canvas.isVisible()
        assert pane.before_title_label.text() == "动作前"
        assert pane.after_title_label.text() == "动作后"
        for box in (pane.before_box, pane.after_box):
            for button in box.findChildren(QPushButton):
                if button.isVisible():
                    left = button.mapTo(box, QPoint()).x()
                    assert left >= 0
                    assert left + button.width() <= box.width()
        assert pane.before_canvas._image_identity[1] == _node(created, "state-a")["node_id"]
        assert pane.after_canvas._image_identity[1] == _node(created, "state-b")["node_id"]
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_compact_identity_and_inspector_controls_never_overflow_horizontally(
    tmp_path, qapp,
) -> None:
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    apply_review_theme(pane)
    pane.resize(1080, 680)
    pane.show()
    try:
        pane.set_revision(created)
        _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None)
        node = _node(created, "state-a")
        assert node["node_id"] not in pane.node_id_display_label.text()
        assert node["node_id"] == pane.node_id_display_label.toolTip()
        assert pane.node_id_label.text() == node["node_id"]

        pane.node_advanced.toggle.setChecked(True)
        pane.node_recognition_section.toggle.setChecked(True)
        qapp.processEvents()
        QTest.qWait(30)

        inspector = pane.findChild(QScrollArea, "graphInspectorScroll")
        viewport = inspector.viewport()
        editor_controls = (
            pane.node_id_display_label,
            pane.node_meaning_edit,
            pane.node_region_combo,
            pane.node_region_bbox_edit,
            pane.node_recognition_text_edit,
            pane.node_recognition_bbox_edit,
            pane.save_node_meaning_button,
            pane.save_region_bbox_button,
            pane.save_node_recognition_button,
        )
        for control in editor_controls:
            if not control.isVisible():
                continue
            left = control.mapTo(viewport, QPoint()).x()
            assert left >= 0, control.objectName()
            assert left + control.width() <= viewport.width(), control.objectName()

        wrapper = pane.inspector_wrapper
        footer_controls = (
            pane.revert_button, pane.graph_relearn_button, pane.review_graph_button,
        )
        for control in footer_controls:
            top_left = control.mapTo(wrapper, QPoint())
            assert top_left.x() >= 0
            assert top_left.x() + control.width() <= wrapper.width()
            assert top_left.y() >= 0
            assert top_left.y() + control.height() <= wrapper.height()
        assert not inspector.isAncestorOf(pane.review_graph_button)
        assert pane.revert_button.text() == "放弃修改"
        assert "未保存" in pane.revert_button.toolTip()
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_identity_is_compact_and_disabling_animation_cancels_it(tmp_path, qapp) -> None:
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.show()
    qapp.processEvents()
    pane.set_animations_enabled(True)
    pane._selection_transition.play()
    qapp.processEvents()
    try:
        assert pane.animations_enabled is True
        assert pane._selection_transition.state() == QAbstractAnimation.State.Running
        pane.set_animations_enabled(False)
        assert pane.animations_enabled is False
        assert pane._selection_transition.state() == QAbstractAnimation.State.Stopped
        assert pane.selection_title.graphicsEffect() is None
        assert pane.selection_title.styleSheet() == ""

        digest = created["content_sha256"]
        pane.set_revision(created)
        assert digest not in pane.identity_label.text()
        assert "修订 1" in pane.identity_label.text()
        assert digest in pane.identity_label.toolTip()
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_closing_pane_stops_animation_before_deferred_widget_deletion(qapp) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    pane = GraphReviewPane(object())
    pane.show()
    qapp.processEvents()
    pane._selection_transition.play()
    assert pane._selection_transition.state() == QAbstractAnimation.State.Running
    pane.close()
    assert pane._selection_transition.state() == QAbstractAnimation.State.Stopped
    assert pane.selection_title.graphicsEffect() is None
    assert pane.selection_title.styleSheet() == ""
    assert pane.animations_enabled is True
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_screenshot_focus_preserves_evidence_identity_split_sizes_and_dirty_state(
    tmp_path, qapp,
) -> None:
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.resize(1080, 680)
    pane.show()
    try:
        pane.set_revision(created)
        _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None)
        button = pane.findChild(QPushButton, "focusScreenshotButton")
        outer = pane.findChild(QSplitter, "graphWorkspaceSplitter")
        center = pane.findChild(QSplitter, "graphCenterSplitter")
        identity = pane.before_canvas._image_identity
        original_sizes = (outer.sizes(), center.sizes())
        assert button is not None and button.isCheckable()
        assert button.accessibleName()

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert button.isChecked()
        assert not pane.graph_box.isVisible()
        assert not pane.inspector_scroll.isVisible()
        assert pane.before_canvas.isVisible()
        assert pane.before_canvas._image_identity == identity
        assert not pane.is_dirty

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert not button.isChecked()
        assert pane.graph_box.isVisible() and pane.inspector_scroll.isVisible()
        assert outer.sizes() == original_sizes[0]
        assert center.sizes() == original_sizes[1]
        assert pane.before_canvas._image_identity == identity
        assert not pane.is_dirty

        edge = created["graph"]["edges"][0]
        _click_edge(pane, edge["edge_id"])
        _wait(qapp, lambda: not pane.is_busy and pane.after_canvas._pixmap_item is not None)
        assert button.isVisible() and pane.after_canvas.isVisible()
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()
