"""普通执行只使用本帧视觉坐标；测试禁止真实模型、网络和桌面读取。"""
from types import SimpleNamespace

import pytest
from PIL import Image

from app.api import vision
from app.api.models.request import VisionRecognitionPlanRequestModel
from app.vision.schemas import BBox, ImageSize, VisionAnalyzeResponse, VisionTarget


@pytest.fixture
def direct_scene(tmp_path, monkeypatch):
    image = tmp_path / "fresh-direct.png"
    Image.new("RGB", (800, 600), "white").save(image)
    calls = []
    state = {"raw": "[250, 500]"}
    config = {"vision": {"mode": "local_grounding", "local_grounding": {
        "model_name": "isolated-vista", "endpoint": "http://unused.invalid",
        "output_contract": "vista_point_v1"}}}
    monkeypatch.setattr(vision.VisionProviderFactory, "load_config", lambda: config)
    monkeypatch.setattr(vision.VisionProviderFactory, "create", lambda **kw: state.get("provider", object()))
    def forbidden(*args, **kwargs):
        pytest.fail("direct visual must not read UIA, OCR, learned memory, or recall")
    for name in ("_load_observe_trace_reuse", "_build_path_graph_recall", "_build_visual_asset_recall",
                 "_execute_fast_inventory_from_uia", "_corroborate_vista_direct_point"):
        monkeypatch.setattr(vision, name, forbidden)
    monkeypatch.setattr(vision.uia_provider, "snapshot_bound_window", forbidden)
    monkeypatch.setattr(vision.ocr_service, "scan_image", forbidden)
    def endpoint(self, path, prompt, **kwargs):
        calls.append({"image_path": str(path), "prompt": prompt, **kwargs})
        if state.get("error"):
            raise state["error"]
        if state.get("mutate"):
            Image.new("RGB", (800, 600), "red").save(image)
        return {"choices": [{"message": {"content": state["raw"]}}]}
    monkeypatch.setattr(vision.LocalVisionProvider, "_call_openai_compatible_endpoint", endpoint)
    def run(**kwargs):
        return vision.recognition_plan(VisionRecognitionPlanRequestModel(image_path=str(image),
            goal="Click the reports button", provider_mode=kwargs.pop("provider_mode", "local_grounding"),
            metadata={"execution_grounding": "direct_visual", **kwargs.pop("metadata", {})},
            write_policy={"path_graph": False, "element_memory": False, "trace": False}, **kwargs))
    return run, calls, state, config, image


def test_selected_point_model_called_without_uia_or_recall(direct_scene):
    run, calls, _, _, image = direct_scene
    response = run(metadata={"visual_target": {"name": "reports", "control_type": "Button"}})
    assert response.success, response.error
    result = response.data["result"]
    assert len(calls) == 1 and calls[0]["image_path"] == str(image)
    assert "reports" in calls[0]["prompt"] and "Button" in calls[0]["prompt"]
    assert result["pre_click_decision"]["allowed"] is True
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 200, "y": 300}
    assert result["candidate_freshness_decision"]["allowed"] is True
    assert result["execution_path"]["execution_grounding"] == "direct_visual"
    assert result["execution_path"]["screen_inventory_used"] is False


@pytest.mark.parametrize("raw", ["[-1, 500]", "[1001, 500]", "[NaN, 500]",
    "[true, 500]", "not a point",
    '["250", 500]', '{"x":250,"x":500,"y":500}',
    '{"point":{"x":200,"y":300,"coordinate_space":"pixel","confidence":0.1}}',
    '{"point":{"x":800,"y":300,"coordinate_space":"pixel"}}',
    '{"point":{"x":200,"y":300,"coordinate_space":"pixel"},"confidence":0.2}',
    '{"status":"ambiguous","point":{"x":200,"y":300,"coordinate_space":"pixel"}}'])
def test_invalid_or_uncertain_point_is_rejected_without_fallback(direct_scene, raw):
    run, calls, state, _, _ = direct_scene
    state["raw"] = raw
    response = run()
    assert response.success is False
    assert len(calls) == 1
    assert response.data["model_io"]["model_io"]["raw_text"] == raw


def test_provider_failure_is_not_replaced_by_controls(direct_scene):
    run, calls, state, _, _ = direct_scene
    state["error"] = RuntimeError("isolated model failed")
    response = run()
    assert response.success is False
    assert "isolated model failed" in str(response.error.details)
    assert len(calls) == 1


def test_same_path_capture_replacement_rejects_model_result(direct_scene):
    run, calls, state, _, _ = direct_scene
    state["mutate"] = True
    response = run()
    assert response.success is False
    assert "capture_changed" in str(response.error.details)
    assert len(calls) == 1


def test_explicit_refinement_uses_same_visual_provider_and_transform(direct_scene, tmp_path):
    from app.core.runtime_artifacts import pinned_runtime_output_root
    run, calls, _, _, _ = direct_scene
    with pinned_runtime_output_root(tmp_path):
        response = run(metadata={"vista_direct_grounding":{"refine":True}})
    assert response.success, response.error
    assert len(calls) == 2
    result = response.data["result"]
    assert result["model_io"]["attempt_count"] == 2
    assert result["pre_click_decision"]["selected_click_point"] == {"x":128,"y":300}


def test_explicit_local_max_edge_uses_processed_image_and_original_coordinates(direct_scene, tmp_path):
    from app.core.runtime_artifacts import pinned_runtime_output_root
    run, calls, state, _, image = direct_scene
    state["raw"] = '{"point":{"x":100,"y":150,"coordinate_space":"pixel"},"confidence":0.9}'
    with pinned_runtime_output_root(tmp_path):
        response = run(metadata={"vista_direct_grounding": {"max_edge": 400}})
    assert response.success, response.error
    assert len(calls) == 1 and calls[0]["image_path"] != str(image)
    with Image.open(calls[0]["image_path"]) as inference_image:
        assert inference_image.size == (400, 300)
    result = response.data["result"]
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 200, "y": 300}
    assert result["capture_identity"]["image_size"] == {"width": 800, "height": 600}
    assert result["parse_result"]["vista_point_grounding"]["inference_image_size"] == {"width": 400, "height": 300}


def test_resized_local_point_outside_inference_image_is_rejected(direct_scene, tmp_path):
    from app.core.runtime_artifacts import pinned_runtime_output_root
    run, calls, state, _, _ = direct_scene
    state["raw"] = '{"point":{"x":450,"y":150,"coordinate_space":"pixel"}}'
    with pinned_runtime_output_root(tmp_path):
        response = run(metadata={"vista_direct_grounding": {"max_edge": 400}})
    assert response.success is False
    assert len(calls) == 1
    assert "direct_visual_model_point_outside_image" in str(response.error.details)


@pytest.mark.parametrize("scale,origin", [(0, 0), (-1, 0), (float("inf"), 0), (1, -50), (2, 790)])
def test_direct_coordinate_transform_cannot_silently_clamp(scale, origin):
    with pytest.raises(ValueError, match="direct_visual_coordinate_transform_invalid"):
        vision._map_vista_processed_point_to_original({"x": 20, "y": 20},
            original_image_size=ImageSize(width=800, height=600), strict_direct_visual=True,
            coordinate_transform={"origin_original": {"x": origin, "y": 0},
                "scale_processed_to_original": {"x": scale, "y": 1}})


def test_final_submit_has_no_recommended_candidate_even_with_model_point(direct_scene):
    run, calls, _, _, _ = direct_scene
    response = run(metadata={"visual_target":{"name":"Submit application","control_type":"Button"}})
    assert response.success, response.error
    result = response.data["result"]
    assert result["pre_click_decision"]["allowed"] is False
    assert result["candidate_result"]["recommended_candidate_id"] is None
    assert result["recommended_target"] is None


def test_api_selection_uses_api_provider_without_local_point_model(direct_scene):
    run, calls, state, _, _ = direct_scene
    provider_calls = []
    def analyze(req):
        provider_calls.append(req)
        return VisionAnalyzeResponse(provider="api", screen_summary="fresh visual", state_guess=None,
            image_size=ImageSize(width=800, height=600), targets=[VisionTarget(target_id="reports",
                label="reports", bbox=BBox(x=180,y=280,w=40,h=40), kind="button", clickable_confidence=0.95)],
            raw_response={"mode": "endpoint"})
    state["provider"] = SimpleNamespace(analyze=analyze)
    response = run(provider_mode="api")
    assert response.success, response.error
    assert len(provider_calls) == 1 and calls == []
    assert response.data["result"]["pre_click_decision"]["selected_click_point"] == {"x":200,"y":300}


def test_learning_does_not_enter_direct_branch(tmp_path, monkeypatch):
    image = tmp_path / "learning.png"
    Image.new("RGB", (800, 600), "white").save(image)
    marker = object()
    monkeypatch.setattr(vision.VisionProviderFactory, "load_config", lambda: {"vision": {"local": {
        "output_contract": "vista_point_v1"}}})
    monkeypatch.setattr(vision.VisionProviderFactory, "create", lambda **kw: object())
    monkeypatch.setattr(vision, "_load_observe_trace_reuse", lambda *args, **kwargs: {})
    monkeypatch.setattr(vision, "_build_path_graph_recall", lambda **kwargs: {})
    monkeypatch.setattr(vision, "_build_visual_asset_recall", lambda **kwargs: {})
    monkeypatch.setattr(vision, "_recognition_plan_from_vista_point", lambda **kwargs: marker)
    response = vision.recognition_plan(VisionRecognitionPlanRequestModel(image_path=str(image),
        agent_mode="learn", metadata={"execution_grounding":"direct_visual"}))
    assert response is marker
