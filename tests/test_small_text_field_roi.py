"""小文本字段首轮定位保持标签上下文和真实坐标，不以扩大点击框纠错。"""
import pytest
from PIL import Image
from app.api import vision
from app.vision.schemas import ImageSize
from app.core.runtime_artifacts import pinned_runtime_output_root
from tests.test_selection_control_roi_context import candidate


@pytest.mark.parametrize("width,height", [(178, 21), (356, 28), (512, 24)])
def test_small_named_text_field_gets_readable_primary_crop(tmp_path, width, height):
    path = tmp_path / "small-field.png"
    Image.new("RGB", (1278, 1285), "white").save(path)
    box = {"x": 138, "y": 100, "w": width, "h": height}
    target = candidate("input", "Customer name:", box)
    snapshot = {"scan_complete": True, "controls": [{"name": "Customer name:",
        "control_type": "Text", "visible": True, "bbox": {"x": 12, "y": 100, "w": 122, "h": 21}}]}
    with pinned_runtime_output_root(tmp_path):
        result = vision._prepare_vista_candidate_roi_image(path, ImageSize(width=1278, height=1285),
            candidates=[target], padding=12, min_size=96, max_edge=448,
            roi_source="current_uia_candidate_v1", uia_snapshot=snapshot)
    assert result["context_reason"] == "small_text_field_label_context"
    assert result["context_label_count"] == 1
    scale = result["transform"]["scale_original_to_processed"]
    assert height * scale["y"] >= 39
    assert result["crop_bounds_original"]["x"] <= 12
    assert result["pathgraph_candidates"][0]["bbox_original"] == box
    assert target.element.bbox.to_dict() == box
    assert scale["y"] * result["transform"]["scale_processed_to_original"]["y"] == pytest.approx(1)
    assert result["processed_size"]["width"] <= 2304


def test_regular_height_text_field_keeps_existing_crop(tmp_path):
    path = tmp_path / "regular-field.png"
    Image.new("RGB", (1278, 1285), "white").save(path)
    target = candidate("input", "Text input", {"x": 81, "y": 168, "w": 356, "h": 38})
    with pinned_runtime_output_root(tmp_path):
        result = vision._prepare_vista_candidate_roi_image(path, ImageSize(width=1278, height=1285),
            candidates=[target], padding=12, min_size=96, max_edge=448,
            roi_source="current_uia_candidate_v1")
    assert "context_reason" not in result
    assert result["processed_size"] == {"width": 380, "height": 96}
