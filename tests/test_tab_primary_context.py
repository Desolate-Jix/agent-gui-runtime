"""明确标签应先用本次唯一 TabItem 裁图，不让整窗缩图丢失小字。"""
from copy import deepcopy

import pytest
from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("variant,expected", [("unique", "roi"), ("duplicate", "full"), ("incomplete", "full")])
@pytest.mark.parametrize("kind,role,label,box,point", [
    ("Button", "button", "还原", {"x": 1280, "y": 0, "w": 46, "h": 40}, {"x": 1303, "y": 20}),
    ("TabItem", "tab", "独立界面库", {"x": 72, "y": 46, "w": 84, "h": 23}, {"x": 114, "y": 57}),
    ("ListItem", "list item", "百科城市条目 · read-dunedin-text / after",
     {"x": 13, "y": 64, "w": 1074, "h": 17}, {"x": 55, "y": 72}),
    ("ListItem", "list item", "候选 1",
     {"x": 22, "y": 533, "w": 259, "h": 17}, {"x": 44, "y": 541}),
])
def test_exact_tab_uses_current_unique_identity_before_inference(tmp_path, monkeypatch, variant, expected, kind, role, label, box, point, language):
    image = tmp_path / "native.png"
    Image.new("RGB", (1380, 900), "white").save(image)
    control = {"control_id": "tab-library", "runtime_id": [42, 1], "name": label,
        "control_type": kind, "patterns": ["SelectionItem"], "enabled": True,
        "visible": True, "bbox": box}
    snapshot = {"status": "ok", "scan_complete": variant != "incomplete", "truncated": False,
                "controls": [control]}
    if variant == "duplicate":
        other = deepcopy(control)
        other.update(control_id="other-tab", runtime_id=[42, 2], bbox={"x": 250, "y": 46, "w": 84, "h": 23})
        snapshot["controls"].append(other)
    calls = []

    def roi(**kwargs):
        calls.append(("roi", kwargs))
        return {"point": point, "provider": "isolated-model-boundary"}

    def full(**kwargs):
        calls.append(("full", kwargs))
        return {"point": point, "provider": "isolated-model-boundary"}

    monkeypatch.setattr(vision, "_call_vista_point_grounding", roi)
    monkeypatch.setattr(vision, "_call_vista_point_prompt", full)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    goal = f'Click the {role} labelled "{label}"'
    if language == 'zh':
        cn_role = {'tab': '标签页', 'list item': '列表项', 'button': '按钮'}[role]
        goal = f'点击名为“{label}”的{cn_role}'
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element",
        goal=goal, agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"vista_direct_grounding": {"refine": False}},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=1380, height=900), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    assert calls[0][0] == expected
    if expected == "roi":
        assert len(calls[0][1]["candidates"]) == 1
        assert calls[0][1]["candidates"][0].role == role.replace(" ", "")
        if kind == "ListItem" and box["w"] > 1000:
            pre = calls[0][1]["image_preprocess"]
            assert pre["roi_policy"] == "thin_list_row_window_context_primary"
            assert pre["original_size"] == {"width": 1380, "height": 900}
            assert pre["processed_size"]["width"] == 1024
            assert "crop_bounds_original" not in pre
            return
        crop = calls[0][1]["image_preprocess"]["crop_bounds_original"]
        if kind == "ListItem":
            # 短行不缩小，保留局部上下文；不因原始行高低于18像素就退回整窗。
            assert calls[0][1]["image_preprocess"]["processed_size"]["width"] <= 448
        assert crop["x"] <= box["x"] and crop["y"] <= box["y"]
        assert crop["x"] + crop["w"] >= box["x"] + box["w"]
        assert crop["y"] + crop["h"] >= box["y"] + box["h"]
