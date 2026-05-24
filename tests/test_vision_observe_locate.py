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
        return APIResponse(success=True, message="ok", data={"result": {"screen_reading": {"ui": {"elements": []}}}}, error=None)

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="demo"))

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "screen_observation_v1"
    assert result["live_capture"]["image_path"] == "screen.png"
    assert "POST /vision/locate_target" in result["agent_next_steps"][1]


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
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "pre_click_decision": {"allowed": True, "selected_click_point": {"x": 10, "y": 20}},
                    "recommended_target": {"label": "home"},
                    "execution_path": {"ocr_anchor_grounding_used": True},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition_plan)

    response = vision_api.locate_target(VisionLocateTargetRequestModel(goal="click home", app_name="demo"))

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "target_location_v1"
    assert result["selected_click_point"] == {"x": 10, "y": 20}
    assert result["execution_path"]["action_executed"] is False
    assert result["execution_path"]["agent_must_call_for_click"] == "POST /action/execute_recognition_plan"
