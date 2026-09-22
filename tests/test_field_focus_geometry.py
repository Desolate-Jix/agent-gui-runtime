"""字段已被本帧粗定位命中时，不让裁图细化重新选择另一个控件。"""
import pytest
from app.api import vision


def snapshot():
    return {"status": "ok", "scan_complete": True, "truncated": False, "controls": [
        {"control_id": "search", "runtime_id": [42, 1], "name": "搜索",
         "control_type": "ComboBox", "patterns": ["Value", "Text"],
         "enabled": True, "visible": True, "bbox": {"x": 235, "y": 113, "w": 700, "h": 40}},
        {"control_id": "address", "runtime_id": [42, 2], "name": "地址和搜索栏",
         "control_type": "Edit", "patterns": ["Value", "Text"],
         "enabled": True, "visible": True, "bbox": {"x": 104, "y": 48, "w": 2152, "h": 24}},
    ]}


@pytest.mark.parametrize("goal,expected", [
    ("Click the Google search input field at the top of the results page", True),
    ("Click inside the text area", True),
    ("Click the search button next to the input box", False),
    ("Double click the word museum inside the search input box", False),
    ("Click the icon inside the search input box", False),
])
def test_only_field_focus_uses_full_context(goal, expected):
    assert vision._field_focus_uses_full_context(goal) is expected


@pytest.mark.parametrize("uia_ready", [True, False])
def test_recognition_does_not_refine_a_field_into_the_address_bar(tmp_path, monkeypatch, uia_ready):
    from PIL import Image
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image = tmp_path / "page.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    calls = []
    def infer(**kwargs):
        calls.append(kwargs)
        return {"point": {"x": 496, "y": 140} if len(calls) == 1 else {"x": 299, "y": 51},
                "provider": "isolated-model-boundary"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", infer)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    goal = "Click the search input field at the top of the results page"
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"vista_direct_grounding": {"refine": True}},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    uia = snapshot()
    if not uia_ready:
        # 未提供 UIA 与完整树未命中字段不同；此项只覆盖真正不可用时的像素路径。
        uia = {"status": "unavailable", "scan_complete": None, "truncated": False, "controls": []}
    with pinned_uia_snapshot(uia), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    assert len(calls) == 1
    result = response.data["result"]
    chosen = result["recommended_target"]
    # UIA 元素仍保存原中心；实际模型点保存在对应的细化结果，不能把两者混用。
    local = [item for item in result["narrow_search_result"]["results"]
             if item["candidate_id"] == chosen["candidate_id"]]
    assert len(local) == 1
    assert local[0]["refined_click_point"] == {"x": 496, "y": 140}
