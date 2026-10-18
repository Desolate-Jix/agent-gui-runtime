"""长属性表单保留可读高度，滚动不移动画布或改变审核数据。"""
import copy

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea

from app.desktop_review.window import ReviewMainWindow, ensure_application
from tests.test_desktop_review_window import _Facade, _wait_workers


@pytest.mark.parametrize("size", [(1440, 900), (1080, 680)])
def test_properties_fields_remain_readable_in_supported_window_sizes(size):
    app = ensure_application()
    window = ReviewMainWindow(_Facade([]))
    try:
        window.resize(*size); window.show(); _wait_workers(window); QTest.qWait(30)
        for field in (window.step_action, window.scroll_direction, window.scroll_wheel_clicks,
                      window.text_variable, window.step_start, window.step_arrival, window.relationship_kind):
            assert field.height() >= field.fontMetrics().height() + 4, (field.objectName(), field.height())
        assert window.size().width() == size[0] and window.size().height() == size[1]
        scroll = window.findChild(QScrollArea, "propertiesScrollArea")
        assert scroll is not None and scroll.horizontalScrollBar().maximum() == 0, "form controls must fit the inspector width"
    finally:
        _wait_workers(window); window.close()


def test_scroll_reaches_last_controls_without_moving_other_panes_or_draft():
    app = ensure_application()
    window = ReviewMainWindow(_Facade([]))
    try:
        window.resize(1080, 680); window.show(); _wait_workers(window); QTest.qWait(30)
        splitter = window._legacy_review
        other_geometry = [splitter.widget(i).geometry() for i in (0, 1)]
        workspace, dirty = copy.deepcopy(window.workspace), window.is_dirty
        scroll = window.findChild(QScrollArea, "propertiesScrollArea")
        assert scroll is not None, "long inspector needs a reachable scroll viewport"
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()); QTest.qWait(20)
        button = window.workflow_library_button
        position = button.mapTo(scroll.viewport(), QPoint(0, 0))
        assert 0 <= position.y() and position.y() + button.height() <= scroll.viewport().height()
        assert [splitter.widget(i).geometry() for i in (0, 1)] == other_geometry
        assert window.workspace == workspace and window.is_dirty == dirty
    finally:
        _wait_workers(window); window.close()
