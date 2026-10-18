"""新观察原图沿现有原生面板审核，不通过真实系统输入。"""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.desktop_review.graph_review_pane import GraphReviewPane
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_learning_observation import (
    _owner, _bound, _WindowManager, _ScreenshotService, _UIAProvider,
)
from tests.test_formal_graph_review_pane import qapp, _wait, _click_node


def test_fresh_full_resolution_node_loads_and_saves_through_native_pane(tmp_path, qapp):
    capture = tmp_path / "capture"
    packet = _owner(capture,
        manager=_WindowManager(*[_bound(width=1920, height=1080) for _ in range(3)]),
        screenshot=_ScreenshotService(capture, width=1920, height=1080),
        uia=_UIAProvider(width=1920, height=1080),
    ).observe(target_window_handle=4242, target_process_id=9001)
    host, _, _, _, args, result = _stage(tmp_path, packet)
    pane = GraphReviewPane(host.facade)
    pane.resize(1280, 760)
    pane.show()
    try:
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        node_id = graph["graph"]["nodes"][0]["node_id"]
        pane.load_graph(graph["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy and node_id in pane.graph_view._node_items)
        _click_node(pane, node_id)
        _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None)
        pixmap = pane.before_canvas._pixmap_item.pixmap()
        assert (pixmap.width(), pixmap.height()) == (1920, 1080)
        assert pane.node_meaning_edit.text() == args["meaning"]
        assert pane.after_canvas._pixmap_item is None
        assert pane.before_canvas._regions == {}
        pane.node_meaning_edit.setText("\u4eba\u5de5\u6821\u6b63\u7684\u65b0\u89c2\u5bdf")
        QTest.mouseClick(pane.save_node_meaning_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and not pane.is_dirty)
        current = host.facade.load_graph_revision(graph["logical_workflow_id"])
        assert current["revision"] == 2
        assert current["graph"]["nodes"][0]["display_name"] == "\u4eba\u5de5\u6821\u6b63\u7684\u65b0\u89c2\u5bdf"
        evidence = host.facade.load_graph_node_evidence(current["logical_workflow_id"], current["revision"], current["content_sha256"], node_id)
        assert evidence["screenshot"]["png_bytes"] == packet.png_bytes
        assert current["graph"]["edges"] == []
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        host.close()
