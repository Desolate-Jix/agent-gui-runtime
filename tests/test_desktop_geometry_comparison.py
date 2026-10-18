"""只读原生截图框三方对照的离屏回归测试。"""
from __future__ import annotations

import base64
import copy
import hashlib
import math
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem

from app.desktop_review.geometry_comparison import GeometryComparisonWidget
from app.desktop_review.window import ensure_application


def _png(width: int, height: int, color: str) -> tuple[str, str]:
    ensure_application()
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    raw = bytes(buffer.data())
    return base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def _workspace():
    one, one_sha = _png(120, 80, "#eef3ff")
    two, two_sha = _png(200, 100, "#fff0ee")
    return {
        "task_id": "任务-甲", "batch_id": "batch-1", "source_ref": "a" * 64,
        "revision": 3,
        "batch": {
            "screenshots": [
                {"screenshot_id": "shot-one", "png_base64": one, "sha256": one_sha, "width": 120, "height": 80},
                {"screenshot_id": "shot-two", "png_base64": two, "sha256": two_sha, "width": 200, "height": 100},
            ],
            "interfaces": [
                {"interface_id": "screen-one", "meaning": "中文主界面", "screenshot_id": "shot-one", "regions": [
                    {"region_id": "region-one", "meaning": "打开详情", "bbox": [10, 12, 30, 20]},
                ]},
                {"interface_id": "screen-two", "meaning": "第二个界面", "screenshot_id": "shot-two", "regions": [
                    {"region_id": "region-two", "meaning": "导出按钮", "bbox": [50, 20, 60, 30]},
                ]},
            ],
        },
    }


def _comparison(workspace, diffs, *, status="current"):
    return {
        "contract_version": "desktop_relearn_comparison_v1",
        "task_id": workspace["task_id"], "batch_id": workspace["batch_id"],
        "source_ref": workspace["source_ref"], "workspace_revision": workspace["revision"],
        "candidate_id": "candidate-a", "candidate_sha256": "b" * 64,
        "review_baseline_sha256": "c" * 64, "status": status, "diffs": diffs,
    }


def _geometry(region, baseline, current, proposed):
    return {"target_type": "region", "target_id": region, "field": "bbox", "baseline": baseline, "current": current, "proposed": proposed}


def _pump():
    app = ensure_application()
    time.sleep(.01)
    app.processEvents()


def _rect(view):
    return next(item for item in view.scene().items() if isinstance(item, QGraphicsRectItem))


def test_draws_actual_png_and_three_geometry_frames_with_readonly_zoom_and_pan(tmp_path):
    workspace = _workspace()
    comparison = _comparison(workspace, [_geometry("region-one", [10, 12, 30, 20], [10, 12, 30, 20], [15, 14, 25, 18])])
    widget = GeometryComparisonWidget(workspace, comparison)
    widget.resize(900, 340); widget.show(); _pump()
    assert widget.comparison_title.text() == "截图框三方对照（只读）"
    assert widget.region_selector.currentData() == "region-one"
    for view, expected in ((widget.baseline_view, [10, 12, 30, 20]), (widget.current_view, [10, 12, 30, 20]), (widget.proposed_view, [15, 14, 25, 18])):
        pixmap = next(item for item in view.scene().items() if isinstance(item, QGraphicsPixmapItem))
        assert (pixmap.pixmap().width(), pixmap.pixmap().height()) == (120, 80)
        rect = _rect(view)
        assert [rect.pos().x(), rect.pos().y(), rect.rect().width(), rect.rect().height()] == expected
        assert not rect.flags() & QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
        assert view.dragMode() == view.DragMode.ScrollHandDrag
    before = [view.transform().m11() for view in (widget.baseline_view, widget.current_view, widget.proposed_view)]
    QTest.mouseClick(widget.zoom_in_button, Qt.MouseButton.LeftButton); _pump()
    assert all(view.transform().m11() > original for view, original in zip((widget.baseline_view, widget.current_view, widget.proposed_view), before))
    QTest.mouseClick(widget.zoom_out_button, Qt.MouseButton.LeftButton); QTest.mouseClick(widget.fit_button, Qt.MouseButton.LeftButton); _pump()
    assert "[10, 12, 30, 20]" in widget.baseline_bbox_label.text()
    assert "[15, 14, 25, 18]" in widget.proposed_bbox_label.text()
    screenshot = tmp_path / "geometry-comparison.png"
    assert widget.grab().save(str(screenshot), "PNG") and screenshot.is_file()
    widget.close()


def test_switches_to_actual_target_interface_and_stale_baseline_can_differ():
    workspace = _workspace()
    comparison = _comparison(workspace, [
        _geometry("region-one", [10, 12, 30, 20], [10, 12, 30, 20], [15, 14, 25, 18]),
        _geometry("region-two", [45, 20, 60, 30], [50, 20, 60, 30], [55, 21, 58, 29]),
    ], status="stale")
    widget = GeometryComparisonWidget(workspace, comparison)
    assert widget.region_selector.count() == 2
    widget.region_selector.setCurrentIndex(1); _pump()
    assert "第二个界面" in widget.region_selector.currentText()
    assert next(item for item in widget.current_view.scene().items() if isinstance(item, QGraphicsPixmapItem)).pixmap().width() == 200
    assert _rect(widget.baseline_view).pos().x() == 45
    widget.close()


def test_empty_geometry_is_explicit_and_does_not_fabricate_frames():
    workspace = _workspace()
    widget = GeometryComparisonWidget(workspace, _comparison(workspace, []))
    assert widget.region_selector.count() == 0
    assert "没有" in widget.empty_label.text()
    assert not any(isinstance(item, QGraphicsRectItem) for item in widget.current_view.scene().items())
    widget.close()


@pytest.mark.parametrize("mutate", [
    lambda workspace, comparison: comparison.__setitem__("task_id", "other"),
    lambda workspace, comparison: comparison.__setitem__("workspace_revision", True),
    lambda workspace, comparison: comparison.__setitem__("candidate_sha256", "not-a-hash"),
    lambda workspace, comparison: comparison["diffs"][0].__setitem__("current", [9, 12, 30, 20]),
    lambda workspace, comparison: comparison["diffs"][0].__setitem__("proposed", [100, 1, 30, 20]),
    lambda workspace, comparison: comparison["diffs"][0].__setitem__("proposed", [1, 1, True, 3]),
    lambda workspace, comparison: comparison["diffs"][0].__setitem__("proposed", [10 ** 1000, 1, 3, 3]),
    lambda workspace, comparison: workspace["batch"]["screenshots"][0].__setitem__("sha256", "0" * 64),
])
def test_rejects_bad_identity_hash_or_unclipped_bbox(mutate):
    workspace = _workspace()
    comparison = _comparison(workspace, [_geometry("region-one", [10, 12, 30, 20], [10, 12, 30, 20], [15, 14, 25, 18])])
    mutate(workspace, comparison)
    with pytest.raises(ValueError):
        GeometryComparisonWidget(workspace, comparison)


def test_current_status_requires_saved_baseline_equal_current():
    workspace = _workspace()
    comparison = _comparison(workspace, [_geometry("region-one", [9, 12, 30, 20], [10, 12, 30, 20], [15, 14, 25, 18])])
    with pytest.raises(ValueError, match="baseline"):
        GeometryComparisonWidget(workspace, comparison)
