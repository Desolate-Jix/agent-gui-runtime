"""完整目标标签不能被搜索框中的同名短前缀挤出排名。"""
import pytest
from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult


@pytest.mark.parametrize("label,partial", [("临时删除·工作台流程页", "临时删除"), ("Project Alpine", "Project")])
@pytest.mark.parametrize("point,expected", [({"x": 51, "y": 169}, True), ({"x": 51, "y": 90}, False)])
def test_explicit_full_list_label_outranks_short_filter_value(tmp_path, monkeypatch, label, partial, point, expected):
    image = tmp_path / "list.png"
    Image.new("RGB", (1380, 900), "white").save(image)
    controls = [
        {"control_id": "filter", "runtime_id": [1], "name": partial, "control_type": "Edit",
         "patterns": ["Value", "Text"], "enabled": True, "visible": True,
         "bbox": {"x": 11, "y": 80, "w": 1026, "h": 21}},
        {"control_id": "wanted", "runtime_id": [2], "name": label + " 新学内容 · 修订 1", "control_type": "ListItem",
         "patterns": ["SelectionItem"], "enabled": True, "visible": True,
         "bbox": {"x": 13, "y": 160, "w": 325, "h": 32}},
    ]
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kwargs: {"point": point})
    monkeypatch.setattr(vision, "_call_vista_point_grounding", lambda **kwargs: {"point": point})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    goal = f'Click the first list item labelled "{label}" in the left interface list'
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element",
        goal=goal, agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"vista_direct_grounding": {"refine": False}},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot({"status": "ok", "scan_complete": True, "truncated": False, "controls": controls}), pinned_runtime_output_root(tmp_path):
        result = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=1380, height=900), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    # 模型点仍须与本帧真实列表框相符，不能用过滤框或静态坐标替代。
    chosen = result.data["result"]["recommended_target"]
    if not expected:
        assert chosen is None
        return
    assert chosen is not None
    assert chosen["element"]["evidence"]["screen_inventory_action"]["source_id"] == "wanted"
    assert chosen["element"]["evidence"]["vista_direct_identity"]["point"] == {"x": 51, "y": 169}
