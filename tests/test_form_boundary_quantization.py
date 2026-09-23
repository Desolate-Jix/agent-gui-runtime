"""唯一当前文本字段沿用有限近框容差，派发点必须回到真实框内部。"""
import pytest
from PIL import Image
from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRResult


@pytest.mark.parametrize("y,accepted", [(237, True), (236, True), (235, False), (230, False), (229, False), (240, True)])
def test_exact_editable_field_boundary_rounding(tmp_path, monkeypatch, y, accepted):
    image = tmp_path / "frame.png"
    Image.new("RGB", (1278, 1285), "white").save(image)
    box = {"x": 461, "y": 238, "w": 356, "h": 38}
    controls = [dict(control_id="field", runtime_id=[42, 354], name="Place",
        control_type="ComboBox", patterns=["Value", "Text", "ExpandCollapse"],
        bbox=box, enabled=True, visible=True)]
    snapshot = dict(status="ok", scan_complete=True, truncated=False, controls=controls)
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: {
        "point": {"x": 510, "y": y}, "provider": "recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    goal = 'Click the input labelled "Place"'
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=ImageSize(width=1278, height=1285), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    from app.core.local_recognition_policy import local_recognition_selection
    if not accepted:
        with pytest.raises(ValueError):
            local_recognition_selection(result, image_path=image, viewport_size={"width": 1278, "height": 1285})
    else:
        selected = local_recognition_selection(result, image_path=image, viewport_size={"width": 1278, "height": 1285})
        assert selected is not None
        local = result["narrow_search_result"]["results"][0]
        p = local["refined_click_point"]
        assert 461 <= p["x"] < 817 and 238 <= p["y"] < 276
        if y < 238:
            assert local["coordinate_source"] == "current_uia_vista_near_bbox_reconciled_v1"
