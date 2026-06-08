from __future__ import annotations

from app.api import vision as vision_api
from app.models.request import VisionLocateTargetRequestModel, VisionObserveScreenRequestModel
from app.models.request import VisionRecognitionPlanRequestModel
from app.models.response import APIResponse
from app.vision.schemas import ImageSize


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
            data={
                "result": {
                    "image_size": {"width": 900, "height": 700},
                    "state_guess": "job results list",
                    "screen_summary": "A job results page with filters and result cards.",
                    "texts": [
                        {
                            "id": "text_docs",
                            "text": "Docs",
                            "bbox": {"x": 240, "y": 96, "w": 42, "h": 18},
                            "confidence": 0.94,
                        },
                        {
                            "id": "text_card_title",
                            "text": "回报率测试",
                            "bbox": {"x": 320, "y": 310, "w": 80, "h": 22},
                            "confidence": 0.98,
                        },
                        {
                            "id": "text_card_body",
                            "text": "Hz轮询率",
                            "bbox": {"x": 322, "y": 340, "w": 68, "h": 18},
                            "confidence": 0.96,
                        },
                        {
                            "id": "text_apply",
                            "text": "Apply now",
                            "bbox": {"x": 360, "y": 360, "w": 74, "h": 24},
                            "confidence": 0.96,
                        }
                    ],
                    "screen_reading": {
                        "ui": {
                            "elements": [
                                {
                                    "id": "element_filter",
                                    "label": "Filter",
                                    "type": "button",
                                    "bbox": {"x": 20, "y": 30, "w": 80, "h": 32},
                                    "click_point": {"x": 60, "y": 46},
                                    "confidence": 0.88,
                                    "evidence": {
                                        "interaction_policy": {
                                            "allowed": True,
                                            "reasons": ["nav_control"],
                                        }
                                    },
                                    "verification_hints": {"expected_changes": ["filter panel opens"]},
                                },
                                {
                                    "id": "element_delete",
                                    "label": "Delete",
                                    "type": "button",
                                    "bbox": {"x": 120, "y": 30, "w": 80, "h": 32},
                                    "click_point": {"x": 160, "y": 46},
                                    "confidence": 0.8,
                                },
                            ],
                        }
                    },
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="demo"))

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "screen_observation_v1"
    assert result["live_capture"]["image_path"] == "screen.png"
    assert result["suggested_state_hint"] == "job results list"
    assert result["screen_map"]["contract_version"] == "screen_map_v1"
    assert result["screen_map"]["state_id"].startswith("state_")
    assert result["screen_map"]["summary"]["section_count"] >= 4
    assert result["screen_map"]["summary"]["candidate_count"] >= 6
    assert result["screen_map"]["sections"][0]["contract_version"] == "screen_map_section_v1"
    assert result["screen_map"]["candidates"][0]["label"] == "Filter"
    assert result["screen_map"]["candidates"][0]["section_id"]
    assert result["screen_map"]["candidates"][0]["risk_class"] == "safe_click_allowed"
    assert result["screen_map"]["candidates"][0]["expected_effect"] == "filter panel opens"
    assert result["screen_map"]["candidates"][1]["risk_class"] == "requires_user_confirmation"
    candidates = result["screen_map"]["candidates"]
    docs = next(item for item in candidates if item["label"] == "Docs")
    assert docs["role"] == "nav_text_action"
    assert docs["section_id"] == "page_header"
    card = next(item for item in candidates if item["label"] == "回报率测试" and item["source"] == "ocr_card_groups")
    assert card["bbox"]["w"] > 80
    assert card["bbox"]["h"] > 22
    assert card["section_id"] == "main_content"
    assert any(item["label"] == "Apply now" and item["source"] == "ocr_text_actions" for item in candidates)
    assert "screen_map.state_id" in result["agent_next_steps"][1]
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


def test_locate_target_surfaces_review_candidate_from_rejected_list(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", None),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "locate-trace.json")

    def fake_recognition_plan(_request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "pre_click_decision": {"allowed": False, "selected_click_point": None},
                    "recommended_target": None,
                    "candidate_result": {
                        "candidates": [],
                        "rejected": [
                            {
                                "candidate_id": "candidate_review_target",
                                "label": "review target",
                                "element": {
                                    "bbox": {"x": 53, "y": 425, "w": 172, "h": 21},
                                    "click_point": {"x": 139, "y": 436},
                                    "interaction_policy": {
                                        "allowed": False,
                                        "zone_type": "precise_text_target",
                                        "priority": "review",
                                        "ad_risk": 0.0,
                                        "reasons": ["precision_text_grounding_requires_confirmation"],
                                    },
                                },
                            }
                        ],
                    },
                    "execution_path": {"ocr_anchor_grounding_used": True},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition_plan)

    response = vision_api.locate_target(VisionLocateTargetRequestModel(goal="select first acceleration", app_name="demo"))

    assert response.success is True
    result = response.data["result"]
    assert result["location_status"] == "requires_pre_click_confirmation"
    assert result["located_bbox"] == {"x": 53, "y": 425, "w": 172, "h": 21}
    assert result["located_point"] == {"x": 139, "y": 436}
    assert result["recommended_target"]["candidate_id"] == "candidate_review_target"
    assert result["execution_path"]["located_coordinate_source"] == "candidate_result.rejected[0]"


def test_recognition_plan_reuses_observe_ocr_anchors_without_rescanning(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")

    def fail_scan(_path):
        raise AssertionError("OCR should be reused from observe trace")

    monkeypatch.setattr(vision_api.ocr_service, "scan_image", fail_scan)

    reused_anchors = {
        "contract_version": "ocr_anchors_v1",
        "image_path": str(image_path),
        "coordinate_space": "original_image",
        "image_size": {"width": 100, "height": 80},
        "anchor_count": 1,
        "anchors": [
            {
                "anchor_id": "ocr_anchor_1",
                "text": "Start",
                "bbox": {"x": 10, "y": 12, "w": 40, "h": 16},
                "center": {"x": 30, "y": 20},
                "confidence": 0.99,
            }
        ],
    }

    vision_request, ocr_result, anchor_payload, status = vision_api._recognition_vision_request_with_ocr_anchors(
        VisionRecognitionPlanRequestModel(
            image_path=str(image_path),
            goal="Start",
            metadata={
                "reused_ocr_anchors": reused_anchors,
                "reused_ocr_source_trace_path": "observe-trace.json",
                "ocr_anchors": {"enabled": True, "max_anchors": "all"},
            },
        ),
        image_path=image_path,
        image_size=ImageSize(width=100, height=80),
    )

    assert ocr_result is None
    assert anchor_payload is not None
    assert anchor_payload["anchor_count"] == 1
    assert status["reused"] is True
    assert status["source_trace_path"] == "observe-trace.json"
    assert vision_request.metadata["ocr_anchors"]["anchors"][0]["text"] == "Start"
    assert "reused_ocr_anchors" not in vision_request.metadata


def test_locate_reuse_builds_ocr_anchors_from_observe_trace_texts(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")
    trace_path = tmp_path / "observe.json"
    trace_path.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 200, "height": 120},
                    "texts": [
                        {
                            "id": "text_start",
                            "text": "Start",
                            "bbox": {"x": 20, "y": 30, "w": 50, "h": 20},
                            "confidence": 0.97,
                        }
                    ],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "candidates": [{"label": "Start"}],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reuse = vision_api._load_observe_trace_reuse(str(trace_path), image_path=str(image_path), goal="Start")

    assert reuse["status"] == "ready"
    assert reuse["anchor_source"] == "observe_trace_texts"
    assert reuse["anchor_count"] == 1
    assert reuse["ocr_anchors"]["anchors"][0]["text"] == "Start"
    assert reuse["ocr_anchors"]["anchors"][0]["goal_similarity"] == 1.0
    assert reuse["state_id"] == "state_demo"
