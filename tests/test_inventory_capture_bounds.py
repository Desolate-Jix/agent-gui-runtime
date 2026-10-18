"""客户区外的 UIA 控件可作原始证据，但不得形成可操作候选。"""
from copy import deepcopy
import pytest
from app.operation.screen_inventory import build_screen_inventory


@pytest.mark.parametrize("bbox", [
    {"x": 0, "y": -30, "w": 40, "h": 20},
    {"x": -4, "y": 10, "w": 40, "h": 20},
    {"x": 890, "y": 10, "w": 40, "h": 20},
    {"x": 10, "y": 550, "w": 40, "h": 20},
])
def test_out_of_surface_controls_are_not_clamped_into_actionable_candidates(bbox):
    control = {"name": "frame button", "control_type": "Button", "visible": True,
               "enabled": True, "patterns": ["Invoke"], "bbox": bbox}
    good = {**control, "name": "查看示例详情", "bbox": {"x": 20, "y": 82, "w": 98, "h": 28}}
    screen = {"image_size": {"width": 900, "height": 560},
              "source_layers": {"windows_uia": {"controls": [control, good]}}}
    original = deepcopy(screen)
    result = build_screen_inventory(screen)
    assert [a["label"] for a in result["available_actions"]] == ["查看示例详情"]
    assert result["summary"]["excluded_outside_capture_count"] == 1
    assert screen == original
