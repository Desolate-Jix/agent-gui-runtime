from copy import deepcopy
from io import BytesIO

from PIL import Image
import pytest
from PySide6.QtWidgets import QApplication

from app.desktop_review.canvas import ReviewCanvas

_APP = QApplication.instance() or QApplication([])


def _png():
    stream = BytesIO()
    Image.new('RGB', (100, 80), (11, 27, 45)).save(stream, format='PNG')
    return stream.getvalue()


def test_raw_png_graph_regions_render_without_a_batch_and_preserve_input():
    canvas = ReviewCanvas()
    regions = [{'region_id': 'graph-region', 'bbox': [2, 3, 25, 30]}]
    original = deepcopy(regions)
    canvas.set_image(_png(), regions, ('workflow', 'node', 'capture'))
    assert canvas._pixmap_item.pixmap().width() == 100
    assert canvas._pixmap_item.pixmap().height() == 80
    assert canvas._pixmap_item.pixmap().toImage().pixelColor(1, 1).getRgb() == (11, 27, 45, 255)
    canvas.select_region('graph-region')
    assert canvas._regions['graph-region'].isSelected()
    canvas.set_region_bbox('graph-region', [4, 5, 26, 31])
    assert regions == original


def test_same_original_png_preserves_view_when_graph_box_revision_changes():
    canvas = ReviewCanvas()
    canvas.set_image(_png(), [{'region_id': 'r', 'bbox': [2, 3, 25, 30]}], ('x', 'node', 'capture'))
    canvas.set_zoom_percent(250)
    transform = canvas.transform()
    canvas.set_image(_png(), [{'region_id': 'r', 'bbox': [5, 6, 27, 31]}], ('x', 'node', 'capture'))
    assert canvas.transform() == transform
    assert canvas._regions['r'].bbox() == [5, 6, 27, 31]


@pytest.mark.parametrize('case', ['png', 'bbox', 'duplicate_region'])
def test_invalid_graph_image_or_boxes_leave_previous_evidence_visible(case):
    canvas = ReviewCanvas()
    regions = [{'region_id': 'r', 'bbox': [2, 3, 25, 30]}]
    png = _png()
    canvas.set_image(png, regions, ('x',))
    previous = canvas._pixmap_item
    if case == 'png':
        png = b'invalid PNG'
    elif case == 'bbox':
        regions[0]['bbox'] = [99, 3, 25, 30]
    else:
        regions.append(deepcopy(regions[0]))
    with pytest.raises(ValueError):
        canvas.set_image(png, regions, ('y',))
    assert canvas._pixmap_item is previous
    assert canvas._regions['r'].bbox() == [2, 3, 25, 30]
