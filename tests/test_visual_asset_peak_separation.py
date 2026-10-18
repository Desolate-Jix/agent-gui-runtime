"""局部模板峰值分离回归；仅使用全新临时图片，不派发输入。"""
import numpy as np
from PIL import Image
import pytest

from app.operation.visual_asset_matching import match_visual_asset, _top_template_locations


@pytest.mark.parametrize("offset", [(10, 0), (0, 10), (6, 0)])
def test_nonoverlapping_small_duplicate_controls_are_ambiguous(tmp_path, offset):
    rng = np.random.default_rng(7)
    pixels = rng.integers(0, 256, (60, 80, 3), dtype=np.uint8)
    template = pixels[20:26, 20:26].copy()
    dx, dy = offset
    pixels[20+dy:26+dy, 20+dx:26+dx] = template
    template_path, target_path = tmp_path / "template.png", tmp_path / "current.png"
    Image.fromarray(template).save(template_path)
    Image.fromarray(pixels).save(target_path)

    result = match_visual_asset(asset_id="small-control", template_path=template_path,
        target_image_path=target_path, label="control", semantic_action="locate_control",
        scales=(1.0,), methods=("gray_template",), min_score=0.92, min_score_gap=0.04)

    assert result["ambiguous"] is True
    assert result["matched"] is False
    assert {(row["bbox"]["x"], row["bbox"]["y"]) for row in result["top_candidates"]} == {
        (20, 20), (20+dx, 20+dy)}
    assert result["can_authorize_click"] is False


def test_unique_small_control_remains_matched(tmp_path):
    pixels = np.random.default_rng(7).integers(0, 256, (60, 80, 3), dtype=np.uint8)
    template_path, target_path = tmp_path / "template.png", tmp_path / "current.png"
    Image.fromarray(pixels[20:26, 20:26]).save(template_path)
    Image.fromarray(pixels).save(target_path)
    result = match_visual_asset(asset_id="small-control", template_path=template_path,
        target_image_path=target_path, label="control", semantic_action="locate_control",
        scales=(1.0,), methods=("gray_template",), min_score=0.92, min_score_gap=0.04)
    assert result["matched"] is True
    assert result["ambiguous"] is False
    assert result["bbox"] == {"x": 20, "y": 20, "w": 6, "h": 6}


@pytest.mark.parametrize("template_size,overlapping,distinct", [
    ((6, 6), (12, 10), (20, 10)),
    ((60, 20), (23, 10), (80, 10)),
    ((20, 60), (10, 23), (10, 80)),
])
def test_overlapping_response_peaks_do_not_hide_next_distinct_target(
        template_size, overlapping, distinct):
    response = np.zeros((100, 100), dtype=np.float32)
    response[10, 10] = 1.0
    response[overlapping[1], overlapping[0]] = 0.99
    response[distinct[1], distinct[0]] = 0.97
    peaks = _top_template_locations(response, limit=2, template_size=template_size)
    assert [row["location"] for row in peaks] == [(10, 10), distinct]


def test_exhausted_response_does_not_reintroduce_suppressed_peak():
    peaks = _top_template_locations(np.ones((1, 1), dtype=np.float32),
        limit=2, template_size=(6, 6))
    assert len(peaks) == 1
    assert peaks[0]["location"] == (0, 0)
