from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from app.desktop_review.canvas import ReviewCanvas


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def _batch():
    buffer = BytesIO()
    Image.new("RGB", (640, 480), "white").save(buffer, "PNG")
    return {"batch_id": "fresh-canvas", "screenshots": [{
        "screenshot_id": "shot", "png_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }], "interfaces": [{"interface_id": "page", "screenshot_id": "shot", "meaning": "测试界面",
        "regions": [{"region_id": "target", "bbox": [80, 60, 160, 100]},
                    {"region_id": "second", "bbox": [400, 300, 100, 80]}]}]}


@pytest.fixture
def canvas(application):
    widget = ReviewCanvas()
    widget.resize(640, 480)
    widget.set_interface(_batch(), "page")
    widget.show()
    application.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def _drag(canvas, start, end):
    viewport = canvas.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     canvas.mapFromScene(QPointF(*start)))
    QTest.mouseMove(viewport, canvas.mapFromScene(QPointF(*end)), 10)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       canvas.mapFromScene(QPointF(*end)))
    QApplication.processEvents()


@pytest.mark.parametrize("zoom", [75, 150])
def test_corner_drag_resizes_in_original_image_coordinates(canvas, zoom):
    canvas.set_zoom_percent(zoom)
    canvas.centerOn(160, 120)
    canvas.select_region("target")
    geometry = []
    canvas.regionGeometryChanged.connect(lambda rid, bbox: geometry.append((rid, bbox)))
    _drag(canvas, (240, 160), (300, 210))
    assert canvas._regions["target"].bbox() == pytest.approx([80, 60, 220, 150], abs=2)
    assert len(geometry) == 1 and geometry[0][0] == "target"
    assert geometry[0][1] == canvas._regions["target"].bbox()


def test_same_image_refresh_preserves_zoom_pan_and_updates_regions(canvas):
    canvas.scale(1.4, 1.4)
    canvas.centerOn(420, 320)
    transform = canvas.transform()
    center = canvas.mapToScene(canvas.viewport().rect().center())
    batch = _batch()
    batch["interfaces"][0]["regions"][0]["bbox"] = [90, 70, 170, 110]
    canvas.set_interface(batch, "page")
    canvas.select_region("second")
    assert canvas.transform() == transform
    current = canvas.mapToScene(canvas.viewport().rect().center())
    assert abs(current.x() - center.x()) <= 2
    assert abs(current.y() - center.y()) <= 2
    assert canvas._regions["target"].bbox() == [90, 70, 170, 110]


def test_actual_size_and_fit_keep_original_pixmap_pixels(canvas):
    original = canvas._pixmap_item.pixmap().toImage()
    canvas.show_actual_size()
    assert canvas.zoom_percent() == pytest.approx(100)
    assert canvas.transform().m11() * canvas.devicePixelRatioF() == pytest.approx(1)
    canvas.fit_image()
    assert canvas._pixmap_item.pixmap().toImage() == original
    assert (original.width(), original.height()) == (640, 480)


def test_selection_click_does_not_emit_fake_geometry_edit(canvas):
    geometry = []
    canvas.regionGeometryChanged.connect(lambda *args: geometry.append(args))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, canvas.mapFromScene(QPointF(160, 110)))
    assert [item.region_id for item in canvas.scene().selectedItems()] == ["target"]
    assert geometry == []


def test_numeric_bbox_rejects_outside_image_without_partial_update(canvas):
    previous = canvas._regions["target"].bbox()
    for bbox in ([10, 10, 800, 20], [0, 0, 0, 1], [0, 0, float("nan"), 20]):
        with pytest.raises(ValueError, match="bbox"):
            canvas.set_region_bbox("target", bbox)
        assert canvas._regions["target"].bbox() == previous


@pytest.mark.parametrize("start,end,expected", [
    ((160, 60), (160, 30), [80, 30, 160, 130]),
    ((80, 110), (40, 110), [40, 60, 200, 100]),
    ((240, 110), (300, 110), [80, 60, 220, 100]),
    ((160, 160), (160, 210), [80, 60, 160, 150]),
    ((80, 60), (-100, -100), [0, 0, 240, 160]),
    ((80, 60), (400, 300), [239, 159, 1, 1]),
])
def test_edge_handles_and_boundary_clamping(canvas, start, end, expected):
    canvas.show_actual_size()
    canvas.select_region("target")
    _drag(canvas, start, end)
    assert canvas._regions["target"].bbox() == pytest.approx(expected, abs=1)


def test_middle_drag_pans_without_changing_geometry(canvas):
    # 各 DPI 下都让画面大于视口，平移才有足够的滚动范围。
    canvas.set_zoom_percent(200 * canvas.devicePixelRatioF())
    canvas.centerOn(320, 240)
    center = canvas.mapToScene(canvas.viewport().rect().center())
    boxes = deepcopy({rid: item.bbox() for rid, item in canvas._regions.items()})
    geometry = []
    canvas.regionGeometryChanged.connect(lambda *args: geometry.append(args))
    start = canvas.viewport().rect().center()
    end = start + canvas.mapFromScene(QPointF(30, 20)) - canvas.mapFromScene(QPointF(0, 0))
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(canvas.viewport(), end, 10)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, end)
    after = canvas.mapToScene(canvas.viewport().rect().center())
    assert after.x() < center.x() - 20 and after.y() < center.y() - 10
    assert {rid: item.bbox() for rid, item in canvas._regions.items()} == boxes
    assert geometry == []
