from __future__ import annotations

from app.api import vision as vision_api
from app.models.request import VisionLocateTargetRequestModel, VisionObserveScreenRequestModel
from app.models.response import APIResponse


def test_observe_screen_wraps_live_capture_and_screen_reading(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-trace.json")

    def fake_screen_reading(request):
        assert request.image_path == "screen.png"
        assert request.metadata["ocr_anchors"]["enabled"] is True
        return APIResponse(
            success=True,
            message="ok",
            data={"result": {"state_guess": "job results list", "screen_reading": {"ui": {"elements": []}}}},
            error=None,
        )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="demo"))

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "screen_observation_v1"
    assert result["live_capture"]["image_path"] == "screen.png"
    assert result["suggested_state_hint"] == "job results list"
    assert "suggested_state_hint" in result["agent_next_steps"][1]
    assert "POST /vision/locate_target" in result["agent_next_steps"][2]


def test_locate_target_wraps_recognition_plan_without_clicking(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "locate-trace.json")

    def fake_recognition_plan(request):
        assert request.goal == "click home"
        assert request.metadata["ocr_anchors"]["max_anchors"] == "all"
        assert "Precision-localization stage only" in request.metadata["prompt_overrides"]["additional_rules"]
        assert 'text_inclusion_policy="exclude_text"' in request.metadata["prompt_overrides"]["additional_rules"]
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "pre_click_decision": {"allowed": True, "selected_click_point": {"x": 10, "y": 20}},
                    "recommended_target": {"label": "home", "element": {"bbox": {"x": 4, "y": 14, "w": 12, "h": 12}, "click_point": {"x": 10, "y": 20}}},
                    "execution_path": {"ocr_anchor_grounding_used": True},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition_plan)

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="click home",
            app_name="demo",
            metadata={
                "prompt_overrides": {
                    "additional_rules": (
                        'Precision-localization stage only. '
                        'For icon-only targets set text_inclusion_policy="exclude_text".'
                    )
                }
            },
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "target_location_v1"
    assert result["selected_click_point"] == {"x": 10, "y": 20}
    assert result["located_bbox"] == {"x": 4, "y": 14, "w": 12, "h": 12}
    assert result["located_point"] == {"x": 10, "y": 20}
    assert result["location_status"] == "pre_click_verified"
    assert result["execution_path"]["action_executed"] is False
    assert result["execution_path"]["located_coordinate_source"] == "recommended_target.element.click_point"
    assert result["execution_path"]["agent_must_call_for_click"] == "POST /action/execute_recognition_plan"
