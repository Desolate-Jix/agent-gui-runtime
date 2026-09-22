"""完整当前 UIA 不允许泛型字段意图退化为框外合成按钮。"""
import pytest

from app.api import vision


GOAL = "Click the search input field at the top left of the webpage"


def controls():
    return [
        {"control_id": "field", "runtime_id": [42, 1], "name": "\ufffc", "control_type": "ComboBox",
         "patterns": ["Value", "Text", "ExpandCollapse"], "enabled": True, "visible": True,
         "bbox": {"x": 116, "y": 103, "w": 246, "h": 24}},
        {"control_id": "address", "runtime_id": [42, 2], "name": "Address", "control_type": "Edit",
         "patterns": ["Value", "Text"], "enabled": True, "visible": True,
         "bbox": {"x": 104, "y": 48, "w": 1917, "h": 24}},
        {"control_id": "suggestions", "runtime_id": [42, 3], "name": "Suggestions", "control_type": "DataGrid",
         "patterns": [], "enabled": True, "visible": True,
         "bbox": {"x": 92, "y": 140, "w": 376, "h": 402}},
    ]


@pytest.mark.parametrize("items", [controls(), [], controls()[2:]])
def test_complete_uia_without_field_point_hit_is_not_a_visual_fallback(items):
    inventory = {"status": "ready", "uia_scan_complete": True, "uia_scan_truncated": False,
        "screen_reading": {"source_layers": {"windows_uia": {
            "status": "ok", "scan_complete": True, "truncated": False, "controls": items}}}}
    assert vision._vista_direct_current_uia_identity(goal=GOAL, target_text=None,
        point={"x": 128, "y": 140}, fast_inventory=inventory, candidates=[]) == (
            None, "generic_field_current_uia_point_missing")


@pytest.mark.parametrize("status,complete,expected", [
    ("unavailable", None, None),
    ("ready", False, "vista_direct_current_uia_scan_incomplete"),
])
def test_unavailable_and_incomplete_uia_keep_distinct_contracts(status, complete, expected):
    assert vision._vista_direct_current_uia_identity(goal=GOAL, target_text=None,
        point={"x": 128, "y": 140}, fast_inventory={"status": status, "uia_scan_complete": complete},
        candidates=[]) == (None, expected)


def test_unknown_scan_completion_is_not_promoted_to_complete():
    inventory = {"status": "ready", "screen_reading": {"source_layers": {"windows_uia": {
        "status": "ok", "controls": controls()}}}}
    assert vision._vista_direct_current_uia_identity(goal=GOAL, target_text=None,
        point={"x": 128, "y": 140}, fast_inventory=inventory, candidates=[]) == (None, None)


def test_map10_sanitized_primary_replay_rejects_original_model_point(tmp_path, monkeypatch):
    from PIL import Image
    from app.core.local_recognition_policy import local_recognition_selection
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult

    image = tmp_path / "synthetic-map10.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    calls = []
    point = {"x": 128, "y": 140}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or
        {"point": dict(point), "provider": "recorded-model-point-only"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=GOAL,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot({"status": "ok", "scan_complete": True, "truncated": False,
                             "controls": controls()}), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=GOAL,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    assert len(calls) == 1
    assert result["recommended_target"] is None
    assert result["candidate_result"]["recommended_candidate_id"] is None
    assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] == "generic_field_current_uia_point_missing"
    rejected = result["candidate_result"]["rejected"]
    direct = [item for item in rejected if item["candidate_id"].startswith("vista_direct_")]
    assert len(direct) == 1 and direct[0]["element"]["click_point"] == point
    # 派发前的实际选择入口必须拒绝，不能借 operator 模式执行合成点。
    dispatch = []
    with pytest.raises(ValueError):
        selected = local_recognition_selection(result, image_path=image, viewport_size={"width": 2560, "height": 1400})
        dispatch.append(selected)
    assert dispatch == []
