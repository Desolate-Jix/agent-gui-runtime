"""明确标题和位置说明分开；精确链接仍拒绝模型返回的框外点。"""
import json

import pytest
from PIL import Image

from app.api import vision
from app.core.local_recognition_policy import local_recognition_selection
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.recognition.text_match import explicit_target_label, explicit_target_role
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult


@pytest.mark.parametrize("point,allowed", [({"x": 540, "y": 454}, True), ({"x": 412, "y": 440}, False)])
def test_quoted_link_context_keeps_exact_identity_and_rejects_observed_miss(tmp_path, monkeypatch, point, allowed):
    label = "asyncio — Asynchronous I/O"
    goal = (f"Open the visible search result link titled {json.dumps(label, ensure_ascii=False)}, "
            "the second result below Search Results, to read the module documentation.")
    assert explicit_target_label(goal) == label and explicit_target_role(goal) == "link"
    assert f'labelled "{label}".' in vision._vista_direct_prompt(goal)
    assert goal in vision._vista_direct_prompt(goal)
    image = tmp_path / "fresh-link.png"
    Image.new("RGB", (1410, 1032), "white").save(image)
    box = {"x": 429, "y": 443, "w": 222, "h": 22}
    snapshot = {"status": "ok", "scan_complete": True, "truncated": False, "controls": [
        {"control_id": "module", "runtime_id": [42, 1], "name": "asyncio", "control_type": "Hyperlink",
         "patterns": ["Invoke"], "visible": True, "enabled": True, "bbox": {"x": 429, "y": 406, "w": 57, "h": 22}},
        {"control_id": "documentation", "runtime_id": [42, 2], "name": label, "control_type": "Hyperlink",
         "patterns": ["Invoke"], "visible": True, "enabled": True, "bbox": box}]}
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kwargs: calls.append(kwargs) or
                        {"point": dict(point), "provider": "recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=1410, height=1032), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    assert len(calls) == 1 and calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
    result = response.data["result"]
    identity = result["candidate_result"]["summary"]["current_uia_literal_identity"]
    assert identity["match_count"] == 1
    assert result["recommended_target"]["element"]["bbox"] == box
    if allowed:
        selected = local_recognition_selection(result, image_path=image, viewport_size={"width": 1410, "height": 1032})
        assert selected["selected_click_point"] == point
    else:
        with pytest.raises(ValueError, match="outside candidate"):
            local_recognition_selection(result, image_path=image, viewport_size={"width": 1410, "height": 1032})
