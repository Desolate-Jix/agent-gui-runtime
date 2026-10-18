"""排序中的同名背景控件不能替换模型实际选中的目标。"""
from PIL import Image
import pytest
from copy import deepcopy

from app.api import vision
from app.agent.live_runtime_composition import _parse_candidate_result, _parse_local_grounding, _parse_recognition
from app.core.local_recognition_policy import local_recognition_selection
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult


@pytest.mark.parametrize("top_k", [1, 5])
def test_direct_model_selection_and_candidate_recommendation_share_identity(tmp_path, monkeypatch, top_k):
    image = tmp_path / "current.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    goal = "Click the Quick search input at the top right of the documentation page"
    point = {"x": 2253, "y": 105}
    snapshot = {"status": "ok", "provider": "windows_uia", "scan_complete": True, "truncated": False,
        "controls": [{"control_id": "background-tab", "name": "Search documentation", "control_type": "TabItem",
                      "bbox": {"x": 271, "y": 0, "w": 256, "h": 41}, "visible": True, "enabled": True,
                      "patterns": ["SelectionItem"]}]}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kwargs: {"point": dict(point)})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        provider_mode="local_grounding", agent_mode="execute", top_k=top_k,
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={"vista_direct_grounding": {"refine": False}})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "boundary"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    plan = response.data["result"]
    ranking = plan["candidate_result"]
    selected = plan["narrow_search_result"]["recommended_candidate_id"]
    if top_k > 1:
        assert ranking["candidates"][0]["element"]["evidence"]["screen_inventory_action"]["source_id"] == "background-tab"
    assert ranking["recommended_candidate_id"] == selected
    assert plan["recommended_target"]["candidate_id"] == selected
    decision = plan["pre_click_decision"]
    assert decision["selected_candidate_id"] in (None, selected)
    if decision["selected_candidate_id"] is None:
        assert decision["allowed"] is False
    chosen = local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1400})
    assert chosen["selected_candidate_id"] == selected and chosen["selected_click_point"] == point
    # 几何一致不代表独立命中证明，也不把未验证 OCR 改成已验证。
    assert chosen["candidate_decisions"][0]["original_grounding_status"] == "unverified"
    # 下游解析也须保留明确选中的身份，不按文本排序偷偷换绑。
    parsed, grounded = _parse_recognition(plan)
    assert parsed.recommended_candidate_id == grounded.recommended_candidate_id == selected
    assert [item.candidate_id for item in parsed.candidates] == [item["candidate_id"] for item in ranking["candidates"]]
    expected_margin = (round(ranking["candidates"][0]["score"] - ranking["candidates"][1]["score"], 4)
                       if top_k > 1 else ranking["candidates"][0]["score"])
    assert parsed.margin_to_second == expected_margin
    assert next(item for item in grounded.results if item.candidate_id == selected).status == "unverified"
    for bad_id in ("unknown-candidate", None):
        malformed = deepcopy(ranking)
        malformed["recommended_candidate_id"] = bad_id
        with pytest.raises(ValueError, match="candidate recommendation is inconsistent"):
            _parse_candidate_result(malformed)
        malformed_local = deepcopy(plan["narrow_search_result"])
        malformed_local["recommended_candidate_id"] = bad_id
        with pytest.raises(ValueError, match="local grounding recommendation is inconsistent"):
            _parse_local_grounding(malformed_local)
