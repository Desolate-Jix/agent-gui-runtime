"""辅助功能组合名称不能被当作按钮上实际绘制的文字。"""
from types import SimpleNamespace

import pytest

from app.api import vision
from app.vision.model_workers.vista_openai_server import _vista_prompt
from app.vision.schemas import BBox


@pytest.mark.parametrize("raw_name", ["File input: test7-candidate02.txt", "选择文件: 未选择文件"])
def test_bound_button_keeps_original_action_without_inventing_visible_caption(raw_name):
    goal = "Click the choose file button labelled File input"
    item = SimpleNamespace(candidate_id="current-button", label="File input", role="button",
        refined_bbox=None, element=SimpleNamespace(bbox=BBox(x=998, y=308, w=416, h=38),
            evidence={"current_uia_form_label_binding": {"label": "File input"},
                      "current_uia_form_control_name": raw_name}))
    effective = _vista_prompt(vision._vista_point_prompt(goal, [item]))
    assert f"button labelled {raw_name!r}" not in effective
    assert f"Original instruction: {goal}" in effective
    assert "associated with the visible field label 'File input'" in effective
    assert "accessibility name" in effective
    assert raw_name in effective
    assert "not the printed label" in effective


@pytest.mark.parametrize("source,bound,count,tight", [
    ("current_uia_candidate_v1", True, 1, True),
    ("top1_only", True, 1, False),
    ("current_uia_candidate_v1", False, 1, False),
    ("current_uia_candidate_v1", True, 2, False),
])
def test_only_unique_current_bound_button_excludes_external_label_pixels(tmp_path, source, bound, count, tight):
    from PIL import Image
    from app.core.runtime_artifacts import pinned_runtime_output_root
    from app.vision.schemas import ImageSize
    from tests.test_selection_control_roi_context import candidate
    path = tmp_path / "screen.png"
    Image.new("RGB", (2412, 1040), "white").save(path)
    box = {"x": 998, "y": 308, "w": 416, "h": 38}
    item = candidate("button", "File input", box)
    item.element.evidence = {"current_uia_form_label_binding": {"label": "File input", "bbox": box}} if bound else {}
    with pinned_runtime_output_root(tmp_path):
        result = vision._prepare_vista_candidate_roi_image(path, ImageSize(width=2412, height=1040),
            candidates=[item] * count, padding=12, min_size=96, max_edge=448, roi_source=source)
    crop = result["crop_bounds_original"]
    if tight:
        assert crop == box
        assert result["context_reason"] == "current_bound_button_control_pixels"
        assert result["processed_size"]["height"] >= 76
    else:
        assert crop["y"] < box["y"]
    assert result["pathgraph_candidates"][0]["bbox_original"] == box
